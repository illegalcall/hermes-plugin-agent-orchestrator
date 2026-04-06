"""Tool handler functions for the AO Hermes plugin.

Each handler receives (args: dict, **kwargs) and returns a JSON string.
Handlers must not raise — all errors are caught and returned as JSON.
"""

import json
import logging

from .ao_client import AOClient
from .utils import (
    MAX_MESSAGE_LEN,
    format_issue_list,
    format_session_list,
    truncate,
    validate_issue_id,
    validate_session_id,
)

logger = logging.getLogger("hermes-ao")


def _ok(text: str) -> str:
    return json.dumps({"ok": True, "result": text})


def _err(text: str) -> str:
    return json.dumps({"ok": False, "error": text})


# ── Phase 1 handlers ────────────────────────────────────────────────


def make_ao_sessions(client: AOClient):
    """Create ao_sessions handler bound to client."""

    def handler(args: dict, **kwargs) -> str:
        try:
            active_only = args.get("active_only", True)
            project = args.get("project")

            result = client.get_sessions(project=project, active_only=active_only)
            if not result["ok"]:
                return _err(result["error"])

            data = result["data"]

            # Handle both structured and raw responses
            if isinstance(data, dict):
                sessions = data.get("sessions", [])
                stats = data.get("stats")
                text = format_session_list(sessions)
                if stats:
                    text += f"\n\nStats: {json.dumps(stats)}"
                return _ok(text)

            return _ok(str(data))
        except Exception as e:
            logger.exception("ao_sessions failed")
            return _err(f"Unexpected error: {e}")

    return handler


def make_ao_issues(client: AOClient):
    """Create ao_issues handler bound to client."""

    def handler(args: dict, **kwargs) -> str:
        try:
            project = args.get("project")
            labels = args.get("labels")

            result = client.get_issues(project=project, label=labels)
            if not result["ok"]:
                return _err(result["error"])

            data = result["data"]

            if isinstance(data, dict):
                issues = data.get("issues", [])
                text = format_issue_list(issues)
                return _ok(text)

            return _ok(str(data))
        except Exception as e:
            logger.exception("ao_issues failed")
            return _err(f"Unexpected error: {e}")

    return handler


def make_ao_spawn(client: AOClient):
    """Create ao_spawn handler bound to client.

    Auto-resolves the project when only one is configured.
    """
    _cached_project: list[str | None] = [None]  # mutable container for nonlocal

    def _resolve_default_project() -> str | None:
        if _cached_project[0] is not None:
            return _cached_project[0]
        try:
            result = client.get_projects()
            if result["ok"] and isinstance(result["data"], dict):
                projects = result["data"].get("projects", {})
                if isinstance(projects, dict) and len(projects) == 1:
                    _cached_project[0] = next(iter(projects))
                    return _cached_project[0]
        except Exception:
            pass
        return None

    def handler(args: dict, **kwargs) -> str:
        try:
            mode = args.get("mode", "single")
            project = args.get("project") or _resolve_default_project()
            issue = args.get("issue")
            issues = args.get("issues")

            if not project:
                return _err(
                    "Project ID is required — multiple projects configured or project "
                    "list unavailable. Provide it in the 'project' parameter."
                )

            # Orchestrator mode
            if mode == "orchestrator":
                result = client.spawn_orchestrator(project)
                if not result["ok"]:
                    return _err(result["error"])
                return _ok(
                    f"Orchestrator spawned for project '{project}'.\n{json.dumps(result['data'])}"
                )

            # Batch mode
            if mode == "batch":
                if not issues:
                    return _err("Batch mode requires 'issues' array.")
                results = []
                for iss in issues:
                    clean = validate_issue_id(iss)
                    if not clean:
                        results.append(f"#{iss}: invalid issue ID, skipped")
                        continue
                    r = client.spawn(project, issue_id=clean)
                    if r["ok"]:
                        results.append(f"#{clean}: spawned")
                    else:
                        results.append(f"#{clean}: {r['error']}")
                return _ok("\n".join(results))

            # Single mode (default)
            clean_issue = None
            if issue:
                clean_issue = validate_issue_id(issue)
                if not clean_issue:
                    return _err(f"Invalid issue ID: {issue}")

            result = client.spawn(project, issue_id=clean_issue)
            if not result["ok"]:
                return _err(result["error"])

            data = result["data"]
            if isinstance(data, dict):
                sid = data.get("session", {}).get("id", data.get("raw", ""))
                msg = "Agent spawned"
                if clean_issue:
                    msg += f" for #{clean_issue}"
                if sid:
                    msg += f" (session: {sid})"
                return _ok(msg)

            return _ok(f"Agent spawned. {data}")
        except Exception as e:
            logger.exception("ao_spawn failed")
            return _err(f"Unexpected error: {e}")

    return handler


