"""OpenAI function-format tool schemas for the AO plugin.

Schemas are grouped by phase. Only register schemas for implemented tools.
"""

# ── Phase 1 schemas ──────────────────────────────────────────────────

PHASE_1 = {
    "ao_sessions": {
        "name": "ao_sessions",
        "description": (
            "Get live Agent Orchestrator session data — what agents are running, their status, "
            "branches, PRs, and CI results. Use when the user asks about status, progress, "
            "or what's happening."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "active_only": {
                    "type": "boolean",
                    "description": "Only show active (non-exited) sessions. Default true.",
                },
                "project": {
                    "type": "string",
                    "description": "Filter by project ID. Omit to show all projects.",
                },
            },
            "required": [],
        },
    },
    "ao_issues": {
        "name": "ao_issues",
        "description": (
            "Get live GitHub issue data — open issues, labels, assignees, and priorities. "
            "Use when the user asks about work, tasks, issues, or what needs attention."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "project": {
                    "type": "string",
                    "description": "Project ID to filter. Omit to scan all configured repos.",
                },
                "labels": {
                    "type": "string",
                    "description": "Comma-separated label filter (e.g. 'bug,P1'). Optional.",
                },
            },
            "required": [],
        },
    },
    "ao_spawn": {
        "name": "ao_spawn",
        "description": (
            "Spawn a durable coding agent on a task. Creates an isolated git worktree, starts "
            "the agent, and wires up feedback loops — CI failures and PR reviews automatically "
            "route back to the agent. Supports single issues, batch spawning, and orchestrator mode."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "issue": {
                    "type": "string",
                    "description": "Issue number (e.g. '42' or '#42'). Omit for freeform tasks.",
                },
                "project": {
                    "type": "string",
                    "description": "Project ID. Required if multiple projects are configured.",
                },
                "issues": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Multiple issue numbers for batch spawning. Confirm with user first.",
                },
                "mode": {
                    "type": "string",
                    "enum": ["single", "batch", "orchestrator"],
                    "description": "Spawn mode. 'single' (default) for one agent, 'batch' for multiple issues, 'orchestrator' for autonomous orchestrator.",
                },
            },
            "required": [],
        },
    },
    "ao_send": {
        "name": "ao_send",
        "description": "Send a message to a running Agent Orchestrator session.",
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "The AO session ID (e.g. ao-5)",
                },
                "message": {
                    "type": "string",
                    "description": "Message to send to the agent",
                },
            },
            "required": ["session_id", "message"],
        },
    },
    "ao_kill": {
        "name": "ao_kill",
        "description": (
            "Kill an Agent Orchestrator session. This stops the agent and cleans up the worktree. "
            "Always confirm with the user before calling this."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "The AO session ID to kill",
                },
            },
            "required": ["session_id"],
        },
    },
}

# ── Phase 2 schemas ──────────────────────────────────────────────────

PHASE_2 = {
    "ao_doctor": {
        "name": "ao_doctor",
        "description": "Run Agent Orchestrator health checks and diagnostics. Use when troubleshooting.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    "ao_review_check": {
        "name": "ao_review_check",
        "description": "Check PRs for unresolved review comments and trigger agents to address them.",
        "parameters": {
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "Project ID (checks all if omitted)"},
                "dry_run": {
                    "type": "boolean",
                    "description": "Preview what would be done without acting",
                },
            },
            "required": [],
        },
    },
    "ao_verify": {
        "name": "ao_verify",
        "description": (
            "Mark an issue as verified or failed after checking the fix on staging, "
            "or list all merged-but-unverified issues."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "issue": {"type": "string", "description": "Issue number to verify"},
                "project": {"type": "string", "description": "Project ID"},
                "fail": {"type": "boolean", "description": "Mark as failed instead of passing"},
                "comment": {"type": "string", "description": "Custom comment to add"},
                "list": {"type": "boolean", "description": "List merged-unverified issues instead"},
            },
            "required": [],
        },
    },
    "ao_session_cleanup": {
        "name": "ao_session_cleanup",
        "description": "Kill sessions where the PR is merged or the issue is closed. Use dry_run first.",
        "parameters": {
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "Project ID to filter"},
                "dry_run": {"type": "boolean", "description": "Preview what would be cleaned up"},
            },
            "required": [],
        },
    },
    "ao_session_restore": {
        "name": "ao_session_restore",
        "description": "Restore a terminated or crashed agent session in-place.",
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Session ID to restore"},
            },
            "required": ["session_id"],
        },
    },
    "ao_session_claim_pr": {
        "name": "ao_session_claim_pr",
        "description": "Attach an existing PR to an agent session for tracking.",
        "parameters": {
            "type": "object",
            "properties": {
                "pr": {"type": "string", "description": "Pull request number or URL"},
                "session_id": {"type": "string", "description": "Session name (optional)"},
                "assign_on_github": {"type": "boolean", "description": "Assign the PR on GitHub"},
            },
            "required": ["pr"],
        },
    },
}

# ── Phase 3 schemas ──────────────────────────────────────────────────

PHASE_3 = {
    "ao_create_issue": {
        "name": "ao_create_issue",
        "description": "Create a new GitHub issue. Optionally add to backlog for automatic agent pickup.",
        "parameters": {
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "Project ID"},
                "title": {"type": "string", "description": "Issue title (max 200 chars)"},
                "description": {"type": "string", "description": "Issue description/body"},
                "add_to_backlog": {"type": "boolean", "description": "Add agent:backlog label"},
            },
            "required": ["project", "title"],
        },
    },
    "ao_list_projects": {
        "name": "ao_list_projects",
        "description": "List all configured AO projects with their repos and settings.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    "ao_backlog": {
        "name": "ao_backlog",
        "description": "List backlog issues (labeled agent:backlog) awaiting agent assignment.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    "ao_merge_pr": {
        "name": "ao_merge_pr",
        "description": (
            "Merge a pull request. Validates mergeability first. "
            "Always confirm with the user before calling."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "pr_number": {"type": "integer", "description": "Pull request number"},
            },
            "required": ["pr_number"],
        },
    },
    "ao_observability": {
        "name": "ao_observability",
        "description": "Get system health and observability dashboard — project health, API metrics, status.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    "ao_session_output": {
        "name": "ao_session_output",
        "description": "Fetch recent activity and details from a running session. Use to check what an agent is doing.",
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Session ID to inspect"},
            },
            "required": ["session_id"],
        },
    },
}
