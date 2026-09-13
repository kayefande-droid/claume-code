"""claume CLI — interactive REPL entrypoint.

v2.2: always-listening REPL. The prompt stays live while a task runs:

  ❯ build the dashboard        ← starts working immediately
  │ + queue the API refactor   ← typed while running → queued
  │ + /ask what does mcp mean? ← side question, answered without hindering
  │ + /skip                    ← interrupts the running task

A worker thread consumes the task queue; the main thread only reads input.
Stream output is thread-safe (lock) and user lines are echoed with a `│`
prefix so they stay visually separate from agent output.
"""
from __future__ import annotations

import os
import queue
import sys
import threading
import time
from pathlib import Path
from typing import List, Optional

from . import chatbox as _chatbox
from . import commands, config, pinbox, proxy, sessions
from . import frame as _frame
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


def _session_clock() -> "list":
    """Mutable [start_ts] holder for the input-box timer."""
    return [time.time()]


def _fmt_elapsed(start: float) -> str:
    secs = int(time.time() - start)
    if secs < 60:
        return f"{secs}s"
    return f"{secs // 60}m{secs % 60:02d}s"


def _print_frame(workspace: Path, session_label: str = "") -> None:
    """Structural frame: status rule bar + Injected System Skills panel."""
    try:
        _frame.status_bar("worki · claume-code", out=print)
        print()
        _frame.skills_panel(out=print)
        print()
    except Exception:
        pass


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
    print(f"{_ui.GREY}  {uimod.mode_chip(cfg.mode)} {_ui.GREY}· /help commands · type while a task runs (queued) · /ask · /skip · /exit{RESET}\n")


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
        print(f"{_ui.ACCENT}saved sessions{RESET} {_ui.GREY}(project · time){RESET}")
        for n, s in enumerate(entries, 1):
            label = s["name"] or s["title"]
            print(f"  {_ui.MINT}{n:>2}{RESET}. {s['id']}  {_ui.GREY}{s['project']} · {s['when']}{RESET} {label}")
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


class _Shimmer:
    """Background '✻ thinking… Ns' ticker while the model streams."""

    def __init__(self, ui: UI) -> None:
        self.ui = ui
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self.ui.quiet:
            return
        self.ui.thought_stream_start()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        i = 0
        while not self._stop.wait(0.45):
            self.ui.thought_stream_tick(i)
            i += 1

    def stop(self, thought: str = "") -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=0.5)
        self.ui.thought_stream_end(thought)


