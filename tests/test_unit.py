"""Offline unit tests for the AO Hermes plugin.

Zero dependencies beyond Python stdlib. Mocks all HTTP and subprocess calls.
Run: python -m pytest tests/test_unit.py -v
"""

import json
import os
import sys
import time
import unittest
from unittest.mock import MagicMock, patch

# Ensure the package root is importable when running tests directly
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hermes_ao.ao_client import CB_CLOSED, CB_HALF_OPEN, CB_OPEN, AOClient
from hermes_ao.config import PluginConfig, load_config
from hermes_ao.hooks import WORK_TRIGGERS, make_pre_llm_call_hook, notification_queue
from hermes_ao.schemas import PHASE_1, PHASE_2, PHASE_3
from hermes_ao.tools import (
    make_ao_backlog,
    make_ao_create_issue,
    make_ao_doctor,
    make_ao_issues,
    make_ao_kill,
    make_ao_list_projects,
    make_ao_merge_pr,
    make_ao_observability,
    make_ao_review_check,
    make_ao_send,
    make_ao_session_claim_pr,
    make_ao_session_cleanup,
    make_ao_session_output,
    make_ao_session_restore,
    make_ao_sessions,
    make_ao_spawn,
    make_ao_verify,
)
from hermes_ao.utils import (
    format_issue,
    format_issue_list,
    format_session,
    format_session_list,
    truncate,
    validate_issue_id,
    validate_session_id,
)

# ══════════════════════════════════════════════════════════════════════
# Utils
# ══════════════════════════════════════════════════════════════════════


class TestValidateSessionId(unittest.TestCase):
    def test_valid_alphanumeric(self):
        self.assertEqual(validate_session_id("ao-123"), "ao-123")

    def test_valid_underscores(self):
        self.assertEqual(validate_session_id("my_app_1"), "my_app_1")

    def test_rejects_path_traversal(self):
        self.assertIsNone(validate_session_id("../etc/passwd"))

    def test_rejects_spaces(self):
        self.assertIsNone(validate_session_id("ao 1"))

    def test_rejects_empty(self):
        self.assertIsNone(validate_session_id(""))

    def test_rejects_shell_injection(self):
        self.assertIsNone(validate_session_id("$(whoami)"))

    def test_rejects_semicolons(self):
        self.assertIsNone(validate_session_id("ao;rm -rf"))


class TestValidateIssueId(unittest.TestCase):
    def test_number_string(self):
        self.assertEqual(validate_issue_id("42"), "42")

    def test_number_int(self):
        self.assertEqual(validate_issue_id(42), "42")

    def test_hash_prefix(self):
        self.assertEqual(validate_issue_id("#42"), "42")

    def test_rejects_alpha(self):
        self.assertIsNone(validate_issue_id("abc"))

    def test_rejects_empty(self):
        self.assertIsNone(validate_issue_id(""))

    def test_rejects_none(self):
        self.assertIsNone(validate_issue_id(None))

    def test_rejects_mixed(self):
        self.assertIsNone(validate_issue_id("42abc"))


class TestTruncate(unittest.TestCase):
    def test_short_unchanged(self):
        self.assertEqual(truncate("hello", 10), "hello")

    def test_exact_length_unchanged(self):
        self.assertEqual(truncate("hello", 5), "hello")

    def test_long_truncated(self):
        self.assertEqual(truncate("hello world", 8), "hello...")

    def test_ellipsis_length(self):
        result = truncate("a" * 100, 10)
        self.assertEqual(len(result), 10)
        self.assertTrue(result.endswith("..."))


class TestFormatSession(unittest.TestCase):
    def test_basic(self):
        result = format_session({"id": "ao-1", "status": "working"})
        self.assertIn("ao-1", result)
        self.assertIn("working", result)

    def test_with_pr(self):
        result = format_session(
            {
                "id": "ao-1",
                "status": "working",
                "pr": {"number": 42, "ciStatus": "passing"},
            }
        )
        self.assertIn("PR#42", result)
        self.assertIn("passing", result)

    def test_with_branch(self):
        result = format_session({"id": "ao-1", "status": "working", "branch": "feat/123"})
        self.assertIn("feat/123", result)


class TestFormatSessionList(unittest.TestCase):
    def test_empty(self):
        self.assertIn("No sessions", format_session_list([]))

    def test_count(self):
        sessions = [{"id": f"ao-{i}", "status": "working"} for i in range(3)]
        result = format_session_list(sessions)
        self.assertIn("3 session(s)", result)


