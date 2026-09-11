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


def _start_proxy_if_needed() -> None:
    """Start the in-process proxy when provider is nvidia.

    Never prompts for a key here — first-run setup already asked; if the
    user skipped it, /proxy or /key can be used later.
    """
    cfg = config.Config()
    if cfg.get("provider") != "nvidia":
        return
    if config.load_proxy_state():
        return
    try:
        proxy.start_server()
    except Exception:
        pass  # agent surfaces connection errors later


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    # Flags
    fast = "--fast" in argv or "-f" in argv
    quiet = "--quiet" in argv or "-q" in argv
    if "--version" in argv or "-v" in argv:
        print(f"claume-code v{__version__}")
        return 0
    if "--help" in argv or "-h" in argv:
        print("usage: claume [--fast|--quiet|--version]")
        return 0

    workspace = Path.cwd()
    ui = UI(quiet=quiet)

    ui.show_banner(__version__, fast=fast)

    _first_run_setup()
    _start_proxy_if_needed()

    # Context line
    state = config.load_proxy_state()
    if state and config.Config().get("provider") == "nvidia":
        print(f"{GREY}  proxy {RESET}{MINT}{state['base_url']}{RESET} {GREY}· model{RESET} {MINT}{config.Config().model}{RESET}")
    else:
        print(f"{GREY}  provider{RESET} {MINT}{config.Config().get('provider')}{RESET} {GREY}· model{RESET} {MINT}{config.Config().model}{RESET}")
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
