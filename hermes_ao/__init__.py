"""Agent Orchestrator plugin for Hermes.

Entry point: register(ctx) is called by Hermes plugin loader.
"""

import logging

from .ao_client import AOClient
from .config import load_config
from .hooks import make_pre_llm_call_hook
from .schemas import PHASE_1, PHASE_2, PHASE_3
from .tools import (
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

logger = logging.getLogger("hermes-ao")


def register(ctx):
    """Register AO tools and hooks with Hermes.

    Called by the Hermes plugin loader. `ctx` is a PluginContext with:
      - ctx.register_tool(name, schema, handler)
      - ctx.register_hook(hook_name, handler)
      - ctx.inject_message(text)
    """
    # Setup logging
    logging.basicConfig(level=logging.INFO)
    logger.setLevel(logging.DEBUG)

    logger.info("Agent Orchestrator plugin loading...")

    # Load config
    config = load_config()

    # Create API client
    client = AOClient(config)

    # ── Phase 1: Core tools ─────────────────────────────────────────
    _register_tools(
        ctx,
        PHASE_1,
        {
            "ao_sessions": make_ao_sessions(client),
            "ao_issues": make_ao_issues(client),
            "ao_spawn": make_ao_spawn(client),
            "ao_send": make_ao_send(client),
            "ao_kill": make_ao_kill(client),
        },
    )

    # ── Phase 2: Resilience + full port ─────────────────────────────
    _register_tools(
        ctx,
        PHASE_2,
        {
            "ao_doctor": make_ao_doctor(client),
            "ao_review_check": make_ao_review_check(client),
            "ao_verify": make_ao_verify(client),
            "ao_session_cleanup": make_ao_session_cleanup(client),
            "ao_session_restore": make_ao_session_restore(client),
            "ao_session_claim_pr": make_ao_session_claim_pr(client),
        },
    )

    # ── Phase 3: New capabilities ───────────────────────────────────
    _register_tools(
        ctx,
        PHASE_3,
        {
            "ao_create_issue": make_ao_create_issue(client),
            "ao_list_projects": make_ao_list_projects(client),
            "ao_backlog": make_ao_backlog(client),
            "ao_merge_pr": make_ao_merge_pr(client),
            "ao_observability": make_ao_observability(client),
            "ao_session_output": make_ao_session_output(client),
        },
    )

    # ── Hook: pre_llm_call ──────────────────────────────────────────
    hook = make_pre_llm_call_hook(client)
    ctx.register_hook("pre_llm_call", hook)
    logger.info("Registered pre_llm_call hook")

    # ── CLI: hermes ao setup|status|doctor ────────────────────────────
    try:
        from .cli import _ao_command, register_cli

        ctx.register_cli_command(
            name="ao",
            help="Agent Orchestrator — setup, status, diagnostics",
            setup_fn=register_cli,
            handler_fn=_ao_command,
            description="Install, configure, and manage Agent Orchestrator",
        )
        logger.info("Registered CLI command: hermes ao")
    except Exception as e:
        logger.debug("CLI registration skipped: %s", e)

    logger.info("Agent Orchestrator plugin loaded (17 tools, 1 hook, 1 CLI)")


def _register_tools(ctx, schemas: dict, handlers: dict):
    """Register a batch of tools from schema dict + handler dict."""
    for name, schema in schemas.items():
        handler = handlers.get(name)
        if not handler:
            logger.warning("No handler for tool '%s', skipping", name)
            continue
        ctx.register_tool(
            name=name,
            toolset="agent-orchestrator",
            schema=schema,
            handler=handler,
            description=schema.get("description", ""),
        )
        logger.debug("Registered tool: %s", name)
