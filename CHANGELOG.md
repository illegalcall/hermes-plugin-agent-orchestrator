# Changelog

## [1.1.0] - 2026-04-09

### Added
- Unit test suite (`test_unit.py`) — 50+ tests, zero dependencies, runs offline
- CI pipeline (`.github/workflows/ci.yml`) — lint + unit tests on every push/PR
- CLI fallbacks for Phase 3 tools: `create_issue`, `get_backlog`, `merge_pr`, `get_session_output`
- Auto-project resolution in `ao_spawn` — single-project setups no longer need explicit project ID
- `LICENSE` file (MIT)
- `pyproject.toml` for Python version declaration and linting config
- `after-install.md` post-install message for Hermes
- `CHANGELOG.md`

### Fixed
- `ao_spawn` schema declared `project` as optional but handler always required it
- `test_live.py` claim_pr test used wrong schema key (`pr_number` instead of `pr`)
- `_cli_env()` had `import os` inside function body instead of module-level

### Removed
- Unused `default_project` parameter from `make_ao_spawn`

## [1.0.0] - 2026-04-06

### Added
- Initial release: 17 tools + 1 pre_llm_call hook
- REST-first transport with CLI fallback
- 3-state circuit breaker (closed → open → half_open) with exponential backoff
- Input validation on all write tools
- Zero external dependencies (Python stdlib only)
- Live integration test suite (`test_live.py`)
