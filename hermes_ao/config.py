"""Configuration loader for the AO Hermes plugin."""

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger("hermes-ao")


def _safe_int(value: str, default: int) -> int:
    """Parse int from string, return default on failure."""
    try:
        return int(value)
    except (ValueError, TypeError):
        logger.warning("Invalid integer value '%s', using default %d", value, default)
        return default


@dataclass
class PluginConfig:
    api_base_url: str = "http://127.0.0.1:3000"
    ao_path: str = "ao"
    ao_cwd: str = ""
    gh_path: str = "gh"
    api_timeout_s: int = 10
    spawn_timeout_s: int = 30
    cli_timeout_s: int = 15
    health_poll_interval_s: int = 30
    board_scan_interval_s: int = 1800


def load_config() -> PluginConfig:
    """Load plugin config from environment variables with validation."""
    config = PluginConfig(
        api_base_url=os.environ.get("AO_API_URL", "http://127.0.0.1:3000"),
        ao_path=os.environ.get("AO_PATH", "ao"),
        ao_cwd=os.environ.get("AO_CWD", os.getcwd()),
        gh_path=os.environ.get("GH_PATH", "gh"),
        api_timeout_s=_safe_int(os.environ.get("AO_API_TIMEOUT", "10"), 10),
        spawn_timeout_s=_safe_int(os.environ.get("AO_SPAWN_TIMEOUT", "30"), 30),
        cli_timeout_s=_safe_int(os.environ.get("AO_CLI_TIMEOUT", "15"), 15),
        health_poll_interval_s=_safe_int(os.environ.get("AO_HEALTH_POLL_INTERVAL", "30"), 30),
        board_scan_interval_s=_safe_int(os.environ.get("AO_BOARD_SCAN_INTERVAL", "1800"), 1800),
    )

    # Validate API URL
    url = config.api_base_url
    if not (url.startswith("http://") or url.startswith("https://")):
        logger.warning("AO_API_URL must start with http:// or https://, got: %s", url)
        config.api_base_url = "http://127.0.0.1:3000"

    # Validate CWD exists
    if not os.path.isdir(config.ao_cwd):
        logger.warning("AO_CWD does not exist: %s", config.ao_cwd)

    # Log resolved config (mask nothing sensitive here — these are paths/URLs)
    logger.info(
        "AO plugin config: api=%s cwd=%s ao=%s gh=%s timeouts=(%ds/%ds/%ds) polls=(%ds/%ds)",
        config.api_base_url,
        config.ao_cwd,
        config.ao_path,
        config.gh_path,
        config.api_timeout_s,
        config.spawn_timeout_s,
        config.cli_timeout_s,
        config.health_poll_interval_s,
        config.board_scan_interval_s,
    )

    return config