def make_ao_send(client: AOClient):
    """Create ao_send handler bound to client."""

    def handler(args: dict, **kwargs) -> str:
        try:
            session_id = args.get("session_id", "")
            message = args.get("message", "")

            clean_sid = validate_session_id(session_id)
            if not clean_sid:
                return _err(f"Invalid session ID: {session_id}")

            if not message:
                return _err("Message cannot be empty.")

            if len(message) > MAX_MESSAGE_LEN:
                return _err(f"Message too long ({len(message)} chars, max {MAX_MESSAGE_LEN}).")

            result = client.send(clean_sid, message)
            if not result["ok"]:
                return _err(result["error"])

            return _ok(f"Message sent to {clean_sid}.")
        except Exception as e:
            logger.exception("ao_send failed")
            return _err(f"Unexpected error: {e}")

    return handler


def make_ao_kill(client: AOClient):
    """Create ao_kill handler bound to client."""

    def handler(args: dict, **kwargs) -> str:
        try:
            session_id = args.get("session_id", "")

            clean_sid = validate_session_id(session_id)
            if not clean_sid:
                return _err(f"Invalid session ID: {session_id}")

            result = client.kill(clean_sid)
            if not result["ok"]:
                return _err(result["error"])

            return _ok(f"Session {clean_sid} killed.")
        except Exception as e:
            logger.exception("ao_kill failed")
            return _err(f"Unexpected error: {e}")

    return handler


# ── Phase 2 handlers ────────────────────────────────────────────────


def make_ao_doctor(client: AOClient):
    def handler(args: dict, **kwargs) -> str:
        try:
            result = client.doctor()
            if not result["ok"]:
                return _err(result["error"])
            return _ok(result["data"])
        except Exception as e:
            logger.exception("ao_doctor failed")
            return _err(f"Unexpected error: {e}")

    return handler


def make_ao_review_check(client: AOClient):
    def handler(args: dict, **kwargs) -> str:
        try:
            project = args.get("project")
            dry_run = args.get("dry_run", False)
            result = client.review_check(project=project, dry_run=dry_run)
            if not result["ok"]:
                return _err(result["error"])
            return _ok(result["data"])
        except Exception as e:
            logger.exception("ao_review_check failed")
            return _err(f"Unexpected error: {e}")

    return handler


def make_ao_verify(client: AOClient):
    def handler(args: dict, **kwargs) -> str:
        try:
            list_mode = args.get("list", False)
            issue = args.get("issue")
            project = args.get("project")
            fail = args.get("fail", False)
            comment = args.get("comment")

            clean_issue = None
            if issue:
                clean_issue = validate_issue_id(issue)
                if not clean_issue and not list_mode:
                    return _err(f"Invalid issue ID: {issue}")

            result = client.verify(
                issue=clean_issue,
                project=project,
                fail=fail,
                comment=comment,
                list_mode=list_mode,
            )
            if not result["ok"]:
                return _err(result["error"])

            data = result["data"]
            if isinstance(data, dict):
                return _ok(json.dumps(data, indent=2))
            return _ok(str(data))
        except Exception as e:
            logger.exception("ao_verify failed")
            return _err(f"Unexpected error: {e}")

    return handler


def make_ao_session_cleanup(client: AOClient):
    def handler(args: dict, **kwargs) -> str:
        try:
            project = args.get("project")
            dry_run = args.get("dry_run", False)
            result = client.session_cleanup(project=project, dry_run=dry_run)
            if not result["ok"]:
                return _err(result["error"])
            return _ok(result["data"])
        except Exception as e:
            logger.exception("ao_session_cleanup failed")
            return _err(f"Unexpected error: {e}")

    return handler


def make_ao_session_restore(client: AOClient):
    def handler(args: dict, **kwargs) -> str:
        try:
            session_id = args.get("session_id", "")
            clean_sid = validate_session_id(session_id)
            if not clean_sid:
                return _err(f"Invalid session ID: {session_id}")
            result = client.session_restore(clean_sid)
            if not result["ok"]:
                return _err(result["error"])
            data = result["data"]
            if isinstance(data, dict):
                return _ok(json.dumps(data, indent=2))
            return _ok(str(data))
        except Exception as e:
            logger.exception("ao_session_restore failed")
            return _err(f"Unexpected error: {e}")

    return handler