class TestFormatIssue(unittest.TestCase):
    def test_basic(self):
        result = format_issue({"id": "42", "title": "Fix bug"})
        self.assertIn("#42", result)
        self.assertIn("Fix bug", result)

    def test_with_labels(self):
        result = format_issue({"id": "1", "title": "X", "labels": ["bug", "P1"]})
        self.assertIn("bug", result)
        self.assertIn("P1", result)

    def test_with_index(self):
        result = format_issue({"id": "1", "title": "X"}, index=3)
        self.assertTrue(result.startswith("3."))


class TestFormatIssueList(unittest.TestCase):
    def test_empty(self):
        self.assertIn("No issues", format_issue_list([]))

    def test_numbered(self):
        issues = [{"id": "1", "title": "A"}, {"id": "2", "title": "B"}]
        result = format_issue_list(issues)
        self.assertIn("1.", result)
        self.assertIn("2.", result)


# ══════════════════════════════════════════════════════════════════════
# Config
# ══════════════════════════════════════════════════════════════════════


class TestConfig(unittest.TestCase):
    @patch.dict(os.environ, {"AO_CWD": "/tmp/test"}, clear=False)
    def test_defaults(self):
        config = load_config()
        self.assertEqual(config.api_base_url, "http://127.0.0.1:3000")
        self.assertEqual(config.ao_path, "ao")
        self.assertEqual(config.ao_cwd, "/tmp/test")
        self.assertEqual(config.api_timeout_s, 10)

    @patch.dict(
        os.environ,
        {
            "AO_CWD": "/tmp/test",
            "AO_API_URL": "https://ao.example.com",
            "AO_API_TIMEOUT": "30",
            "AO_PATH": "/usr/local/bin/ao",
        },
        clear=False,
    )
    def test_custom_env(self):
        config = load_config()
        self.assertEqual(config.api_base_url, "https://ao.example.com")
        self.assertEqual(config.api_timeout_s, 30)
        self.assertEqual(config.ao_path, "/usr/local/bin/ao")

    @patch.dict(
        os.environ,
        {
            "AO_CWD": "/tmp/test",
            "AO_API_TIMEOUT": "not-a-number",
        },
        clear=False,
    )
    def test_invalid_int_falls_back(self):
        config = load_config()
        self.assertEqual(config.api_timeout_s, 10)

    @patch.dict(
        os.environ,
        {
            "AO_CWD": "/tmp/test",
            "AO_API_URL": "ftp://invalid",
        },
        clear=False,
    )
    def test_invalid_url_falls_back(self):
        config = load_config()
        self.assertEqual(config.api_base_url, "http://127.0.0.1:3000")


# ══════════════════════════════════════════════════════════════════════
# Circuit Breaker
# ══════════════════════════════════════════════════════════════════════


class TestCircuitBreaker(unittest.TestCase):
    def setUp(self):
        self.config = PluginConfig(ao_cwd="/tmp/test")
        self.client = AOClient(self.config)

    def test_starts_closed(self):
        self.assertEqual(self.client._cb_state, CB_CLOSED)
        self.assertTrue(self.client._cb_can_request())

    def test_success_keeps_closed(self):
        self.client._cb_record_success()
        self.assertEqual(self.client._cb_state, CB_CLOSED)
        self.assertEqual(self.client._cb_failures, 0)

    def test_failures_open_after_threshold(self):
        for _ in range(3):
            self.client._cb_record_failure()
        self.assertEqual(self.client._cb_state, CB_OPEN)

    def test_open_blocks_requests(self):
        for _ in range(3):
            self.client._cb_record_failure()
        self.assertFalse(self.client._cb_can_request())

    def test_half_open_after_backoff(self):
        for _ in range(3):
            self.client._cb_record_failure()
        # Simulate time passing beyond backoff
        self.client._cb_open_until = time.time() - 1
        self.assertTrue(self.client._cb_can_request())
        self.assertEqual(self.client._cb_state, CB_HALF_OPEN)

    def test_success_in_half_open_closes(self):
        self.client._cb_state = CB_HALF_OPEN
        self.client._cb_record_success()
        self.assertEqual(self.client._cb_state, CB_CLOSED)
        self.assertEqual(self.client._cb_failures, 0)

    def test_failure_in_half_open_reopens(self):
        self.client._cb_state = CB_HALF_OPEN
        self.client._cb_record_failure()
        self.assertEqual(self.client._cb_state, CB_OPEN)

    def test_backoff_doubles(self):
        initial = self.client._cb_backoff_s
        for _ in range(3):
            self.client._cb_record_failure()
        self.assertEqual(self.client._cb_backoff_s, initial * 2)


