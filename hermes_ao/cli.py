"""CLI commands for the AO Hermes plugin.

Registers `hermes ao setup|status|doctor` subcommands.
"""

import os
import shutil
import subprocess
import sys

# Minimum Node.js version required by AO
MIN_NODE_MAJOR = 20

# Where Hermes stores skills
HERMES_SKILLS_DIR = os.path.expanduser("~/.hermes/skills")

# Where Hermes stores env config
HERMES_ENV_FILE = os.path.expanduser("~/.hermes/.env")


def _print(msg: str = "") -> None:
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


def _prompt(label: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    sys.stdout.write(f"  {label}{suffix}: ")
    sys.stdout.flush()
    val = sys.stdin.readline().strip()
    return val or (default or "")


def _run(
    cmd: list[str], check: bool = True, capture: bool = True, timeout: int = 120, **kwargs
) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        check=check,
        capture_output=capture,
        text=True,
        timeout=timeout,
        **kwargs,
    )


def _check_node() -> str | None:
    """Return Node.js version string if >= MIN_NODE_MAJOR, else None."""
    node = shutil.which("node")
    if not node:
        return None
    try:
        result = _run([node, "--version"])
        version = result.stdout.strip().lstrip("v")
        major = int(version.split(".")[0])
        if major >= MIN_NODE_MAJOR:
            return version
    except Exception:
        pass
    return None


def _check_npm() -> bool:
    return shutil.which("npm") is not None


def _check_ao() -> str | None:
    """Return ao CLI version if installed, else None."""
    ao = shutil.which("ao")
    if not ao:
        return None
    try:
        result = _run([ao, "--version"], timeout=10)
        return result.stdout.strip()
    except Exception:
        return None


def _check_ao_server(url: str = "http://127.0.0.1:3000") -> bool:
    """Check if AO server is reachable."""
    try:
        from urllib.request import urlopen

        resp = urlopen(f"{url}/api/health", timeout=5)
        return resp.status == 200
    except Exception:
        return False


def _install_skill() -> bool:
    """Copy the bundled SKILL.md to ~/.hermes/skills/agent-orchestrator/."""
    skill_dir = os.path.join(HERMES_SKILLS_DIR, "agent-orchestrator")
    os.makedirs(skill_dir, exist_ok=True)

    # SKILL.md is at the repo root (sibling of hermes_ao/)
    source = os.path.join(os.path.dirname(os.path.dirname(__file__)), "SKILL.md")
    if not os.path.exists(source):
        # Fallback: try package data
        source = os.path.join(os.path.dirname(__file__), "SKILL.md")
    if not os.path.exists(source):
        return False

    dest = os.path.join(skill_dir, "SKILL.md")
    shutil.copy2(source, dest)
    return True


def _append_env(key: str, value: str) -> None:
    """Append a KEY=value line to ~/.hermes/.env if not already set."""
    env_file = HERMES_ENV_FILE
    os.makedirs(os.path.dirname(env_file), exist_ok=True)

    # Check if already set
    if os.path.exists(env_file):
        with open(env_file) as f:
            for line in f:
                if line.strip().startswith(f"{key}="):
                    return

    with open(env_file, "a") as f:
        f.write(f"{key}={value}\n")


# ── Commands ────────────────────────────────────────────────────────


