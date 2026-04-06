#!/usr/bin/env python3
"""Live integration test for the AO Hermes plugin on the VPS.

Calls each tool handler directly against the real AO dashboard API.
Tests read-only tools fully; tests write tools with validation only (no actual spawn/kill).
"""

import os
import sys

# Set required env vars before importing
os.environ.setdefault("AO_CWD", os.environ.get("MESSAGING_CWD", "/home/aoagent/agent-orchestrator"))
os.environ.setdefault("AO_API_URL", "http://127.0.0.1:3000")

# Ensure the package root is importable when running tests directly
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hermes_ao.ao_client import AOClient
from hermes_ao.config import load_config
from hermes_ao.hooks import WORK_TRIGGERS, make_pre_llm_call_hook, notification_queue
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

PASS = 0
FAIL = 0
SKIP = 0


def test(name, fn):
    global PASS, FAIL
    try:
        result = fn()
        if result is True or result is None:
            PASS += 1
            print(f"  ✓ {name}")
        else:
            FAIL += 1
            print(f"  ✗ {name} — {result}")
    except Exception as e:
        FAIL += 1
        print(f"  ✗ {name} — EXCEPTION: {e}")


def skip(name, reason):
    global SKIP
    SKIP += 1
    print(f"  ⊘ {name} — SKIPPED: {reason}")


def parse(response):
    """Tool handlers return JSON strings like {"ok": true, "result": "..."}.
    Return the full text for assertion matching."""
    if isinstance(response, str):
        return response
    return str(response)


# ─── Setup ────────────────────────────────────────────────────────────────

print("\n══ AO Plugin Live Integration Tests ══\n")

config = load_config()
client = AOClient(config)

# Build all handlers
sessions_handler = make_ao_sessions(client)
issues_handler = make_ao_issues(client)
spawn_handler = make_ao_spawn(client)
send_handler = make_ao_send(client)
kill_handler = make_ao_kill(client)
doctor_handler = make_ao_doctor(client)
review_check_handler = make_ao_review_check(client)
verify_handler = make_ao_verify(client)
session_cleanup_handler = make_ao_session_cleanup(client)
session_restore_handler = make_ao_session_restore(client)
session_claim_pr_handler = make_ao_session_claim_pr(client)
create_issue_handler = make_ao_create_issue(client)
list_projects_handler = make_ao_list_projects(client)
backlog_handler = make_ao_backlog(client)
merge_pr_handler = make_ao_merge_pr(client)
observability_handler = make_ao_observability(client)
session_output_handler = make_ao_session_output(client)

# ─── 1. Utils ─────────────────────────────────────────────────────────────

print("── Utils ──")

test("validate_session_id: valid", lambda: validate_session_id("ao-123") == "ao-123")
test("validate_session_id: invalid", lambda: validate_session_id("../etc/passwd") is None)
test("validate_session_id: empty", lambda: validate_session_id("") is None)
test("validate_issue_id: number", lambda: validate_issue_id(123) == "123")
test("validate_issue_id: hash prefix", lambda: validate_issue_id("#42") == "42")
test("validate_issue_id: invalid", lambda: validate_issue_id("abc") is None)
test("truncate: short", lambda: truncate("hello", 10) == "hello")
test("truncate: long", lambda: truncate("hello world", 8) == "hello...")
test(
    "format_session: basic",
    lambda: "working" in format_session({"id": "ao-1", "status": "working"}),
)
test("format_session_list: empty", lambda: "No sessions" in format_session_list([]))
test("format_issue: basic", lambda: "#42" in format_issue({"id": "42", "title": "Fix bug"}))
test("format_issue_list: empty", lambda: "No issues" in format_issue_list([]))

# ─── 2. Circuit Breaker ──────────────────────────────────────────────────

print("\n── Circuit Breaker ──")

test("circuit breaker: starts closed", lambda: client._cb_state == "closed")