# ══════════════════════════════════════════════════════════════════════
# Client Transport
# ══════════════════════════════════════════════════════════════════════


class TestClientTryApi(unittest.TestCase):
    def setUp(self):
        self.config = PluginConfig(ao_cwd="/tmp/test")
        self.client = AOClient(self.config)

    @patch("hermes_ao.ao_client.urlopen")
    def test_success(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"sessions": []}'
        mock_resp.status = 200
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = self.client._try_api("GET", "/api/sessions")
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"], {"sessions": []})

    @patch("hermes_ao.ao_client.urlopen")
    def test_4xx_doesnt_trip_breaker(self, mock_urlopen):
        from urllib.error import HTTPError

        err = HTTPError("http://test", 404, "Not Found", {}, None)
        mock_urlopen.side_effect = err

        result = self.client._try_api("GET", "/api/sessions/nonexistent")
        self.assertFalse(result["ok"])
        # Circuit should still be closed — 4xx means API is reachable
        self.assertEqual(self.client._cb_state, CB_CLOSED)

    @patch("hermes_ao.ao_client.urlopen")
    def test_5xx_trips_breaker(self, mock_urlopen):
        from urllib.error import HTTPError

        err = HTTPError("http://test", 500, "Server Error", {}, None)
        mock_urlopen.side_effect = err

        for _ in range(3):
            self.client._try_api("GET", "/api/sessions")
        self.assertEqual(self.client._cb_state, CB_OPEN)

    @patch("hermes_ao.ao_client.urlopen")
    def test_connection_error_trips_breaker(self, mock_urlopen):
        from urllib.error import URLError

        mock_urlopen.side_effect = URLError("Connection refused")

        for _ in range(3):
            self.client._try_api("GET", "/api/sessions")
        self.assertEqual(self.client._cb_state, CB_OPEN)

    def test_circuit_open_returns_error(self):
        # Force circuit open
        for _ in range(3):
            self.client._cb_record_failure()

        result = self.client._try_api("GET", "/api/sessions")
        self.assertFalse(result["ok"])
        self.assertIn("circuit breaker", result["error"].lower())


class TestClientTryCli(unittest.TestCase):
    def setUp(self):
        self.config = PluginConfig(ao_cwd="/tmp/test")
        self.client = AOClient(self.config)

    @patch("hermes_ao.ao_client.subprocess.run")
    def test_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="ok\n", stderr="")
        result = self.client._try_cli(["status"])
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"], "ok")

    @patch("hermes_ao.ao_client.subprocess.run")
    def test_failure(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="not found")
        result = self.client._try_cli(["status"])
        self.assertFalse(result["ok"])
        self.assertIn("not found", result["error"])

    @patch("hermes_ao.ao_client.subprocess.run")
    def test_timeout(self, mock_run):
        import subprocess

        mock_run.side_effect = subprocess.TimeoutExpired(cmd="ao", timeout=15)
        result = self.client._try_cli(["status"])
        self.assertFalse(result["ok"])
        self.assertIn("timed out", result["error"])

    @patch("hermes_ao.ao_client.subprocess.run")
    def test_binary_not_found(self, mock_run):
        mock_run.side_effect = FileNotFoundError()
        result = self.client._try_cli(["status"])
        self.assertFalse(result["ok"])
        self.assertIn("not found", result["error"])


# ══════════════════════════════════════════════════════════════════════
# Client Public Methods (with fallback behavior)
# ══════════════════════════════════════════════════════════════════════


