---
name: agent-orchestrator
description: Manage parallel AI coding agents — spawn, monitor, kill, review, and merge from chat
version: 1.0.0
metadata:
  hermes:
    tags: [coding, agents, orchestration, devops, automation]
    category: development
    requires_toolsets: [terminal]
    requires_tools: [ao_sessions, ao_spawn]
    config:
      - key: ao.project_path
        description: "Path to project with agent-orchestrator.yaml"
        default: ""
        prompt: "Where is your AO project?"
---

# Agent Orchestrator

Spawn, monitor, and manage parallel AI coding agents from chat. Each agent works in an isolated git worktree with its own PR.

## When to Use

- User wants to assign coding tasks to AI agents
- User asks about running agents, sessions, or PRs
- User wants to batch-process issues or manage a backlog
- User mentions "spawn", "agent", "session", "orchestrator", or "AO"
- User wants to check on agent progress or review agent work

## Quick Reference

| Task | Tool | Example |
|------|------|---------|
| See what's running | `ao_sessions` | "what agents are running?" |
| List open issues | `ao_issues` | "what issues are open?" |
| Start an agent | `ao_spawn` with issue number | "spawn an agent on #42" |
| Batch spawn | `ao_spawn` with mode=batch | "spawn agents for all backlog issues" |
| Message an agent | `ao_send` | "tell ao-5 to check the tests" |
| Stop an agent | `ao_kill` | "kill ao-5" |
| Check health | `ao_doctor` | "is AO healthy?" |
| Review PRs | `ao_review_check` | "any PRs need review?" |
| Verify work | `ao_verify` | "verify issue #42" |
| Clean up | `ao_session_cleanup` | "clean up finished sessions" |
| Restore crashed | `ao_session_restore` | "restore ao-5" |
| Link PR to session | `ao_session_claim_pr` | "link PR #18 to ao-5" |
| Create issue | `ao_create_issue` | "create issue: fix login bug" |
| List projects | `ao_list_projects` | "what projects are configured?" |
| Show backlog | `ao_backlog` | "show the backlog" |
| Merge a PR | `ao_merge_pr` | "merge PR #18" |
| System metrics | `ao_observability` | "system health" |
| Agent output | `ao_session_output` | "show output from ao-5" |

## Workflows

### Spawn an Agent on an Issue

1. Check `ao_sessions` to see if an agent is already working on the issue
2. If not, use `ao_spawn` with the issue number
3. Confirm the session started by checking `ao_sessions` again

### Handle the Backlog

1. Run `ao_backlog` to see pending issues
2. Use `ao_spawn` with `mode: "batch"` and the issue numbers
3. Monitor with `ao_sessions`

### Debug a Stuck Agent

1. Check `ao_sessions` for the session status
2. Run `ao_session_output` to see what the agent is doing
3. If stuck on a prompt, use `ao_send` to respond
4. If truly stuck, `ao_kill` and `ao_session_restore` to restart
5. If the issue is systemic, run `ao_doctor`

### Review and Merge Agent Work

1. `ao_review_check` to find PRs with review activity
2. `ao_verify` to validate the agent's work on specific issues
3. `ao_merge_pr` to merge approved PRs
4. `ao_session_cleanup` to clean up sessions with merged PRs

### Daily Standup

When asked "what's the status?" or "what's happening?", combine:
1. `ao_sessions` — show active agents and their states
2. `ao_review_check` — highlight PRs needing attention
3. `ao_backlog` — show what's queued up

## Pitfalls

- **Always check sessions before spawning** to avoid duplicate agents on the same issue
- **Don't kill agents that are mid-PR** — check session output first
- **Batch spawn is powerful but noisy** — start with 2-3 agents, not 20
- **The server must be running** — if tools fail, suggest `hermes ao doctor` or `hermes ao status`
- **Session IDs look like `ao-5`** — don't confuse with issue numbers like `#42`

## Verification

After any spawn or kill operation, confirm the result by calling `ao_sessions` to verify the session list reflects the expected state.