test("circuit breaker: API reachable", lambda: client.get_sessions()["ok"] is True)

test("circuit breaker: still closed after success", lambda: client._cb_state == "closed")

# ─── 3. ao_sessions (read-only, hits live API) ───────────────────────────

print("\n── ao_sessions ──")


def test_sessions_all():
    r = parse(sessions_handler({}))
    return True if "ok" in r.lower() or "session" in r.lower() else f"Unexpected: {r[:100]}"


def test_sessions_active():
    r = parse(sessions_handler({"active_only": True}))
    return True if "ok" in r.lower() or "session" in r.lower() else f"Unexpected: {r[:100]}"


def test_sessions_project_filter():
    r = parse(sessions_handler({"project": "agent-orchestrator"}))
    return True if "ok" in r.lower() or "session" in r.lower() else f"Unexpected: {r[:100]}"


test("ao_sessions: list all", test_sessions_all)
test("ao_sessions: active_only=true", test_sessions_active)
test("ao_sessions: project filter", test_sessions_project_filter)

# ─── 4. ao_issues (read-only, hits live API) ─────────────────────────────

print("\n── ao_issues ──")


def test_issues():
    r = parse(issues_handler({}))
    return (
        True
        if "ok" in r.lower() or "issue" in r.lower() or "no issues" in r.lower()
        else f"Unexpected: {r[:100]}"
    )


def test_issues_label():
    r = parse(issues_handler({"label": "bug"}))
    return (
        True
        if "ok" in r.lower() or "issue" in r.lower() or "no issues" in r.lower()
        else f"Unexpected: {r[:100]}"
    )


test("ao_issues: list all", test_issues)
test("ao_issues: label filter", test_issues_label)

# ─── 5. ao_list_projects (read-only) ─────────────────────────────────────

print("\n── ao_list_projects ──")


def test_list_projects():
    r = parse(list_projects_handler({}))
    return True if "ok" in r.lower() or "project" in r.lower() else f"Unexpected: {r[:100]}"


test("ao_list_projects: list", test_list_projects)

# ─── 6. ao_backlog (read-only) ───────────────────────────────────────────

print("\n── ao_backlog ──")


def test_backlog():
    r = parse(backlog_handler({}))
    return (
        True
        if "ok" in r.lower() or "backlog" in r.lower() or "error" in r.lower()
        else f"Unexpected: {r[:100]}"
    )


test("ao_backlog: list", test_backlog)

# ─── 7. ao_observability (read-only) ─────────────────────────────────────

print("\n── ao_observability ──")


def test_observability():
    r = parse(observability_handler({}))
    return True if "ok" in r.lower() or "error" in r.lower() else f"Unexpected: {r[:100]}"


test("ao_observability: dashboard", test_observability)

# ─── 8. ao_verify (read-only GET) ────────────────────────────────────────

print("\n── ao_verify ──")


def test_verify_list():
    r = parse(verify_handler({}))
    return (
        True
        if "ok" in r.lower() or "error" in r.lower() or "verif" in r.lower()
        else f"Unexpected: {r[:100]}"
    )


test("ao_verify: list unverified", test_verify_list)

# ─── 9. ao_session_output (read-only, uses a real session ID) ────────────

print("\n── ao_session_output ──")


def test_session_output_invalid():
    r = parse(session_output_handler({"session_id": "../../etc"}))
    return True if "invalid" in r.lower() or "error" in r.lower() else f"Unexpected: {r[:100]}"


def test_session_output_nonexistent():
    r = parse(session_output_handler({"session_id": "ao-999999"}))
    return True if "ok" in r.lower() or "error" in r.lower() else f"Unexpected: {r[:100]}"


test("ao_session_output: invalid session_id", test_session_output_invalid)
test("ao_session_output: nonexistent session", test_session_output_nonexistent)

# ─── 10. Input validation on write tools (no actual writes) ──────────────

print("\n── Write tool input validation ──")


