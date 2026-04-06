"""AO API client with REST-first transport, 3-state circuit breaker, and CLI fallback."""

import json
import logging
import os
import subprocess
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from .config import PluginConfig

logger = logging.getLogger("hermes-ao")

# Circuit breaker states
CB_CLOSED = "closed"
CB_OPEN = "open"
CB_HALF_OPEN = "half_open"

# Circuit breaker defaults
CB_FAILURE_THRESHOLD = 3
CB_INITIAL_BACKOFF_S = 15
CB_MAX_BACKOFF_S = 300  # 5 minutes


class AOClient:
    """Unified AO API client. Prefers REST API, falls back to CLI.

    Every public method returns:
        {"ok": True, "data": <parsed JSON or string>}
        {"ok": False, "error": "<message>"}
    """

    def __init__(self, config: PluginConfig):
        self.base_url = config.api_base_url.rstrip("/")
        self.ao_path = config.ao_path
        self.ao_cwd = config.ao_cwd
        self.gh_path = config.gh_path
        self.api_timeout = config.api_timeout_s
        self.spawn_timeout = config.spawn_timeout_s
        self.cli_timeout = config.cli_timeout_s

        # Circuit breaker state (protected by lock)
        self._lock = threading.Lock()
        self._cb_state = CB_CLOSED
        self._cb_failures = 0
        self._cb_backoff_s = CB_INITIAL_BACKOFF_S
        self._cb_open_until = 0.0  # timestamp

        # Health tracking
        self.last_healthy_at: float | None = None

    # ── Circuit breaker ──────────────────────────────────────────────

    def _cb_can_request(self) -> bool:
        """Check if the circuit breaker allows a request."""
        with self._lock:
            if self._cb_state == CB_CLOSED:
                return True
            if self._cb_state == CB_OPEN:
                if time.time() >= self._cb_open_until:
                    self._cb_state = CB_HALF_OPEN
                    logger.info("Circuit breaker -> half_open (probing)")
                    return True
                return False
            # half_open: allow one probe
            return True

    def _cb_record_success(self) -> None:
        """Record a successful API call."""
        with self._lock:
            if self._cb_state != CB_CLOSED:
                logger.info("Circuit breaker -> closed (API recovered)")
            self._cb_state = CB_CLOSED
            self._cb_failures = 0
            self._cb_backoff_s = CB_INITIAL_BACKOFF_S
            self.last_healthy_at = time.time()

    def _cb_record_failure(self) -> None:
        """Record a failed API call."""
        with self._lock:
            self._cb_failures += 1
            if self._cb_state == CB_HALF_OPEN or self._cb_failures >= CB_FAILURE_THRESHOLD:
                self._cb_state = CB_OPEN
                self._cb_open_until = time.time() + self._cb_backoff_s
                logger.info(
                    "Circuit breaker -> open (backoff=%ds, failures=%d)",
                    self._cb_backoff_s,
                    self._cb_failures,
                )
                self._cb_backoff_s = min(self._cb_backoff_s * 2, CB_MAX_BACKOFF_S)

    # ── Low-level transport ──────────────────────────────────────────

    def _api_request(
        self, method: str, path: str, body: dict | None = None, timeout: int | None = None
    ) -> dict:
        """Make HTTP request to AO dashboard. Returns parsed JSON."""
        url = f"{self.base_url}{path}"
        data = json.dumps(body).encode("utf-8") if body else None
        headers = {"Content-Type": "application/json"} if data else {}
        req = Request(url, data=data, headers=headers, method=method)
        t0 = time.time()
        try:
            with urlopen(req, timeout=timeout or self.api_timeout) as resp:
                raw = resp.read().decode("utf-8")
                elapsed = time.time() - t0
                logger.debug("API %s %s -> %d (%.1fs)", method, path, resp.status, elapsed)
                return json.loads(raw) if raw.strip() else {}
        except HTTPError as e:
            elapsed = time.time() - t0
            body_text = ""
            import contextlib

            with contextlib.suppress(Exception):
                body_text = e.read().decode("utf-8", errors="replace")
            logger.debug("API %s %s -> %d (%.1fs)", method, path, e.code, elapsed)
            error_msg = ""
            try:
                error_data = json.loads(body_text)
                error_msg = error_data.get("error", body_text)
            except (json.JSONDecodeError, AttributeError):
                error_msg = body_text or str(e)
            raise APIError(e.code, error_msg) from e

    def _try_api(
        self, method: str, path: str, body: dict | None = None, timeout: int | None = None
    ) -> dict:
        """Attempt API call with circuit breaker. Returns result dict."""
        if not self._cb_can_request():
            return {"ok": False, "error": "API circuit breaker open"}

        try:
            data = self._api_request(method, path, body, timeout)
            self._cb_record_success()
            return {"ok": True, "data": data}
        except APIError as e:
            # 4xx errors are not connection failures — don't trip the breaker
            if e.status_code and 400 <= e.status_code < 500:
                self._cb_record_success()  # API is reachable
                return {"ok": False, "error": e.message}
            self._cb_record_failure()
            return {"ok": False, "error": e.message}
        except json.JSONDecodeError as e:
            # API returned non-JSON response — API is reachable, just unexpected format
            self._cb_record_success()
            return {"ok": False, "error": f"Invalid JSON response: {e}"}
        except (URLError, OSError, TimeoutError) as e:
            self._cb_record_failure()
            return {"ok": False, "error": f"Connection failed: {e}"}

    def _try_cli(self, args: list[str], timeout: int | None = None, cwd: str | None = None) -> dict:
        """Run an AO CLI command. Returns result dict."""
        cmd = [self.ao_path] + args
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout or self.cli_timeout,
                cwd=cwd or self.ao_cwd,
                env=_cli_env(),
            )
            if result.returncode == 0:
                return {"ok": True, "data": result.stdout.strip()}
            return {"ok": False, "error": result.stderr.strip() or result.stdout.strip()}
        except FileNotFoundError:
            return {"ok": False, "error": f"CLI binary not found: {self.ao_path}"}
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": f"CLI timed out after {timeout or self.cli_timeout}s"}
        except Exception as e:
            return {"ok": False, "error": f"CLI error: {e}"}

    def _try_gh(self, args: list[str], timeout: int | None = None) -> dict:
        """Run a GitHub CLI command. Returns result dict."""
        cmd = [self.gh_path] + args
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout or self.cli_timeout,
                cwd=self.ao_cwd,
                env=_cli_env(),
            )
            if result.returncode == 0:
                return {"ok": True, "data": result.stdout.strip()}
            return {"ok": False, "error": result.stderr.strip() or result.stdout.strip()}
        except FileNotFoundError:
            return {"ok": False, "error": f"CLI binary not found: {self.gh_path}"}
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": f"gh timed out after {timeout or self.cli_timeout}s"}
        except Exception as e:
            return {"ok": False, "error": f"gh error: {e}"}

    # ── Public methods ───────────────────────────────────────────────

    def get_sessions(self, project: str | None = None, active_only: bool = False) -> dict:
        """Get sessions list."""
        params = []
        if project:
            params.append(f"project={quote(project, safe='')}")
        if active_only:
            params.append("active=true")
        qs = "&".join(params)
        path = f"/api/sessions{'?' + qs if qs else ''}"

        result = self._try_api("GET", path)
        if result["ok"]:
            return result

        # CLI fallback
        cli_args = ["status", "--json"]
        if project:
            cli_args.extend(["-p", project])
        cli_result = self._try_cli(cli_args)
        if cli_result["ok"]:
            try:
                data = json.loads(cli_result["data"])
                return {"ok": True, "data": data}
            except json.JSONDecodeError:
                return {"ok": True, "data": {"raw": cli_result["data"]}}
        return _both_failed(result, cli_result)

    def get_issues(
        self, project: str | None = None, state: str = "open", label: str | None = None
    ) -> dict:
        """Get GitHub issues."""
        params = [f"state={quote(state, safe='')}"]
        if project:
            params.append(f"project={quote(project, safe='')}")
        if label:
            params.append(f"label={quote(label, safe='')}")
        qs = "&".join(params)
        path = f"/api/issues?{qs}"

        result = self._try_api("GET", path)
        if result["ok"]:
            return result

        # CLI fallback via gh
        gh_args = [
            "issue",
            "list",
            "--state",
            state,
            "--json",
            "number,title,labels,state,url",
            "--limit",
            "30",
        ]
        if label:
            gh_args.extend(["--label", label])
        cli_result = self._try_gh(gh_args)
        if cli_result["ok"]:
            try:
                issues_raw = json.loads(cli_result["data"])
                issues = [
                    {
                        "id": str(i.get("number", "")),
                        "title": i.get("title", ""),
                        "labels": [lbl.get("name", "") for lbl in i.get("labels", [])],
                        "state": i.get("state", ""),
                        "url": i.get("url", ""),
                    }
                    for i in issues_raw
                ]
                return {"ok": True, "data": {"issues": issues}}
            except json.JSONDecodeError:
                return {"ok": True, "data": {"raw": cli_result["data"]}}
        return _both_failed(result, cli_result)

    def spawn(self, project_id: str, issue_id: str | None = None) -> dict:
        """Spawn a new agent session."""
        body: dict = {"projectId": project_id}
        if issue_id:
            body["issueId"] = issue_id

        result = self._try_api("POST", "/api/spawn", body=body, timeout=self.spawn_timeout)
        if result["ok"]:
            return result

        # CLI fallback
        cli_args = ["spawn"]
        if issue_id:
            cli_args.append(f"#{issue_id}")
        cli_result = self._try_cli(cli_args, timeout=self.spawn_timeout)
        if cli_result["ok"]:
            return {"ok": True, "data": {"raw": cli_result["data"]}}
        return _both_failed(result, cli_result)

    def send(self, session_id: str, message: str) -> dict:
        """Send a message to a running session."""
        result = self._try_api(
            "POST",
            f"/api/sessions/{session_id}/send",
            body={"message": message},
        )
        if result["ok"]:
            return result

        # CLI fallback (use -- to prevent message being parsed as flags)
        cli_result = self._try_cli(["send", session_id, "--", message])
        if cli_result["ok"]:
            return cli_result
        return _both_failed(result, cli_result)

    def kill(self, session_id: str) -> dict:
        """Kill a session."""
        result = self._try_api("POST", f"/api/sessions/{session_id}/kill")
        if result["ok"]:
            return result

        # CLI fallback
        cli_result = self._try_cli(["session", "kill", session_id])
        if cli_result["ok"]:
            return cli_result
        return _both_failed(result, cli_result)

    def get_projects(self) -> dict:
        """Get configured projects."""
        return self._try_api("GET", "/api/projects")

    # ── CLI-only operations ──────────────────────────────────────────

    def doctor(self) -> dict:
        """Run AO health checks (CLI only)."""
        return self._try_cli(["doctor"], timeout=30)

    def review_check(self, project: str | None = None, dry_run: bool = False) -> dict:
        """Check PRs for review comments (CLI only)."""
        args = ["review-check"]
        if project:
            args.append(project)
        if dry_run:
            args.append("--dry-run")
        return self._try_cli(args, timeout=30)

    def session_cleanup(self, project: str | None = None, dry_run: bool = False) -> dict:
        """Kill sessions with merged PRs / closed issues (CLI only)."""
        args = ["session", "cleanup"]
        if project:
            args.extend(["-p", project])
        if dry_run:
            args.append("--dry-run")
        return self._try_cli(args, timeout=30)

    def session_restore(self, session_id: str) -> dict:
        """Restore a terminated session."""
        result = self._try_api("POST", f"/api/sessions/{session_id}/restore")
        if result["ok"]:
            return result
        cli_result = self._try_cli(["session", "restore", session_id], timeout=30)
        if cli_result["ok"]:
            return cli_result
        return _both_failed(result, cli_result)

    def session_claim_pr(
        self, pr: str, session_id: str | None = None, assign_on_github: bool = False
    ) -> dict:
        """Attach a PR to a session (CLI only)."""
        args = ["session", "claim-pr", pr]
        if session_id:
            args.append(session_id)
        if assign_on_github:
            args.append("--assign-on-github")
        return self._try_cli(args)

    def verify(
        self,
        issue: str | None = None,
        project: str | None = None,
        fail: bool = False,
        comment: str | None = None,
        list_mode: bool = False,
    ) -> dict:
        """Verify an issue or list unverified issues."""
        if list_mode:
            path = "/api/verify"
            if project:
                path += f"?project={quote(project, safe='')}"
            result = self._try_api("GET", path)
            if result["ok"]:
                return result
            args = ["verify", "--list"]
            if project:
                args.extend(["-p", project])
            return self._try_cli(args, timeout=30)

        if not issue:
            return {"ok": False, "error": "issue is required when not using list mode"}

        body: dict = {"issueId": issue, "action": "fail" if fail else "verify"}
        if project:
            body["projectId"] = project
        if comment:
            body["comment"] = comment
        result = self._try_api("POST", "/api/verify", body=body)
        if result["ok"]:
            return result
        args = ["verify", issue]
        if project:
            args.extend(["-p", project])
        if fail:
            args.append("--fail")
        if comment:
            args.extend(["-c", comment])
        return self._try_cli(args, timeout=30)

    # ── Phase 3 — API-first with CLI fallbacks where possible ──────

    def create_issue(
        self, project_id: str, title: str, description: str = "", add_to_backlog: bool = False
    ) -> dict:
        """Create a GitHub issue."""
        result = self._try_api(
            "POST",
            "/api/issues",
            body={
                "projectId": project_id,
                "title": title,
                "description": description,
                "addToBacklog": add_to_backlog,
            },
        )
        if result["ok"]:
            return result

        # CLI fallback via gh
        gh_args = ["issue", "create", "--title", title]
        if description:
            gh_args.extend(["--body", description])
        if add_to_backlog:
            gh_args.extend(["--label", "agent:backlog"])
        cli_result = self._try_gh(gh_args)
        if cli_result["ok"]:
            return {"ok": True, "data": {"raw": cli_result["data"]}}
        return _both_failed(result, cli_result)

    def get_backlog(self) -> dict:
        """Get backlog issues."""
        result = self._try_api("GET", "/api/backlog")
        if result["ok"]:
            return result

        # CLI fallback via gh
        cli_result = self._try_gh(
            [
                "issue",
                "list",
                "--label",
                "agent:backlog",
                "--json",
                "number,title,labels,state,url",
                "--limit",
                "30",
            ]
        )
        if cli_result["ok"]:
            try:
                issues_raw = json.loads(cli_result["data"])
                issues = [
                    {
                        "id": str(i.get("number", "")),
                        "title": i.get("title", ""),
                        "labels": [lbl.get("name", "") for lbl in i.get("labels", [])],
                        "state": i.get("state", ""),
                        "url": i.get("url", ""),
                    }
                    for i in issues_raw
                ]
                return {"ok": True, "data": {"issues": issues}}
            except json.JSONDecodeError:
                return {"ok": True, "data": {"raw": cli_result["data"]}}
        return _both_failed(result, cli_result)

    def merge_pr(self, pr_number: int) -> dict:
        """Merge a pull request."""
        result = self._try_api("POST", f"/api/prs/{pr_number}/merge", timeout=self.spawn_timeout)
        if result["ok"]:
            return result

        # CLI fallback via gh
        cli_result = self._try_gh(
            ["pr", "merge", str(pr_number), "--merge"],
            timeout=self.spawn_timeout,
        )
        if cli_result["ok"]:
            return {"ok": True, "data": {"raw": cli_result["data"]}}
        return _both_failed(result, cli_result)

    def get_observability(self) -> dict:
        """Get system observability data. API-only — no CLI equivalent."""
        return self._try_api("GET", "/api/observability")

    def get_session_output(self, session_id: str) -> dict:
        """Get detailed output/activity for a session."""
        result = self._try_api("GET", f"/api/sessions/{session_id}")
        if result["ok"]:
            return result

        # CLI fallback
        cli_result = self._try_cli(["session", "info", session_id])
        if cli_result["ok"]:
            return {"ok": True, "data": {"raw": cli_result["data"]}}
        return _both_failed(result, cli_result)

    def spawn_orchestrator(self, project_id: str) -> dict:
        """Spawn an orchestrator session."""
        return self._try_api(
            "POST", "/api/orchestrators", body={"projectId": project_id}, timeout=self.spawn_timeout
        )


class APIError(Exception):
    """HTTP API error with status code."""

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"HTTP {status_code}: {message}")


def _both_failed(api_result: dict, cli_result: dict) -> dict:
    """Combine error messages when both API and CLI fail."""
    api_err = api_result.get("error", "unknown")
    cli_err = cli_result.get("error", "unknown")
    return {"ok": False, "error": f"API: {api_err} | CLI: {cli_err}"}


def _cli_env() -> dict:
    """Build environment for CLI subprocesses (suppress color codes)."""
    env = os.environ.copy()
    env["FORCE_COLOR"] = "0"
    env["NO_COLOR"] = "1"
    return env