class TestClientGetSessions(unittest.TestCase):
    def setUp(self):
        self.config = PluginConfig(ao_cwd="/tmp/test")
        self.client = AOClient(self.config)

    @patch.object(AOClient, "_try_api")
    def test_api_success(self, mock_api):
        mock_api.return_value = {"ok": True, "data": {"sessions": [{"id": "ao-1"}]}}
        result = self.client.get_sessions()
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["sessions"][0]["id"], "ao-1")

    @patch.object(AOClient, "_try_cli")
    @patch.object(AOClient, "_try_api")
    def test_falls_back_to_cli(self, mock_api, mock_cli):
        mock_api.return_value = {"ok": False, "error": "connection failed"}
        mock_cli.return_value = {"ok": True, "data": '{"sessions": []}'}
        result = self.client.get_sessions()
        self.assertTrue(result["ok"])

    @patch.object(AOClient, "_try_cli")
    @patch.object(AOClient, "_try_api")
    def test_both_fail(self, mock_api, mock_cli):
        mock_api.return_value = {"ok": False, "error": "API down"}
        mock_cli.return_value = {"ok": False, "error": "CLI missing"}
        result = self.client.get_sessions()
        self.assertFalse(result["ok"])
        self.assertIn("API", result["error"])
        self.assertIn("CLI", result["error"])


class TestClientCreateIssue(unittest.TestCase):
    """Test that Phase 3 tools now have CLI fallbacks."""

    def setUp(self):
        self.config = PluginConfig(ao_cwd="/tmp/test")
        self.client = AOClient(self.config)

    @patch.object(AOClient, "_try_api")
    def test_api_success(self, mock_api):
        mock_api.return_value = {"ok": True, "data": {"number": 42}}
        result = self.client.create_issue("my-app", "Fix bug", "Details")
        self.assertTrue(result["ok"])

    @patch.object(AOClient, "_try_gh")
    @patch.object(AOClient, "_try_api")
    def test_falls_back_to_gh(self, mock_api, mock_gh):
        mock_api.return_value = {"ok": False, "error": "API down"}
        mock_gh.return_value = {"ok": True, "data": "Created issue #42"}
        result = self.client.create_issue("my-app", "Fix bug")
        self.assertTrue(result["ok"])
        # Verify gh was called with correct args
        call_args = mock_gh.call_args[0][0]
        self.assertIn("issue", call_args)
        self.assertIn("create", call_args)
        self.assertIn("Fix bug", call_args)


class TestClientMergePr(unittest.TestCase):
    def setUp(self):
        self.config = PluginConfig(ao_cwd="/tmp/test")
        self.client = AOClient(self.config)

    @patch.object(AOClient, "_try_gh")
    @patch.object(AOClient, "_try_api")
    def test_falls_back_to_gh(self, mock_api, mock_gh):
        mock_api.return_value = {"ok": False, "error": "API down"}
        mock_gh.return_value = {"ok": True, "data": "Merged"}
        result = self.client.merge_pr(42)
        self.assertTrue(result["ok"])
        call_args = mock_gh.call_args[0][0]
        self.assertIn("pr", call_args)
        self.assertIn("merge", call_args)
        self.assertIn("42", call_args)


class TestClientGetBacklog(unittest.TestCase):
    def setUp(self):
        self.config = PluginConfig(ao_cwd="/tmp/test")
        self.client = AOClient(self.config)

    @patch.object(AOClient, "_try_gh")
    @patch.object(AOClient, "_try_api")
    def test_falls_back_to_gh(self, mock_api, mock_gh):
        mock_api.return_value = {"ok": False, "error": "API down"}
        mock_gh.return_value = {
            "ok": True,
            "data": json.dumps(
                [{"number": 1, "title": "Task", "labels": [], "state": "open", "url": ""}]
            ),
        }
        result = self.client.get_backlog()
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["issues"][0]["id"], "1")


# ══════════════════════════════════════════════════════════════════════
# Tool Handlers
# ══════════════════════════════════════════════════════════════════════


def _mock_client(**overrides):
    """Create a mock AOClient with sensible defaults."""
    client = MagicMock(spec=AOClient)
    client.get_sessions.return_value = {"ok": True, "data": {"sessions": []}}
    client.get_issues.return_value = {"ok": True, "data": {"issues": []}}
    client.spawn.return_value = {"ok": True, "data": {"session": {"id": "ao-1"}}}
    client.send.return_value = {"ok": True, "data": {}}
    client.kill.return_value = {"ok": True, "data": {}}
    client.doctor.return_value = {"ok": True, "data": "All checks passed"}
    client.review_check.return_value = {"ok": True, "data": "No issues"}
    client.verify.return_value = {"ok": True, "data": {"verified": True}}
    client.session_cleanup.return_value = {"ok": True, "data": "Cleaned up 0 sessions"}
    client.session_restore.return_value = {"ok": True, "data": {"id": "ao-1"}}
    client.session_claim_pr.return_value = {"ok": True, "data": "Claimed"}
    client.create_issue.return_value = {"ok": True, "data": {"number": 42}}
    client.get_projects.return_value = {"ok": True, "data": {"projects": {"my-app": {}}}}
    client.get_backlog.return_value = {"ok": True, "data": {"issues": []}}
    client.merge_pr.return_value = {"ok": True, "data": {}}
    client.get_observability.return_value = {"ok": True, "data": {"status": "healthy"}}
    client.get_session_output.return_value = {"ok": True, "data": {"output": "..."}}
    client.spawn_orchestrator.return_value = {"ok": True, "data": {"id": "orch-1"}}
    for k, v in overrides.items():
        setattr(client, k, MagicMock(return_value=v))
    return client


