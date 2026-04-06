"""Hermes hooks for the AO plugin.

Single pre_llm_call hook that:
1. Detects work-related messages and injects live AO context
2. Drains the notification queue (populated by background services)
"""

import collections
import logging
import re

from .ao_client import AOClient
from .utils import format_issue_list, format_session_list

logger = logging.getLogger("hermes-ao")

# Work-trigger phrases — if the user's message matches any, inject AO context
WORK_TRIGGERS = re.compile(
    r"\b("
    r"what.?s happening|what.?s going on|status|progress|update"
    r"|spawn|start|launch|kick off|begin"
    r"|issue|bug|task|ticket|pr|pull request"
    r"|session|agent|worker|running"
    r"|kill|stop|terminate|abort"
    r"|send|message|tell"
    r"|morning|standup|stand-up|check in|checkin"
    r"|what needs|what.?s next|what should|priorities"
    r"|review|verify|merge|deploy|ship"
    r"|doctor|health|diagnostics|broken|down"
    r"|backlog|queue|pending|waiting"
    r"|cleanup|clean up|restore"
    r"|ao |orchestrat"
    r")\b",
    re.IGNORECASE,
)

# AO tool names — if conversation history has these, stay in AO context
AO_TOOL_NAMES = {
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

# Notification queue — thread-safe deque, populated by background services
notification_queue: collections.deque = collections.deque(maxlen=50)


def make_pre_llm_call_hook(client: AOClient):
    """Create the pre_llm_call hook bound to an AOClient."""

    def hook(messages: list, **kwargs) -> list:
        """Inspect messages, optionally inject AO context and notifications."""
        try:
            inject_context = _should_inject(messages)
            has_notifications = len(notification_queue) > 0

            if not inject_context and not has_notifications:
                return messages

            context_parts = []

            # Drain notification queue
            if has_notifications:
                notifications = []
                while notification_queue:
                    try:
                        notifications.append(notification_queue.popleft())
                    except IndexError:
                        break
                if notifications:
                    context_parts.append(
                        "**AO Notifications:**\n" + "\n".join(f"- {n}" for n in notifications)
                    )

            # Inject live context on work triggers
            if inject_context:
                live = _fetch_live_context(client)
                if live:
                    context_parts.append(live)

            if not context_parts:
                return messages

            if not messages:
                return messages

            context_block = "\n\n".join(context_parts)
            injection = {
                "role": "system",
                "content": (
                    f"[Agent Orchestrator — Live Context]\n\n{context_block}\n\n"
                    "Use the ao_* tools to take action. Do not fabricate session IDs or issue numbers."
                ),
            }

            # Insert before the last user message
            return messages[:-1] + [injection] + messages[-1:]

        except Exception:
            logger.exception("pre_llm_call hook error (non-fatal)")
            return messages

    return hook


def _extract_text(content) -> str:
    """Extract text from message content (handles string or multimodal list)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                parts.append(part.get("text", ""))
        return " ".join(parts)
    return ""


def _should_inject(messages: list) -> bool:
    """Determine if AO context should be injected."""
    # Check last user message for work triggers
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            text = _extract_text(content)
            if text and WORK_TRIGGERS.search(text):
                return True
            break

    # Check if conversation has prior AO tool calls
    for msg in messages:
        if msg.get("role") == "assistant":
            tool_calls = msg.get("tool_calls", [])
            for tc in tool_calls:
                fn = tc.get("function", {})
                if fn.get("name") in AO_TOOL_NAMES:
                    return True

    return False


def _fetch_live_context(client: AOClient) -> str | None:
    """Fetch live sessions and issues for context injection."""
    parts = []

    # Get active sessions
    sessions_result = client.get_sessions(active_only=True)
    if sessions_result["ok"]:
        data = sessions_result["data"]
        sessions = data.get("sessions", []) if isinstance(data, dict) else []
        if sessions:
            parts.append("**Active Sessions:**\n" + format_session_list(sessions))
        else:
            parts.append("**Active Sessions:** None")

    # Get open issues (limit context size)
    issues_result = client.get_issues()
    if issues_result["ok"]:
        data = issues_result["data"]
        issues = data.get("issues", []) if isinstance(data, dict) else []
        if issues:
            # Cap at 10 issues to keep context small
            display = issues[:10]
            text = format_issue_list(display)
            if len(issues) > 10:
                text += f"\n... and {len(issues) - 10} more"
            parts.append(f"**Open Issues ({len(issues)}):**\n{text}")

    if not parts:
        return None

    return "\n\n".join(parts)
