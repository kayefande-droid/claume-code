"""claume CLI — interactive REPL entrypoint."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import List, Optional

from . import commands, config, proxy
from .agent import Agent
from .ui import BOLD, DIM, GREEN, GREY, MINT, RESET, UI
from .version import __version__


def _first_run_setup() -> None:
    cfg = config.Config()
    if cfg.get("first_run_done"):
        return
    print(f"{GREY}first run detected — setting up your vault & proxy…{RESET}")
    # Ensure dirs
    config.claume_dir().mkdir(parents=True, exist_ok=True)
    config.skills_dir().mkdir(parents=True, exist_ok=True)
    config.sessions_dir().mkdir(parents=True, exist_ok=True)
    # Ask for NVIDIA key (free tier) — interactive terminals only
    proxy.ensure_keys()
    cfg.set("first_run_done", True)
    cfg.set("last_version", __version__)
    print(f"{GREEN}✔ setup complete — happy building!{RESET}\n")
    if not proxy.collect_keys():
        print(f"{GREY}  no NVIDIA key yet — get one free at https://build.nvidia.com{RESET}")
        print(f"{GREY}  then run /key NVIDIA_API_KEY or /proxy{RESET}\n")


def _ensure_nvidia_key_interactive() -> None:
    """Demand the NVIDIA key whenever we have none — not only on first run."""
    cfg = config.Config()
    if cfg.get("provider") != "nvidia":
        return
    if proxy.collect_keys():
        return
    try:
        if not sys.stdin.isatty():
            return  # piped/non-interactive: never block
    except Exception:
        return
    proxy.prompt_for_nvidia_key()


def _start_proxy_if_needed() -> None:
    """Start the in-process proxy when provider is nvidia.

    Uses a LIVE health probe — a leftover proxy.json from a crashed run
    must not make us print a phantom proxy URL. Piped/non-interactive
    runs never spawn the server (that's what `claume proxy` is for).
    """
    cfg = config.Config()
    if cfg.get("provider") != "nvidia":
        return
    if proxy.is_running():
        return
    config.clear_proxy_state()  # drop stale state from dead runs
    try:
        if not sys.stdin.isatty():
            return
    except Exception:
        return
    try:
        proxy.start_server()
    except Exception:
        pass  # agent surfaces connection errors later


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    # Subcommand: claume proxy [--verbose]  ->  foreground proxy server
    if argv and argv[0] == "proxy":
        return proxy.serve_foreground(verbose="--verbose" in argv)

    # Flags
    fast = "--fast" in argv or "-f" in argv
    quiet = "--quiet" in argv or "-q" in argv
    if "--version" in argv or "-v" in argv:
        print(f"claume-code v{__version__}")
        return 0
    if "--help" in argv or "-h" in argv:
        print("usage: claume [proxy] [--fast|--quiet|--version]")
        print("  claume           start the interactive agent")
        print("  claume proxy     run the free-claume proxy in the foreground")
        return 0

    workspace = Path.cwd()
    ui = UI(quiet=quiet)

    ui.show_banner(__version__, fast=fast)

    _first_run_setup()
    _ensure_nvidia_key_interactive()
    _start_proxy_if_needed()

    # Context line — proxy status is a LIVE probe, never a stale file
    cfg = config.Config()
    if cfg.get("provider") == "nvidia":
        base = f"http://{cfg.get('proxy_host', '127.0.0.1')}:{cfg.get('proxy_port', 8000)}/v1"
        if proxy.is_running():
            print(f"{GREY}  proxy{RESET} {MINT}{base}{RESET} {GREEN}live{RESET} {GREY}· model{RESET} {MINT}{cfg.model}{RESET}")
        else:
            print(f"{GREY}  proxy{RESET} {GREY}not running — open another terminal and run:{RESET} {MINT}claume proxy{RESET}")
        print(f"{GREY}  model{RESET} {MINT}{cfg.model}{RESET}")
    else:
        print(f"{GREY}  provider{RESET} {MINT}{cfg.get('provider')}{RESET} {GREY}· model{RESET} {MINT}{cfg.model}{RESET}")
    print(f"{GREY}  workspace{RESET} {MINT}{workspace}{RESET}")
    print(f"{GREY}  /help for commands · ctrl+c to interrupt · /exit to quit{RESET}\n")

    agent = Agent(workspace=workspace, ui=ui, confirm_fn=ui.confirm)

    # Instruction .md auto-load
    md_note = commands.load_instruction_md(workspace)
    if md_note:
        agent.history.append({"role": "user", "content": md_note + "\n\n(apply these to all future turns)"})
        print(f"{GREY}  loaded project instructions from CLAUUME.md/CLAUDE.md{RESET}\n")

    from . import llm  # late import keeps startup snappy

    while True:
        try:
            line = input(ui.prompt_symbol()).strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n{GREY}bye ✦{RESET}")
            return 0

        if not line:
            continue

        if line.startswith("/"):
            try:
                commands.handle_command(line, agent)
            except SystemExit:
                print(f"{GREY}bye ✦{RESET}")
                return 0
            except Exception as exc:
                ui.render_error(f"command failed: {exc}")
            continue

        # Regular user prompt → agent turn
        with SpinnerIfEnabled(ui):
            agent.compact_if_needed()
            final = agent.run_turn(line)
        if final and final != "(no final answer produced)":
            print(f"\n{GREEN}❯{RESET} {BOLD}{final}{RESET}\n")
        else:
            print()


class SpinnerIfEnabled:
    """Wrap the agent turn in a spinner while waiting (streaming already shows output)."""

    def __init__(self, ui: UI) -> None:
        self.ui = ui

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


if __name__ == "__main__":
    sys.exit(main())