class TestAoSessions(unittest.TestCase):
    def test_success(self):
        client = _mock_client()
        handler = make_ao_sessions(client)
        result = json.loads(handler({}))
        self.assertTrue(result["ok"])

    def test_with_project_filter(self):
        client = _mock_client()
        handler = make_ao_sessions(client)
        handler({"project": "my-app", "active_only": False})
        client.get_sessions.assert_called_with(project="my-app", active_only=False)

    def test_api_error(self):
        client = _mock_client(get_sessions={"ok": False, "error": "down"})
        handler = make_ao_sessions(client)
        result = json.loads(handler({}))
        self.assertFalse(result["ok"])
        self.assertIn("down", result["error"])


class TestAoIssues(unittest.TestCase):
    def test_success(self):
        client = _mock_client()
        handler = make_ao_issues(client)
        result = json.loads(handler({}))
        self.assertTrue(result["ok"])

    def test_with_labels(self):
        client = _mock_client()
        handler = make_ao_issues(client)
        handler({"labels": "bug,P1"})
        client.get_issues.assert_called_with(project=None, label="bug,P1")


class TestAoSpawn(unittest.TestCase):
    def test_single_with_issue(self):
        client = _mock_client()
        handler = make_ao_spawn(client)
        result = json.loads(handler({"project": "my-app", "issue": "#42"}))
        self.assertTrue(result["ok"])
        client.spawn.assert_called_with("my-app", issue_id="42")

    def test_single_without_issue(self):
        client = _mock_client()
        handler = make_ao_spawn(client)
        result = json.loads(handler({"project": "my-app"}))
        self.assertTrue(result["ok"])
        client.spawn.assert_called_with("my-app", issue_id=None)

    def test_batch_mode(self):
        client = _mock_client()
        handler = make_ao_spawn(client)
        result = json.loads(
            handler(
                {
                    "project": "my-app",
                    "mode": "batch",
                    "issues": ["1", "2"],
                }
            )
        )
        self.assertTrue(result["ok"])
        self.assertEqual(client.spawn.call_count, 2)

    def test_auto_resolves_single_project(self):
        client = _mock_client()
        client.get_projects.return_value = {
            "ok": True,
            "data": {"projects": {"only-project": {}}},
        }
        handler = make_ao_spawn(client)
        result = json.loads(handler({"issue": "42"}))
        self.assertTrue(result["ok"])
        client.spawn.assert_called_with("only-project", issue_id="42")

    def test_no_project_multiple_configured(self):
        client = _mock_client()
        client.get_projects.return_value = {
            "ok": True,
            "data": {"projects": {"app-a": {}, "app-b": {}}},
        }
        handler = make_ao_spawn(client)
        result = json.loads(handler({"issue": "42"}))
        self.assertFalse(result["ok"])
        self.assertIn("required", result["error"].lower())

    def test_invalid_issue_id(self):
        client = _mock_client()
        handler = make_ao_spawn(client)
        result = json.loads(handler({"project": "my-app", "issue": "not-a-number"}))
        self.assertFalse(result["ok"])
        self.assertIn("invalid", result["error"].lower())

    def test_orchestrator_mode(self):
        client = _mock_client()
        handler = make_ao_spawn(client)
        result = json.loads(handler({"project": "my-app", "mode": "orchestrator"}))
        self.assertTrue(result["ok"])
        client.spawn_orchestrator.assert_called_with("my-app")

    def test_batch_missing_issues(self):
        client = _mock_client()
        handler = make_ao_spawn(client)
        result = json.loads(handler({"project": "my-app", "mode": "batch"}))
        self.assertFalse(result["ok"])

    def test_spawn_error(self):
        client = _mock_client(spawn={"ok": False, "error": "quota exceeded"})
        handler = make_ao_spawn(client)
        result = json.loads(handler({"project": "my-app", "issue": "42"}))
        self.assertFalse(result["ok"])