# ---------------------------------------------------------------------------
# Worker: consumes the task queue so typing stays live during a run
# ---------------------------------------------------------------------------
def _make_worker(agent: Agent, ui: UI, task_queue: "queue.Queue", box_state: dict) -> threading.Thread:
    from . import voice  # late import: optional engines

    def _finish_turn(final: str) -> None:
        uimod = _ui
        _chatbox.close_box()
        if final and final not in ("(no final answer produced)", "(interrupted by user)"):
            print(f"\n{uimod.ACCENT}❯{RESET} {BOLD}{final}{RESET}\n")
            ui.last_final = final
            if config.Config().get("auto_copy", True):
                try:
                    uimod.copy_to_clipboard(final)
                    print(f"{uimod.MUTED}  ⧉ copied to clipboard — /copy to re-copy · /expand for full tool output{RESET}")
                except Exception:
                    pass
            voice.speak(final, block=False)
        elif final == "(interrupted by user)":
            print(f"\n{uimod.GOLD}⚠ task stopped — queue still live, type the next thing{RESET}\n")

    def _print_outside_box(*args, **kwargs) -> None:
        """Worker-side print: wipe the on-screen box first so output lands
        on clean lines, then mark the box dirty (next keystroke redraws
        it below this output)."""
        _chatbox.close_box()
        print(*args, **kwargs)
        box_state["dirty"] = True

    def _run() -> None:
        while True:
            item = task_queue.get()
            try:
                if item is None:
                    return
                text = item
                attachments: list = []
                if isinstance(item, dict):
                    text = item.get("text", "")
                    attachments = item.get("attachments") or []
                # Animated thinking shimmer around the run
                # (rendered via _print_outside_box so it never overprints
                # the open input box)
                shimmer = _Shimmer(ui)
                try:
                    shimmer.start()
                    final = agent.run_turn(text, attachments=attachments or None)
                finally:
                    thought = ""
                    try:
                        thought = next(
                            (m["content"] for m in reversed(agent.history) if m.get("role") == "assistant" and isinstance(m.get("content"), str)),
                            "",
                        )[:70]
                    except Exception:
                        pass
                    shimmer.stop(thought)
                _finish_turn(final)
            except Exception as exc:
                _print_outside_box(f"{_ui.RED}✗ task failed: {exc}{RESET}")
            finally:
                task_queue.task_done()

    t = threading.Thread(target=_run, name="claume-worker", daemon=True)
    return t


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
        ui.mascot.show(mood="idle", note="type a task — keep typing while it works")

    _first_run_setup()
    _ensure_nvidia_key_interactive()
    _start_proxy_if_needed()

    # Bundled skills (ui-ux-pro-max design pack) seed + auto-activate once
    try:
        from . import skills as skillsmod

        seeded = skillsmod.seed_bundled_skills()
        if seeded and not quiet:
            print(f"{_ui.GREY}  skills: {', '.join(seeded)} — design guidance active (/skills){RESET}")
    except Exception:
        pass

    _print_context_line(workspace)
    # Structural frame: elastic status bar + Injected System Skills panel
    # (Freebuff's ad slot becomes claume's live engineering context).
    _print_frame(workspace)

    session_clock = _session_clock()
    agent = Agent(workspace=workspace, ui=ui, confirm_fn=ui.confirm)

    # Sessions: flags first, else fresh autosaved session (named by project)
    _resume_flag_sessions(argv, agent)
    if agent.session_id is None:
        agent.session_id = sessions.start_new()
        if not quiet:
            project = sessions.default_project_name()
            print(f"{_ui.GREY}  session{RESET} {_ui.MINT}{agent.session_id}{RESET} {_ui.GREY}· project '{project}' (autosaved · /rename to name it · /sessions to browse){RESET}")

    # Instruction .md auto-load
    md_note = commands.load_instruction_md(workspace)
    if md_note:
        agent.history.append({"role": "user", "content": md_note + "\n\n(apply these to all future turns)"})
        print(f"{_ui.GREY}  loaded project instructions from CLAUUME.md/CLAUDE.md{RESET}\n")

    from . import voice  # late import: optional engines

    # Task queue + worker: the REPL never blocks on a running task.
    # Items are str tasks or {"text", "attachments"} dicts (image input).
    task_queue: "queue.Queue" = queue.Queue()
    box_state = {"dirty": False}
    worker = _make_worker(agent, ui, task_queue, box_state)
    worker.start()

    use_input_box = bool(config.Config().get("input_box", True)) and not quiet

    # Border labels for the pinned box: mode · project on the left, live
    # session timer on the right. Refreshed each REPL iteration via the
    # mutable dict (cheap reads from the pinbox watcher thread).
    border = {"left": " claume ", "right": ""}

    def _border_labels() -> "tuple":
        return border["left"], border["right"]

    if use_input_box and sys.stdin.isatty():
        pinbox.enter(labels=_border_labels)

    def _echo_typed(line: str) -> None:
        """Echo what the user typed mid-run so the transcript reads correctly.
        (When pinned, the submission was already echoed by pinbox.finalize.)"""
        if not ui.quiet and not pinbox.pinned():
            print(f"{_ui.MUTED}│{RESET} {_ui.SILVER}{line}{RESET}")

    while True:
        busy = agent.is_busy() or not task_queue.empty()
        pinbox.set_busy(busy)

        # --- border labels + prompt -------------------------------
        session_label = ""
        try:
            if agent.session_id:
                data = sessions.load_session(agent.session_id)
                if data:
                    session_label = data.get("project") or ""
        except Exception:
            session_label = ""
        border["left"] = f" {config.Config().mode} · {session_label or 'claume'} "
        border["right"] = f" {_fmt_elapsed(session_clock[0])} "
        prompt = f"{_ui.ACCENT}{_ui.BOLD}❯{_ui.RESET} "
        if not use_input_box:
            prompt = _ui.busy_prompt() if busy else ui.prompt_symbol()

        # --- read input through the Freebuff-style chat box (drops,
        # ghost suggestions, history, Alt+Enter multiline, bracketed
        # paste); plain input() when quiet or non-interactive.
        def _on_shift_tab() -> None:
            _cycle_mode(agent)

        use_chatbox = not quiet and sys.stdin.isatty() and use_input_box
        try:
            if not use_chatbox:
                line = input(prompt).strip()
            elif pinbox.pinned():
                line = pinbox.read_line(
                    prompt, busy=busy,
                    placeholder=_frame.PLACEHOLDER,
                    on_shift_tab=_on_shift_tab,
                ).strip()
            else:
                line = _chatbox.read_line(
                    prompt, on_shift_tab=_on_shift_tab,
                    placeholder=_frame.PLACEHOLDER,
                    busy=busy,
                ).strip()
        except EOFError:
            pinbox.leave()
            print(f"\n{_ui.GREY}bye ✦{RESET}")
            task_queue.put(None)
            agent.request_interrupt()
            worker.join(timeout=5)
            voice.wait_until_done(timeout=3)
            return 0
        except KeyboardInterrupt:
            if busy:
                # first ctrl+c while running = skip the current task
                agent.request_interrupt()
                print(f"\n{_ui.GOLD}⚠ skip requested — stopping current task (queue stays live){RESET}")
                continue
            pinbox.leave()
            print(f"\n{_ui.GREY}press ctrl+c again or /exit to quit · /skip stops a running task{RESET}")
            try:
                if not use_chatbox:
                    line = input(prompt).strip()
                else:
                    line = _chatbox.read_line(prompt, on_shift_tab=_on_shift_tab, busy=busy).strip()
            except (EOFError, KeyboardInterrupt):
                pinbox.leave()
                print(f"\n{_ui.GREY}bye ✦{RESET}")
                task_queue.put(None)
                worker.join(timeout=5)
                voice.wait_until_done(timeout=3)
                return 0

        if not line:
            continue

        if line in ("\\Z", "^[[Z", "\x1b[Z"):
            # Shift+Tab escaped through as a literal control sequence
            _cycle_mode(agent)
            continue

        # --- live routing: commands that make sense mid-run ----------
        low = line.lower()
        if low.startswith("/skip") or low in ("skip", "stop"):
            if agent.is_busy():
                agent.request_interrupt()
                print(f"{_ui.GOLD}⚠ skip requested — stopping current task{RESET}")
            else:
                print(f"{_ui.GREY}nothing running — type a task{RESET}")
            continue
        if low.startswith("/ask ") or low == "/ask":
            q = line[5:].strip()
            if not q:
                print(f"{_ui.RED}usage: /ask <question>{RESET}")
            else:
                commands.cmd_ask([q], agent)
            continue
        if low.startswith("/queue "):
            t = line[7:].strip()
            if t:
                task_queue.put(t)
                _echo_typed(f"queued: {t}")
            continue

        if line.startswith("/"):
            try:
                if agent.is_busy() and low in ("/new",):
                    print(f"{_ui.GOLD}⚠ a task is running — /skip first, then /new{RESET}")
                    continue

                def _enqueue(text: str = "") -> None:
                    task_queue.put(text)
                    _echo_typed(f"queued: {text}")

                commands.handle_command(line, agent, enqueue=_enqueue)
            except SystemExit:
                pinbox.leave()
                print(f"{_ui.GREY}bye ✦{RESET}")
                task_queue.put(None)
                agent.request_interrupt()
                worker.join(timeout=5)
                voice.wait_until_done(timeout=3)
                return 0
            except Exception as exc:
                ui.render_error(f"command failed: {exc}")
            continue

        # /image without prefix handling: it is dispatched inside
        # handle_command; plain text falls through to the queue below.

        # Plain text: if busy → queue it (runs after the current task);
        # else → run now via the queue too. Pending /image attachments
        # ride along with whichever task consumes them.
        payload: dict = {"text": line, "attachments": list(_chatbox.last_attachments)}
        if busy:
            task_queue.put(payload)
            _echo_typed(f"queued: {line}")
            if _chatbox.last_attachments:
                names = ", ".join(a["name"] for a in _chatbox.last_attachments)
                print(f"{_ui.GREY}  (+ image: {names}){RESET}")
            print(f"{_ui.GREY}  (position {task_queue.qsize()} in queue — /skip cancels the current task){RESET}")
        else:
            task_queue.put(payload)
        _chatbox.last_attachments = []


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