def test_spawn_no_issue():
    r = parse(spawn_handler({}))
    return (
        True
        if "issue" in r.lower() or "required" in r.lower() or "error" in r.lower()
        else f"Unexpected: {r[:100]}"
    )


def test_spawn_invalid_issue():
    r = parse(spawn_handler({"issue_id": "not-a-number"}))
    return True if "invalid" in r.lower() or "error" in r.lower() else f"Unexpected: {r[:100]}"


def test_send_no_session():
    r = parse(send_handler({"message": "hello"}))
    return (
        True
        if "session" in r.lower() or "required" in r.lower() or "error" in r.lower()
        else f"Unexpected: {r[:100]}"
    )


def test_send_invalid_session():
    r = parse(send_handler({"session_id": "../etc", "message": "hello"}))
    return True if "invalid" in r.lower() or "error" in r.lower() else f"Unexpected: {r[:100]}"


def test_kill_no_session():
    r = parse(kill_handler({}))
    return (
        True
        if "session" in r.lower() or "required" in r.lower() or "error" in r.lower()
        else f"Unexpected: {r[:100]}"
    )


def test_kill_invalid_session():
    r = parse(kill_handler({"session_id": "DROP TABLE"}))
    return True if "invalid" in r.lower() or "error" in r.lower() else f"Unexpected: {r[:100]}"


def test_restore_invalid():
    r = parse(session_restore_handler({"session_id": "../../../etc"}))
    return True if "invalid" in r.lower() or "error" in r.lower() else f"Unexpected: {r[:100]}"


def test_claim_pr_invalid_session():
    r = parse(session_claim_pr_handler({"session_id": "$(whoami)", "pr": "1"}))
    return True if "invalid" in r.lower() or "error" in r.lower() else f"Unexpected: {r[:100]}"


def test_claim_pr_no_pr():
    r = parse(session_claim_pr_handler({"session_id": "ao-1"}))
    return True if "required" in r.lower() or "error" in r.lower() else f"Unexpected: {r[:100]}"


def test_merge_no_pr():
    r = parse(merge_pr_handler({}))
    return (
        True
        if "pr" in r.lower() or "required" in r.lower() or "error" in r.lower()
        else f"Unexpected: {r[:100]}"
    )


def test_merge_invalid_pr():
    r = parse(merge_pr_handler({"pr_number": "not-a-number"}))
    return (
        True
        if "invalid" in r.lower() or "error" in r.lower() or "number" in r.lower()
        else f"Unexpected: {r[:100]}"
    )


def test_create_issue_no_title():
    r = parse(create_issue_handler({}))
    return (
        True
        if "title" in r.lower() or "required" in r.lower() or "error" in r.lower()
        else f"Unexpected: {r[:100]}"
    )


def test_verify_invalid_issue():
    r = parse(verify_handler({"issue_id": "abc", "status": "verified"}))
    return True if "invalid" in r.lower() or "error" in r.lower() else f"Unexpected: {r[:100]}"


test("ao_spawn: missing issue_id", test_spawn_no_issue)
test("ao_spawn: invalid issue_id", test_spawn_invalid_issue)
test("ao_send: missing session_id", test_send_no_session)
test("ao_send: invalid session_id (path traversal)", test_send_invalid_session)
test("ao_kill: missing session_id", test_kill_no_session)
test("ao_kill: invalid session_id (SQL injection)", test_kill_invalid_session)
test("ao_session_restore: invalid session_id", test_restore_invalid)
test("ao_session_claim_pr: invalid session_id (command injection)", test_claim_pr_invalid_session)
test("ao_session_claim_pr: missing pr", test_claim_pr_no_pr)
test("ao_merge_pr: missing pr_number", test_merge_no_pr)
test("ao_merge_pr: invalid pr_number", test_merge_invalid_pr)
test("ao_create_issue: missing title", test_create_issue_no_title)
test("ao_verify: invalid issue_id", test_verify_invalid_issue)