class TestAoSend(unittest.TestCase):
    def test_success(self):
        client = _mock_client()
        handler = make_ao_send(client)
        result = json.loads(handler({"session_id": "ao-1", "message": "hello"}))
        self.assertTrue(result["ok"])

    def test_invalid_session(self):
        client = _mock_client()
        handler = make_ao_send(client)
        result = json.loads(handler({"session_id": "../etc", "message": "hello"}))
        self.assertFalse(result["ok"])

    def test_empty_message(self):
        client = _mock_client()
        handler = make_ao_send(client)
        result = json.loads(handler({"session_id": "ao-1", "message": ""}))
        self.assertFalse(result["ok"])

    def test_message_too_long(self):
        client = _mock_client()
        handler = make_ao_send(client)
        result = json.loads(handler({"session_id": "ao-1", "message": "x" * 10001}))
        self.assertFalse(result["ok"])


class TestAoKill(unittest.TestCase):
    def test_success(self):
        client = _mock_client()
        handler = make_ao_kill(client)
        result = json.loads(handler({"session_id": "ao-1"}))
        self.assertTrue(result["ok"])

    def test_invalid_session(self):
        client = _mock_client()
        handler = make_ao_kill(client)
        result = json.loads(handler({"session_id": "DROP TABLE"}))
        self.assertFalse(result["ok"])


class TestAoDoctor(unittest.TestCase):
    def test_success(self):
        client = _mock_client()
        handler = make_ao_doctor(client)
        result = json.loads(handler({}))
        self.assertTrue(result["ok"])


class TestAoReviewCheck(unittest.TestCase):
    def test_success(self):
        client = _mock_client()
        handler = make_ao_review_check(client)
        result = json.loads(handler({}))
        self.assertTrue(result["ok"])

    def test_with_project_and_dry_run(self):
        client = _mock_client()
        handler = make_ao_review_check(client)
        handler({"project": "my-app", "dry_run": True})
        client.review_check.assert_called_with(project="my-app", dry_run=True)


class TestAoVerify(unittest.TestCase):
    def test_verify_issue(self):
        client = _mock_client()
        handler = make_ao_verify(client)
        result = json.loads(handler({"issue": "42"}))
        self.assertTrue(result["ok"])

    def test_list_mode(self):
        client = _mock_client()
        handler = make_ao_verify(client)
        handler({"list": True})
        client.verify.assert_called_with(
            issue=None,
            project=None,
            fail=False,
            comment=None,
            list_mode=True,
        )

    def test_invalid_issue(self):
        client = _mock_client()
        handler = make_ao_verify(client)
        result = json.loads(handler({"issue": "abc"}))
        self.assertFalse(result["ok"])


class TestAoSessionCleanup(unittest.TestCase):
    def test_dry_run(self):
        client = _mock_client()
        handler = make_ao_session_cleanup(client)
        handler({"dry_run": True})
        client.session_cleanup.assert_called_with(project=None, dry_run=True)


class TestAoSessionRestore(unittest.TestCase):
    def test_success(self):
        client = _mock_client()
        handler = make_ao_session_restore(client)
        result = json.loads(handler({"session_id": "ao-1"}))
        self.assertTrue(result["ok"])

    def test_invalid_session(self):
        client = _mock_client()
        handler = make_ao_session_restore(client)
        result = json.loads(handler({"session_id": "../../etc"}))
        self.assertFalse(result["ok"])


class TestAoSessionClaimPr(unittest.TestCase):
    def test_success(self):
        client = _mock_client()
        handler = make_ao_session_claim_pr(client)
        result = json.loads(handler({"pr": "42", "session_id": "ao-1"}))
        self.assertTrue(result["ok"])

    def test_missing_pr(self):
        client = _mock_client()
        handler = make_ao_session_claim_pr(client)
        result = json.loads(handler({"session_id": "ao-1"}))
        self.assertFalse(result["ok"])

    def test_invalid_session(self):
        client = _mock_client()
        handler = make_ao_session_claim_pr(client)
        result = json.loads(handler({"pr": "42", "session_id": "$(whoami)"}))
        self.assertFalse(result["ok"])


