"""Shared utilities for the AO Hermes plugin."""

import re

# Input validation patterns
SESSION_ID_RE = re.compile(r"^[\w-]+$")
ISSUE_ID_RE = re.compile(r"^#?\d+$")

# Input length caps
MAX_TITLE_LEN = 200
MAX_BODY_LEN = 4000
MAX_MESSAGE_LEN = 10000


def validate_session_id(session_id: str) -> str | None:
    """Validate and return session ID, or None if invalid."""
    if not session_id or not SESSION_ID_RE.match(session_id):
        return None
    return session_id


def validate_issue_id(issue_id) -> str | None:
    """Validate and normalize issue ID (strip leading #). Returns None if invalid."""
    if not issue_id:
        return None
    issue_id = str(issue_id)
    clean = issue_id.lstrip("#")
    if not clean.isdigit():
        return None
    return clean


def truncate(text: str, max_len: int) -> str:
    """Truncate text to max_len characters."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def format_session(s: dict) -> str:
    """Format a single session dict as a readable line."""
    sid = s.get("id", "?")
    status = s.get("status", "?")
    activity = s.get("activity", "")
    branch = s.get("branch", "")
    pr = ""
    pr_info = s.get("pr")
    if pr_info:
        pr = f" PR#{pr_info.get('number', '?')}"
        ci = pr_info.get("ciStatus", "")
        if ci:
            pr += f"({ci})"
    return f"  {sid} | {status} | {activity}{' | ' + branch if branch else ''}{pr}"


def format_session_list(sessions: list) -> str:
    """Format a list of session dicts as readable text."""
    if not sessions:
        return "No sessions found."
    lines = [format_session(s) for s in sessions]
    return f"{len(sessions)} session(s):\n" + "\n".join(lines)


def format_issue(issue: dict, index: int = 0) -> str:
    """Format a single issue dict as a readable line."""
    iid = issue.get("id", "?")
    title = issue.get("title", "")
    labels = issue.get("labels", [])
    label_str = f" [{', '.join(labels)}]" if labels else ""
    prefix = f"{index}. " if index > 0 else ""
    return f"{prefix}#{iid} -- {title}{label_str}"


def format_issue_list(issues: list) -> str:
    """Format a list of issue dicts as readable text."""
    if not issues:
        return "No issues found."
    lines = [format_issue(i, idx + 1) for idx, i in enumerate(issues)]
    return "\n".join(lines)
