"""claume CLI — interactive REPL entrypoint."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import List, Optional

from . import commands, config, proxy, sessions
from . import ui as _ui
from .agent import Agent
from .ui import BOLD, RESET, UI
from .version import __version__

# Shift+Tab reaches Python input() as a literal backslash-Z on Windows
# (pyreadline3) and as ^[[Z on some terminals — we match both below.


def _first_run_setup() -> None:
    cfg = config.Config()
    if cfg.get("first_run_done"):
        return
    print(f"{_ui.GREY}first run detected — setting up your vault & proxy…{RESET}")
    # Ensure dirs
    config.claume_dir().mkdir(parents=True, exist_ok=True)
    config.skills_dir().mkdir(parents=True, exist_ok=True)
    config.sessions_dir().mkdir(parents=True, exist_ok=True)
    # Ask for NVIDIA key (free tier) — interactive terminals only
    proxy.ensure_keys()
    cfg.set("first_run_done", True)
    cfg.set("last_version", _version())
    print(f"{_ui.ACCENT}✔ setup complete — happy building!{RESET}\n")
    if not proxy.collect_keys():
        print(f"{_ui.GREY}  no NVIDIA key yet — get one free at https://build.nvidia.com{RESET}")
        print(f"{_ui.GREY}  then run /key NVIDIA_API_KEY or /proxy{RESET}\n")


def _version() -> str:
    from .version import __version__

    return __version__


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


def _apply_saved_theme() -> None:
    from . import ui as uimod

    theme = str(config.Config().get("theme", "nvidia-green"))
    if not uimod.set_theme(theme):
        uimod.set_theme("nvidia-green")


def _print_context_line(workspace: Path) -> None:
    cfg = config.Config()
    uimod = _ui

    if cfg.get("provider") == "nvidia":
        base = f"http://{cfg.get('proxy_host', '127.0.0.1')}:{cfg.get('proxy_port', 8000)}/v1"
        if proxy.is_running():
            print(f"{_ui.GREY}  proxy{RESET} {_ui.MINT}{base}{RESET} {_ui.ACCENT}live{RESET} {_ui.GREY}· model{RESET} {_ui.MINT}{cfg.model}{RESET}")
        else:
            print(f"{_ui.GREY}  proxy{RESET} {_ui.GREY}not running — open another terminal and run:{RESET} {_ui.MINT}claume proxy{RESET}")
            print(f"{_ui.GREY}  model{RESET} {_ui.MINT}{cfg.model}{RESET}")
    else:
        print(f"{_ui.GREY}  provider{RESET} {_ui.MINT}{cfg.get('provider')}{RESET} {_ui.GREY}· model{RESET} {_ui.MINT}{cfg.model}{RESET}")
    print(f"{_ui.GREY}  workspace{RESET} {_ui.MINT}{workspace}{RESET}")
    print(f"{_ui.GREY}  {uimod.mode_chip(cfg.mode)} {_ui.GREY}· /help for commands · Shift+Tab mode · ctrl+c interrupt · /exit quit{RESET}\n")


def _resume_flag_sessions(argv: List[str], agent: Agent) -> None:
    """Handle --continue / --resume [id] flags at startup."""
    if "--continue" in argv or "-c" in argv:
        sid = sessions.latest_session_id()
        if sid:
            data = sessions.load_session(sid)
            if data:
                agent.session_id = sid
                agent.history = list(data.get("messages", []))
                print(f"{_ui.ACCENT}✔ continued session {sid}{RESET} {_ui.GREY}({len(agent.history)} messages){RESET}")
                return
        print(f"{_ui.GREY}no previous session — starting fresh{RESET}")
    elif "--resume" in argv:
        i = argv.index("--resume")
        if i + 1 < len(argv) and not argv[i + 1].startswith("-"):
            sid = argv[i + 1]
            data = sessions.load_session(sid)
            if data:
                agent.session_id = sid
                agent.history = list(data.get("messages", []))
                print(f"{_ui.ACCENT}✔ resumed {sid}{RESET}")
                return
        # interactive picker
        entries = sessions.list_sessions(limit=12)
        if not entries:
            print(f"{_ui.GREY}no saved sessions{RESET}")
            return
        print(f"{_ui.ACCENT}saved sessions{RESET}")
        for n, s in enumerate(entries, 1):
            print(f"  {_ui.MINT}{n:>2}{RESET}. {s['id']}  {_ui.GREY}{s['title']}{RESET}")
        try:
            raw = input(f"{_ui.GREY}resume #: {RESET}").strip()
        except (EOFError, KeyboardInterrupt):
            raw = ""
        if raw.isdigit() and 1 <= int(raw) <= len(entries):
            sid = entries[int(raw) - 1]["id"]
            data = sessions.load_session(sid)
            if data:
                agent.session_id = sid
                agent.history = list(data.get("messages", []))
                print(f"{_ui.ACCENT}✔ resumed {sid}{RESET}")


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    # Subcommand: claume proxy [--verbose]  ->  foreground proxy server
    if argv and argv[0] == "proxy":
        return proxy.serve_foreground(verbose="--verbose" in argv)

    # Flags
    fast = "--fast" in argv or "-f" in argv
    quiet = "--quiet" in argv or "-q" in argv
    if "--version" in argv or "-v" in argv:
        print(f"claume-code v{_version()}")
        return 0
    if "--help" in argv or "-h" in argv:
        print("usage: claume [--continue|--resume [id]] [--fast|--quiet] [proxy] [--version]")
        print("  claume              start the interactive agent")
        print("  claume --continue   resume the most recent session")
        print("  claume --resume     pick a session to resume")
        print("  claume proxy        run the free-claume proxy in the foreground")
        return 0

    _apply_saved_theme()

    workspace = Path.cwd()
    ui = UI(quiet=quiet)

    ui.show_banner(_version(), fast=fast)

    # pixel bot greets you
    if not quiet:
        ui.mascot.show(mood="idle", note="type a task, or /help")

    _first_run_setup()
    _ensure_nvidia_key_interactive()
    _start_proxy_if_needed()

    _print_context_line(workspace)

    agent = Agent(workspace=workspace, ui=ui, confirm_fn=ui.confirm)

    # Sessions: flags first, else fresh autosaved session
    _resume_flag_sessions(argv, agent)
    if agent.session_id is None:
        agent.session_id = sessions.start_new()
        if not quiet:
            print(f"{_ui.GREY}  session{RESET} {_ui.MINT}{agent.session_id}{RESET} {_ui.GREY}(autosaved · /resume to revisit){RESET}")

    # Instruction .md auto-load
    md_note = commands.load_instruction_md(workspace)
    if md_note:
        agent.history.append({"role": "user", "content": md_note + "\n\n(apply these to all future turns)"})
        print(f"{_ui.GREY}  loaded project instructions from CLAUUME.md/CLAUDE.md{RESET}\n")

    from . import llm  # late import keeps startup snappy

    while True:
        try:
            line = input(ui.prompt_symbol()).strip()
        except (EOFError, KeyboardInterrupt):
            # First ctrl+c during input: hint instead of quitting (Claude-Code-like)
            print(f"\n{_ui.GREY}press ctrl+c again or /exit to quit · Shift+Tab to change mode{RESET}")
            try:
                line = input(ui.prompt_symbol()).strip()
            except (EOFError, KeyboardInterrupt):
                print(f"\n{_ui.GREY}bye ✦{RESET}")
                return 0

        if not line:
            continue

        if line in ("\\Z", "^[[Z", "\x1b[Z"):
            # Shift+Tab escaped through as a literal control sequence
            _cycle_mode(agent)
            continue

        if line.startswith("/"):
            try:
                commands.handle_command(line, agent)
            except SystemExit:
                print(f"{_ui.GREY}bye ✦{RESET}")
                return 0
            except Exception as exc:
                ui.render_error(f"command failed: {exc}")
            continue

        # Regular user prompt → agent turn
        agent.compact_if_needed()
        final = agent.run_turn(line)
        uimod = _ui  # live theme constants (survive /theme switches)

        if final and final != "(no final answer produced)":
            print(f"\n{uimod.ACCENT}❯{RESET} {BOLD}{final}{RESET}\n")
            ui.last_final = final
            # auto-copy final answers to clipboard
            if config.Config().get("auto_copy", True):
                try:
                    copy_to_clipboard = uimod.copy_to_clipboard
                    copy_to_clipboard(final)
                    print(f"{uimod.MUTED}  ⧉ copied to clipboard — /copy to re-copy · /expand for full tool output{RESET}")
                except Exception:
                    pass
        else:
            print()

        # gentle mascot nudge after long tasks
        if not quiet and final and final != "(no final answer produced)":
            pass  # mascot stays idle; /mascot shows it on demand


def _cycle_mode(agent: Agent) -> None:
    """Shift+Tab: manual → accept → plan → auto → manual (Claude Code order)."""
    from . import ui as uimod

    order = ["manual", "accept", "plan", "auto"]
    try:
        nxt = order[(order.index(agent.mode) + 1) % len(order)]
    except ValueError:
        nxt = "manual"
    agent.set_mode(nxt)
    print(f"\n{uimod.ACCENT}✔ {uimod.mode_chip(nxt)}{RESET}")


if __name__ == "__main__":
    sys.exit(main())
