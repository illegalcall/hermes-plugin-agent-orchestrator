# hermes-ao

[![CI](https://github.com/illegalcall/hermes-plugin-agent-orchestrator/actions/workflows/ci.yml/badge.svg)](https://github.com/illegalcall/hermes-plugin-agent-orchestrator/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/hermes-ao)](https://pypi.org/project/hermes-ao/)

[Hermes](https://github.com/NousResearch/hermes-agent) plugin for [Agent Orchestrator (AO)](https://github.com/ComposioHQ/agent-orchestrator) — spawn and manage parallel AI coding agents from Discord, Telegram, or any Hermes-supported platform.

**17 tools, 1 context-injection hook, setup CLI, orchestration skill.**

## Install and Setup

```bash
pip install hermes-ao
hermes ao setup
```

The setup wizard checks prerequisites, installs AO, generates config, saves env vars, and installs the orchestration skill. That's it.

### What `hermes ao setup` does

1. Checks Node.js 20+ is installed (tells you how to install if missing)
2. Installs AO via `npm install -g @aoagents/ao`
3. Creates `agent-orchestrator.yaml` via `ao init`
4. Saves `AO_CWD`, `AO_API_URL`, `AO_PUBLIC_URL` to `~/.hermes/.env`
5. Installs the orchestration skill to `~/.hermes/skills/`

After setup, start AO and restart Hermes:

```bash
cd /path/to/your/project && ao start
hermes restart
```

### Manual install (alternative)

If you prefer to configure things yourself:

```bash
pip install hermes-ao
```

Set these environment variables (in your shell profile or `~/.hermes/.env`):

```bash
export AO_CWD=/path/to/your/project          # where agent-orchestrator.yaml lives (required)
export AO_API_URL=http://localhost:3000        # AO server URL (default: http://127.0.0.1:3000)
export AO_PUBLIC_URL=http://your-server:3000   # public dashboard URL for links (optional)
```

Restart Hermes.

### Directory-based install (no pip)

```bash
mkdir -p ~/.hermes/plugins/
cp -r hermes_ao ~/.hermes/plugins/hermes-ao
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `hermes ao setup` | Interactive setup wizard — installs AO, configures env, installs skill |
| `hermes ao status` | Show AO plugin health: Node.js, ao CLI, server, config, skill |
| `hermes ao doctor` | Run AO diagnostics via `ao doctor` |

## Quick start

After setup, try:

```bash
hermes chat -q "What AO sessions are running?"
```

Or in Discord/Telegram, ask your bot: "What agents are running?"

## What it does

| Say this in chat | Bot does this |
|---|---|
| "what's happening?" | Shows live session status |
| "what issues are open?" | Lists GitHub issues |
| "spawn #42" | Starts an agent on issue 42 |
| "spawn them all" | Batch-spawns agents on multiple issues |
| "send ao-5 check the tests" | Messages a running agent |
| "kill ao-5" | Stops a session |
| "doctor" | Runs AO health checks |
| "any PRs need review?" | Checks for review comments |
| "verify #42" | Marks issue verified/failed |
| "clean up dead sessions" | Kills merged/closed sessions |
| "restore ao-5" | Restores a crashed session |
| "create issue: fix login bug" | Creates a GitHub issue |
| "what projects?" | Lists configured projects |
| "backlog" | Shows issues awaiting agents |
| "merge PR #18" | Merges a PR |
| "system health" | Observability dashboard |
| "show output ao-5" | Terminal output from a session |

A `pre_llm_call` hook automatically injects live context (active sessions, open issues) when it detects work-related messages.

## Orchestration Skill

The plugin ships a `SKILL.md` that teaches the LLM multi-step workflows:

- **Spawn workflow** — check for duplicates before spawning, confirm after
- **Backlog processing** — list backlog, batch-spawn, monitor
- **Debug stuck agents** — check output, send messages, kill/restore
- **Review and merge** — find PRs needing review, verify, merge, clean up
- **Daily standup** — combine sessions + reviews + backlog into a status report

The skill is installed automatically by `hermes ao setup`, or manually:

```bash
hermes skills install illegalcall/hermes-plugin-agent-orchestrator
```

## Tools reference

| Tool | Description |
|------|-------------|
| `ao_sessions` | List active agent sessions |
| `ao_issues` | List open issues from the tracker |
| `ao_spawn` | Spawn a new coding agent (single, batch, or orchestrator mode) |
| `ao_send` | Send a message to a running agent session |
| `ao_kill` | Terminate an agent session |
| `ao_doctor` | Run AO health diagnostics |
| `ao_review_check` | Check for PRs needing review |
| `ao_verify` | Verify agent work on an issue |
| `ao_session_cleanup` | Clean up sessions with merged/closed PRs |
| `ao_session_restore` | Restore a stopped session |
| `ao_session_claim_pr` | Link a PR to a session |
| `ao_create_issue` | Create a new issue in the tracker |
| `ao_list_projects` | List configured AO projects |
| `ao_backlog` | Show the issue backlog |
| `ao_merge_pr` | Merge a PR |
| `ao_observability` | Get system metrics and health data |
| `ao_session_output` | Get recent output from a session |

## Configuration reference

All optional except `AO_CWD` (set automatically by `hermes ao setup`):

| Variable | Default | Description |
|----------|---------|-------------|
| `AO_CWD` | (required) | Path to project with `agent-orchestrator.yaml` |
| `AO_API_URL` | `http://127.0.0.1:3000` | AO server URL |
| `AO_PUBLIC_URL` | _(empty)_ | Public URL for dashboard links shown to users |
| `AO_PATH` | `ao` | Path to the `ao` CLI binary |
| `GH_PATH` | `gh` | Path to the `gh` CLI binary |
| `AO_API_TIMEOUT` | `10` | API request timeout (seconds) |
| `AO_SPAWN_TIMEOUT` | `30` | Agent spawn timeout (seconds) |
| `AO_CLI_TIMEOUT` | `15` | CLI command timeout (seconds) |

## Architecture

```
Discord/Slack/CLI --> Hermes --> LLM --> ao_* tools --> AO HTTP API --> coding agents
```

```
hermes_ao/
  __init__.py      register(ctx) entry point — 17 tools + 1 hook + 1 CLI
  cli.py           hermes ao setup|status|doctor commands
  config.py        Env-based config loader with validation
  ao_client.py     REST + CLI transport with 3-state circuit breaker
  tools.py         17 tool handler factories (make_ao_* pattern)
  schemas.py       OpenAI function-call schemas, LLM-optimized descriptions
  hooks.py         pre_llm_call hook — regex trigger + context injection
  utils.py         Input validation + formatting helpers
  plugin.yaml      Plugin metadata for Hermes
  SKILL.md         Bundled orchestration skill
SKILL.md           Hermes skill (installable via skills hub)
```

- **REST API first** — talks to the AO dashboard at port 3000, falls back to CLI (`ao` and `gh`)
- **3-state circuit breaker** — closed -> open -> half_open with exponential backoff
- **Thread-safe** — all shared state protected by locks
- **Input validation** — session IDs, issue IDs, message lengths all validated before use

## Testing

```bash
# Unit tests (offline, no AO instance needed)
cd tests && python -m pytest test_unit.py -v

# Live integration tests (requires running AO dashboard)
cd tests && python test_live.py
```

## Requirements

- Python 3.10+
- [Agent Orchestrator](https://github.com/ComposioHQ/agent-orchestrator) installed (via `hermes ao setup` or manually)
- [Hermes Agent](https://github.com/NousResearch/hermes-agent)

## License

MIT — see [LICENSE](LICENSE).