def cmd_setup(args) -> None:
    """Interactive AO setup wizard."""
    _print()
    _print("  Agent Orchestrator Setup")
    _print("  ========================")
    _print()

    # Step 1: Check Node.js
    _print("  [1/6] Checking Node.js...")
    node_version = _check_node()
    if node_version:
        _print(f"    OK  Node.js v{node_version}")
    else:
        _print(f"    MISSING  Node.js {MIN_NODE_MAJOR}+ is required.")
        _print()
        _print("    Install Node.js:")
        _print("      curl -fsSL https://fnm.vercel.app/install | bash")
        _print(f"      fnm install {MIN_NODE_MAJOR}")
        _print(f"      fnm use {MIN_NODE_MAJOR}")
        _print()
        _print("    Then re-run: hermes ao setup")
        return

    # Step 2: Check npm
    _print("  [2/6] Checking npm...")
    if _check_npm():
        _print("    OK  npm found")
    else:
        _print("    MISSING  npm not found. Install Node.js with npm included.")
        return

    # Step 3: Install AO
    _print("  [3/6] Installing Agent Orchestrator...")
    ao_version = _check_ao()
    if ao_version:
        _print(f"    OK  ao CLI already installed ({ao_version})")
    else:
        _print("    Installing @aoagents/ao globally...")
        try:
            _run(["npm", "install", "-g", "@aoagents/ao"], capture=False, timeout=300)
            ao_version = _check_ao()
            if ao_version:
                _print(f"    OK  ao CLI installed ({ao_version})")
            else:
                _print("    FAILED  ao CLI not found after install.")
                _print("    Try manually: npm install -g @aoagents/ao")
                return
        except subprocess.CalledProcessError:
            _print("    FAILED  npm install failed.")
            _print()
            _print("    If @aoagents/ao is not yet published, install from source:")
            _print("      git clone https://github.com/ComposioHQ/agent-orchestrator")
            _print("      cd agent-orchestrator")
            _print("      npm install -g pnpm && pnpm install && pnpm build")
            _print("      npm link packages/ao")
            _print()
            _print("    Then re-run: hermes ao setup")
            return

    # Step 4: Project config
    _print("  [4/6] Project configuration...")
    cwd = os.environ.get("AO_CWD", "")
    if not cwd or not os.path.isdir(cwd):
        _print()
        _print("    AO needs a project directory (where agent-orchestrator.yaml lives).")
        cwd = _prompt("Project path", os.getcwd())

    cwd = os.path.abspath(os.path.expanduser(cwd))
    config_file = os.path.join(cwd, "agent-orchestrator.yaml")

    if os.path.exists(config_file):
        _print(f"    OK  Config found: {config_file}")
    else:
        _print(f"    No config at {config_file}")
        _print("    Running ao init to create one...")
        try:
            _run(["ao", "init"], capture=False, timeout=120, cwd=cwd)
            if os.path.exists(config_file):
                _print("    OK  Config created")
            else:
                _print("    WARNING  Config not created. You may need to create it manually.")
        except (subprocess.CalledProcessError, FileNotFoundError):
            _print("    WARNING  ao init failed. Create agent-orchestrator.yaml manually.")

    # Step 5: Save env vars
    _print("  [5/6] Saving configuration...")
    _append_env("AO_CWD", cwd)
    _print(f"    OK  AO_CWD={cwd} saved to {HERMES_ENV_FILE}")

    api_url = _prompt("AO server URL", "http://127.0.0.1:3000")
    _append_env("AO_API_URL", api_url)
    _print(f"    OK  AO_API_URL={api_url}")

    public_url = _prompt("Public dashboard URL (leave empty to skip)", "")
    if public_url:
        _append_env("AO_PUBLIC_URL", public_url)
        _print(f"    OK  AO_PUBLIC_URL={public_url}")

    # Step 6: Install skill
    _print("  [6/6] Installing Hermes skill...")
    if _install_skill():
        _print("    OK  Skill installed to ~/.hermes/skills/agent-orchestrator/")
    else:
        _print("    SKIPPED  SKILL.md not found in package. You can install it later.")

    # Done
    _print()
    _print("  Setup complete!")
    _print()
    _print("  Next steps:")
    _print(f"    1. Start AO:     cd {cwd} && ao start")
    _print("    2. Restart Hermes to load the plugin")
    _print('    3. Try:          hermes chat -q "what sessions are running?"')
    _print()


def cmd_status(args) -> None:
    """Show current AO plugin status."""
    _print()
    _print("  Agent Orchestrator Status")
    _print("  =========================")
    _print()

    # Node.js
    node_version = _check_node()
    _print(f"  Node.js:    {'v' + node_version if node_version else 'NOT FOUND'}")

    # ao CLI
    ao_version = _check_ao()
    _print(f"  ao CLI:     {ao_version or 'NOT FOUND'}")

    # AO_CWD
    cwd = os.environ.get("AO_CWD", "")
    config_exists = os.path.exists(os.path.join(cwd, "agent-orchestrator.yaml")) if cwd else False
    _print(f"  AO_CWD:     {cwd or 'NOT SET'}")
    _print(f"  Config:     {'FOUND' if config_exists else 'NOT FOUND'}")

    # Server
    api_url = os.environ.get("AO_API_URL", "http://127.0.0.1:3000")
    server_ok = _check_ao_server(api_url)
    _print(f"  Server:     {api_url} ({'REACHABLE' if server_ok else 'UNREACHABLE'})")

    # Skill
    skill_exists = os.path.exists(os.path.join(HERMES_SKILLS_DIR, "agent-orchestrator", "SKILL.md"))
    _print(f"  Skill:      {'INSTALLED' if skill_exists else 'NOT INSTALLED'}")

    _print()
    if not all([node_version, ao_version, cwd, config_exists]):
        _print("  Run 'hermes ao setup' to complete installation.")
    elif not server_ok:
        _print(f"  Server not reachable. Start it: cd {cwd} && ao start")
    else:
        _print("  Everything looks good.")
    _print()


def cmd_doctor(args) -> None:
    """Run AO health diagnostics via ao doctor."""
    ao = shutil.which("ao")
    if not ao:
        _print("  ao CLI not found. Run 'hermes ao setup' first.")
        return

    cwd = os.environ.get("AO_CWD", os.getcwd())
    try:
        _run([ao, "doctor"], capture=False, timeout=30, cwd=cwd)
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        _print(f"  ao doctor failed: {e}")


# ── Registration ────────────────────────────────────────────────────


def _ao_command(args) -> None:
    """Route ao subcommands."""
    sub = getattr(args, "ao_command", None)
    if sub == "setup":
        cmd_setup(args)
    elif sub == "status":
        cmd_status(args)
    elif sub == "doctor":
        cmd_doctor(args)
    elif sub is None:
        cmd_status(args)
    else:
        _print(f"  Unknown command: {sub}")
        _print("  Available: setup, status, doctor")


def register_cli(subparser) -> None:
    """Build the `hermes ao` argparse subcommand tree."""
    subs = subparser.add_subparsers(dest="ao_command")
    subs.add_parser("setup", help="Install and configure Agent Orchestrator")
    subs.add_parser("status", help="Show AO plugin status and health")
    subs.add_parser("doctor", help="Run AO health diagnostics")
    subparser.set_defaults(func=_ao_command)