class TestAoCreateIssue(unittest.TestCase):
    def test_success(self):
        client = _mock_client()
        handler = make_ao_create_issue(client)
        result = json.loads(handler({"project": "my-app", "title": "Fix bug"}))
        self.assertTrue(result["ok"])

    def test_missing_project(self):
        client = _mock_client()
        handler = make_ao_create_issue(client)
        result = json.loads(handler({"title": "Fix bug"}))
        self.assertFalse(result["ok"])

    def test_missing_title(self):
        client = _mock_client()
        handler = make_ao_create_issue(client)
        result = json.loads(handler({"project": "my-app"}))
        self.assertFalse(result["ok"])


class TestAoListProjects(unittest.TestCase):
    def test_success(self):
        client = _mock_client()
        handler = make_ao_list_projects(client)
        result = json.loads(handler({}))
        self.assertTrue(result["ok"])


class TestAoBacklog(unittest.TestCase):
    def test_success(self):
        client = _mock_client()
        handler = make_ao_backlog(client)
        result = json.loads(handler({}))
        self.assertTrue(result["ok"])


class TestAoMergePr(unittest.TestCase):
    def test_success(self):
        client = _mock_client()
        handler = make_ao_merge_pr(client)
        result = json.loads(handler({"pr_number": 42}))
        self.assertTrue(result["ok"])

    def test_invalid_pr(self):
        client = _mock_client()
        handler = make_ao_merge_pr(client)
        result = json.loads(handler({"pr_number": "not-a-number"}))
        self.assertFalse(result["ok"])

    def test_missing_pr(self):
        client = _mock_client()
        handler = make_ao_merge_pr(client)
        result = json.loads(handler({}))
        self.assertFalse(result["ok"])


class TestAoObservability(unittest.TestCase):
    def test_success(self):
        client = _mock_client()
        handler = make_ao_observability(client)
        result = json.loads(handler({}))
        self.assertTrue(result["ok"])


class TestAoSessionOutput(unittest.TestCase):
    def test_success(self):
        client = _mock_client()
        handler = make_ao_session_output(client)
        result = json.loads(handler({"session_id": "ao-1"}))
        self.assertTrue(result["ok"])

    def test_invalid_session(self):
        client = _mock_client()
        handler = make_ao_session_output(client)
        result = json.loads(handler({"session_id": "../../etc"}))
        self.assertFalse(result["ok"])


# ══════════════════════════════════════════════════════════════════════
# Hooks
# ══════════════════════════════════════════════════════════════════════


class TestHookTriggers(unittest.TestCase):
    """Test WORK_TRIGGERS regex patterns."""

    def test_status_triggers(self):
        for phrase in ["what's happening", "status update", "what's going on"]:
            self.assertTrue(WORK_TRIGGERS.search(phrase), f"Should match: {phrase}")

    def test_spawn_triggers(self):
        for phrase in ["spawn #42", "launch agent", "kick off"]:
            self.assertTrue(WORK_TRIGGERS.search(phrase), f"Should match: {phrase}")

    def test_monitoring_triggers(self):
        for phrase in ["morning standup", "what needs doing", "priorities"]:
            self.assertTrue(WORK_TRIGGERS.search(phrase), f"Should match: {phrase}")

    def test_non_triggers(self):
        # Note: "tell" is intentionally in the regex (for "tell agent X"),
        # so "tell me about quantum physics" does match. Only truly unrelated
        # phrases should be non-triggers.
        for phrase in ["how's the weather", "what time is it", "good night"]:
            self.assertFalse(WORK_TRIGGERS.search(phrase), f"Should NOT match: {phrase}")