def make_ao_session_claim_pr(client: AOClient):
    def handler(args: dict, **kwargs) -> str:
        try:
            pr = args.get("pr", "")
            session_id = args.get("session_id")
            assign = args.get("assign_on_github", False)
            if not pr:
                return _err("PR number or URL is required.")
            if session_id:
                clean_sid = validate_session_id(session_id)
                if not clean_sid:
                    return _err(f"Invalid session ID: {session_id}")
                session_id = clean_sid
            result = client.session_claim_pr(pr, session_id=session_id, assign_on_github=assign)
            if not result["ok"]:
                return _err(result["error"])
            return _ok(
                result["data"] if isinstance(result["data"], str) else json.dumps(result["data"])
            )
        except Exception as e:
            logger.exception("ao_session_claim_pr failed")
            return _err(f"Unexpected error: {e}")

    return handler


# ── Phase 3 handlers ────────────────────────────────────────────────


def make_ao_create_issue(client: AOClient):
    def handler(args: dict, **kwargs) -> str:
        try:
            project = args.get("project", "")
            title = args.get("title", "")
            description = args.get("description", "")
            add_to_backlog = args.get("add_to_backlog", False)

            if not project:
                return _err("Project ID is required.")
            if not title:
                return _err("Title is required.")

            title = truncate(title, 200)
            description = truncate(description, 4000)

            result = client.create_issue(project, title, description, add_to_backlog)
            if not result["ok"]:
                return _err(result["error"])
            data = result["data"]
            if isinstance(data, dict):
                return _ok(json.dumps(data, indent=2))
            return _ok(str(data))
        except Exception as e:
            logger.exception("ao_create_issue failed")
            return _err(f"Unexpected error: {e}")

    return handler


def make_ao_list_projects(client: AOClient):
    def handler(args: dict, **kwargs) -> str:
        try:
            result = client.get_projects()
            if not result["ok"]:
                return _err(result["error"])
            data = result["data"]
            if isinstance(data, dict):
                return _ok(json.dumps(data, indent=2))
            return _ok(str(data))
        except Exception as e:
            logger.exception("ao_list_projects failed")
            return _err(f"Unexpected error: {e}")

    return handler


def make_ao_backlog(client: AOClient):
    def handler(args: dict, **kwargs) -> str:
        try:
            result = client.get_backlog()
            if not result["ok"]:
                return _err(result["error"])
            data = result["data"]
            if isinstance(data, dict):
                issues = data.get("issues", [])
                return _ok(format_issue_list(issues))
            return _ok(str(data))
        except Exception as e:
            logger.exception("ao_backlog failed")
            return _err(f"Unexpected error: {e}")

    return handler


def make_ao_merge_pr(client: AOClient):
    def handler(args: dict, **kwargs) -> str:
        try:
            pr_number = args.get("pr_number")
            try:
                pr_number = int(pr_number)
            except (TypeError, ValueError):
                return _err("pr_number (integer) is required.")
            result = client.merge_pr(pr_number)
            if not result["ok"]:
                return _err(result["error"])
            return _ok(f"PR #{pr_number} merged successfully.")
        except Exception as e:
            logger.exception("ao_merge_pr failed")
            return _err(f"Unexpected error: {e}")

    return handler


def make_ao_observability(client: AOClient):
    def handler(args: dict, **kwargs) -> str:
        try:
            result = client.get_observability()
            if not result["ok"]:
                return _err(result["error"])
            data = result["data"]
            if isinstance(data, dict):
                return _ok(json.dumps(data, indent=2))
            return _ok(str(data))
        except Exception as e:
            logger.exception("ao_observability failed")
            return _err(f"Unexpected error: {e}")

    return handler


def make_ao_session_output(client: AOClient):
    def handler(args: dict, **kwargs) -> str:
        try:
            session_id = args.get("session_id", "")
            clean_sid = validate_session_id(session_id)
            if not clean_sid:
                return _err(f"Invalid session ID: {session_id}")
            result = client.get_session_output(clean_sid)
            if not result["ok"]:
                return _err(result["error"])
            data = result["data"]
            if isinstance(data, dict):
                return _ok(json.dumps(data, indent=2))
            return _ok(str(data))
        except Exception as e:
            logger.exception("ao_session_output failed")
            return _err(f"Unexpected error: {e}")

    return handler