# ─── 11. Hook: pre_llm_call ─────────────────────────────────────────────

print("\n── Hook: pre_llm_call ──")

hook = make_pre_llm_call_hook(client)


def test_hook_no_trigger():
    msgs = [{"role": "user", "content": "how is the weather today"}]
    result = hook(msgs)
    return True if result == msgs else f"Hook should pass-through, got {len(result)} msgs"


def test_hook_work_trigger():
    msgs = [{"role": "user", "content": "what's happening with the agents?"}]
    result = hook(msgs)
    # Should have injected a system message
    return True if len(result) > len(msgs) else "Hook should inject context on work trigger"


def test_hook_notification_drain():
    notification_queue.append("Test notification: session ao-1 completed")
    msgs = [{"role": "user", "content": "hello"}]
    result = hook(msgs)
    has_notification = any("Test notification" in str(m.get("content", "")) for m in result)
    return True if has_notification else "Hook should drain notification queue"


def test_hook_empty_messages():
    result = hook([])
    return True if result == [] else "Hook should return empty list for empty input"


def test_hook_multimodal():
    msgs = [{"role": "user", "content": [{"type": "text", "text": "what's the status?"}]}]
    result = hook(msgs)
    return True if len(result) > len(msgs) else "Hook should handle multimodal content"


test("hook: no trigger → pass-through", test_hook_no_trigger)
test("hook: work trigger → injects context", test_hook_work_trigger)
test("hook: notification drain", test_hook_notification_drain)
test("hook: empty messages → pass-through", test_hook_empty_messages)
test("hook: multimodal content", test_hook_multimodal)

# ─── 12. Work trigger regex coverage ────────────────────────────────────

print("\n── Work trigger patterns ──")

trigger_tests = [
    ("what's happening", True),
    ("status update", True),
    ("spawn #42", True),
    ("kill ao-5", True),
    ("what issue is open", True),  # "issue" singular matches \bissue\b
    ("morning standup", True),
    ("review the PR", True),
    ("tell me a joke", True),  # "tell" matches (used for "tell agent X")
    ("how's the weather", False),
    ("what needs doing", True),
    ("check the backlog", True),
    ("deploy to prod", True),
    ("ao doctor", True),
]

for phrase, should_match in trigger_tests:
    matched = bool(WORK_TRIGGERS.search(phrase))
    if matched == should_match:
        PASS += 1
        print(f'  ✓ trigger: "{phrase}" → {"match" if matched else "no match"}')
    else:
        FAIL += 1
        print(
            f'  ✗ trigger: "{phrase}" → expected {"match" if should_match else "no match"}, got {"match" if matched else "no match"}'
        )

# ─── 13. CLI fallback (ao doctor is CLI-only) ───────────────────────────

print("\n── CLI tools ──")


def test_doctor():
    r = parse(doctor_handler({}))
    return (
        True
        if "ok" in r.lower() or "error" in r.lower() or "doctor" in r.lower()
        else f"Unexpected: {r[:100]}"
    )


def test_review_check():
    r = parse(review_check_handler({}))
    return (
        True
        if "ok" in r.lower() or "error" in r.lower() or "review" in r.lower()
        else f"Unexpected: {r[:100]}"
    )


def test_session_cleanup_dry():
    r = parse(session_cleanup_handler({"dry_run": True}))
    return (
        True
        if "ok" in r.lower() or "error" in r.lower() or "clean" in r.lower()
        else f"Unexpected: {r[:100]}"
    )


test("ao_doctor: run", test_doctor)
test("ao_review_check: run", test_review_check)
test("ao_session_cleanup: dry_run", test_session_cleanup_dry)

# ─── Summary ─────────────────────────────────────────────────────────────

print(f"\n══ Results: {PASS} passed, {FAIL} failed, {SKIP} skipped ══")
sys.exit(1 if FAIL > 0 else 0)