class TestPreLlmCallHook(unittest.TestCase):
    def setUp(self):
        self.client = _mock_client()
        self.hook = make_pre_llm_call_hook(self.client)
        # Clear notification queue
        notification_queue.clear()

    def test_no_trigger_passthrough(self):
        msgs = [{"role": "user", "content": "how is the weather today"}]
        result = self.hook(msgs)
        self.assertEqual(result, msgs)

    def test_work_trigger_injects_context(self):
        msgs = [{"role": "user", "content": "what's happening with the agents?"}]
        result = self.hook(msgs)
        self.assertGreater(len(result), len(msgs))
        # System message should be injected before the user message
        system_msg = result[-2]
        self.assertEqual(system_msg["role"], "system")
        self.assertIn("Agent Orchestrator", system_msg["content"])

    def test_tool_call_in_history_triggers(self):
        msgs = [
            {
                "role": "assistant",
                "tool_calls": [
                    {"function": {"name": "ao_sessions"}},
                ],
            },
            {"role": "user", "content": "ok what now"},
        ]
        result = self.hook(msgs)
        self.assertGreater(len(result), len(msgs))

    def test_notification_drain(self):
        notification_queue.append("Session ao-1 completed PR merge")
        msgs = [{"role": "user", "content": "hello"}]
        result = self.hook(msgs)
        has_notification = any("ao-1 completed" in str(m.get("content", "")) for m in result)
        self.assertTrue(has_notification)
        self.assertEqual(len(notification_queue), 0)

    def test_empty_messages_passthrough(self):
        result = self.hook([])
        self.assertEqual(result, [])

    def test_multimodal_content(self):
        msgs = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "what's the status?"},
                ],
            }
        ]
        result = self.hook(msgs)
        self.assertGreater(len(result), len(msgs))

    def test_exception_is_nonfatal(self):
        """Hook should return original messages on internal error."""
        self.client.get_sessions.side_effect = RuntimeError("boom")
        msgs = [{"role": "user", "content": "status"}]
        result = self.hook(msgs)
        # Should not raise — returns messages (possibly with partial injection)
        self.assertIsInstance(result, list)


# ══════════════════════════════════════════════════════════════════════
# Schemas
# ══════════════════════════════════════════════════════════════════════


class TestSchemas(unittest.TestCase):
    def test_all_phases_have_schemas(self):
        all_tools = set(PHASE_1) | set(PHASE_2) | set(PHASE_3)
        expected = {
            "ao_sessions",
            "ao_issues",
            "ao_spawn",
            "ao_send",
            "ao_kill",
            "ao_doctor",
            "ao_review_check",
            "ao_verify",
            "ao_session_cleanup",
            "ao_session_restore",
            "ao_session_claim_pr",
            "ao_create_issue",
            "ao_list_projects",
            "ao_backlog",
            "ao_merge_pr",
            "ao_observability",
            "ao_session_output",
        }
        self.assertEqual(all_tools, expected)

    def test_schemas_have_required_fields(self):
        for phase in [PHASE_1, PHASE_2, PHASE_3]:
            for name, schema in phase.items():
                self.assertIn("name", schema, f"{name} missing 'name'")
                self.assertIn("description", schema, f"{name} missing 'description'")
                self.assertIn("parameters", schema, f"{name} missing 'parameters'")
                self.assertEqual(schema["name"], name)

    def test_schema_name_matches_key(self):
        for phase in [PHASE_1, PHASE_2, PHASE_3]:
            for key, schema in phase.items():
                self.assertEqual(key, schema["name"])


# ══════════════════════════════════════════════════════════════════════
# Register
# ══════════════════════════════════════════════════════════════════════


class TestRegister(unittest.TestCase):
    @patch.dict(os.environ, {"AO_CWD": "/tmp/test"}, clear=False)
    def test_register_all_tools(self):
        """register(ctx) should register 17 tools and 1 hook."""
        import importlib

        import hermes_ao

        importlib.reload(hermes_ao)

        ctx = MagicMock()
        hermes_ao.register(ctx)

        # 17 register_tool calls
        self.assertEqual(ctx.register_tool.call_count, 17)

        # 1 register_hook call
        ctx.register_hook.assert_called_once()
        hook_name = ctx.register_hook.call_args[0][0]
        self.assertEqual(hook_name, "pre_llm_call")

    @patch.dict(os.environ, {"AO_CWD": "/tmp/test"}, clear=False)
    def test_registered_tool_names(self):
        import importlib

        import hermes_ao

        importlib.reload(hermes_ao)

        ctx = MagicMock()
        hermes_ao.register(ctx)

        registered_names = {call.kwargs["name"] for call in ctx.register_tool.call_args_list}
        expected = {
            "ao_sessions",
            "ao_issues",
            "ao_spawn",
            "ao_send",
            "ao_kill",
            "ao_doctor",
            "ao_review_check",
            "ao_verify",
            "ao_session_cleanup",
            "ao_session_restore",
            "ao_session_claim_pr",
            "ao_create_issue",
            "ao_list_projects",
            "ao_backlog",
            "ao_merge_pr",
            "ao_observability",
            "ao_session_output",
        }
        self.assertEqual(registered_names, expected)


if __name__ == "__main__":
    unittest.main()
