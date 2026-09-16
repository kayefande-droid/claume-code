"""Terminal UI for claume-code — pixel art, animations, colored output.

Zero dependencies: pure ANSI. Designed to feel like Claude Code and
Freebuff: bold banner, dim stream of thought, bright tool results.
v2.1: animated thinking shimmer, Claude-style chat highlighting,
mouse-tracking pixel mascot, Freebuff-style input box, copy mode.
"""
from __future__ import annotations

import os
import re
import sys
import threading
import time
from typing import Any, Dict, List, Optional

# --------------------------------------------------------------------------
# Windows console: force UTF-8 so pixel glyphs (█ ╗ ║ …) don't crash cp1252
# --------------------------------------------------------------------------
def _force_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream.encoding and stream.encoding.lower() not in ("utf-8", "utf8"):
                stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if os.name == "nt":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleOutputCP(65001)
        except Exception:
            pass


_force_utf8()

# --------------------------------------------------------------------------
# Color themes — switch live with /theme <name>
# --------------------------------------------------------------------------
THEMES: Dict[str, Dict[str, str]] = {
    "nvidia-green": {
        "label": "NVIDIA Green (default)",
        "ACCENT": "\033[38;5;46m",   # bright green accent
        "SOFT": "\033[38;5;120m",    # mint for values
        "TEXT": "\033[38;5;250m",    # silver body text
        "MUTED": "\033[38;5;245m",   # dim grey
        "GOLD": "\033[38;5;220m",
        "RED": "\033[38;5;203m",
        "BLUE": "\033[38;5;75m",
        "PURPLE": "\033[38;5;135m",
    },
    "claude-orange": {
        "label": "Claude Orange",
        "ACCENT": "\033[38;5;209m",
        "SOFT": "\033[38;5;216m",
        "TEXT": "\033[38;5;253m",
        "MUTED": "\033[38;5;245m",
        "GOLD": "\033[38;5;220m",
        "RED": "\033[38;5;203m",
        "BLUE": "\033[38;5;75m",
        "PURPLE": "\033[38;5;135m",
    },
    "cyber-blue": {
        "label": "Cyber Blue",
        "ACCENT": "\033[38;5;75m",
        "SOFT": "\033[38;5;117m",
        "TEXT": "\033[38;5;253m",
        "MUTED": "\033[38;5;245m",
        "GOLD": "\033[38;5;220m",
        "RED": "\033[38;5;203m",
        "BLUE": "\033[38;5;117m",
        "PURPLE": "\033[38;5;141m",
    },
    "synthwave": {
        "label": "Synthwave (pink/purple)",
        "ACCENT": "\033[38;5;207m",
        "SOFT": "\033[38;5;141m",
        "TEXT": "\033[38;5;253m",
        "MUTED": "\033[38;5;245m",
        "GOLD": "\033[38;5;220m",
        "RED": "\033[38;5;203m",
        "BLUE": "\033[38;5;99m",
        "PURPLE": "\033[38;5;171m",
    },
    "matrix": {
        "label": "Matrix (deep green)",
        "ACCENT": "\033[38;5;34m",
        "SOFT": "\033[38;5;71m",
        "TEXT": "\033[38;5;249m",
        "MUTED": "\033[38;5;243m",
        "GOLD": "\033[38;5;178m",
        "RED": "\033[38;5;160m",
        "BLUE": "\033[38;5;66m",
        "PURPLE": "\033[38;5;108m",
    },
    "sunset": {
        "label": "Sunset (amber/coral)",
        "ACCENT": "\033[38;5;214m",
        "SOFT": "\033[38;5;215m",
        "TEXT": "\033[38;5;253m",
        "MUTED": "\033[38;5;245m",
        "GOLD": "\033[38;5;222m",
        "RED": "\033[38;5;196m",
        "BLUE": "\033[38;5;117m",
        "PURPLE": "\033[38;5;176m",
    },
    "mono": {
        "label": "Mono (greyscale)",
        "ACCENT": "\033[38;5;255m",
        "SOFT": "\033[38;5;250m",
        "TEXT": "\033[38;5;250m",
        "MUTED": "\033[38;5;244m",
        "RED": "\033[38;5;247m",
        "BLUE": "\033[38;5;246m",
        "PURPLE": "\033[38;5;248m",
        "GOLD": "\033[38;5;252m",
    },
}

_current_theme = "nvidia-green"


def set_theme(name: str) -> bool:
    """Switch the active color theme. Returns True on success."""
    global _current_theme
    if name in THEMES:
        _current_theme = name
        _rebind()
        return True
    return False


def current_theme() -> str:
    return _current_theme


def _rebind() -> None:
    """Rebind module-level color constants to the active theme."""
    t = THEMES[_current_theme]
    g = globals()
    for key in ("ACCENT", "SOFT", "TEXT", "MUTED", "GOLD", "RED", "BLUE", "PURPLE"):
        g[key] = t[key] if COLOR else ""
    # Classic aliases kept so old imports still work.
    g["GREEN"] = g["ACCENT"]
    g["MINT"] = g["SOFT"]
    g["GREY"] = g["MUTED"]
    g["SILVER"] = g["TEXT"]


def _supports_color() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return sys.stdout.isatty() or os.environ.get("WT_SESSION") or os.environ.get("TERM") == "xterm-256color"


COLOR = _supports_color()

RESET = "\033[0m" if COLOR else ""
BOLD = "\033[1m" if COLOR else ""
DIM = "\033[2m" if COLOR else ""
ITALIC = "\033[3m" if COLOR else ""
UNDERLINE = "\033[4m" if COLOR else ""

# Legacy aliases (rebound by set_theme); defaults = nvidia-green theme
ACCENT = ""
SOFT = ""
TEXT = ""
MUTED = ""
GOLD = ""
RED = ""
BLUE = ""
PURPLE = ""
GREEN = ""
MINT = ""
GREY = ""
SILVER = ""
BG_PANEL = "\033[48;5;236m" if COLOR else ""

_rebind()

# --------------------------------------------------------------------------
# Pixel banner (5-row block font) — spells CLAUME
# --------------------------------------------------------------------------
_BANNER = [
    " ██████╗██╗      █████╗ ██╗   ██╗███╗   ███╗███████╗",
    "██╔════╝██║     ██╔══██╗██║   ██║████╗ ████║██╔════╝",
    "██║     ██║     ███████║██║   ██║██╔████╔██║█████╗  ",
    "██║     ██║     ██╔══██║██║   ██║██║╚██╔╝██║██╔══╝  ",
    "╚█████╗ ███████╗██║  ██║╚██████╔╝██║ ╚═╝ ██║███████╗",
    " ╚════╝ ╚══════╝╚═╝  ╚═╝ ╚═════╝ ╚═╝     ╚═╝╚══════╝",
]

_BANNER_WIDTH = max(len(row) for row in _BANNER)


def banner_lines() -> List[str]:
    out = []
    for row in _BANNER:
        out.append(f"{ACCENT}{row}{RESET}")
    return out


def _clear_screen() -> None:
    sys.stdout.write("\033[2J\033[H")


def animate_banner(fast: bool = False) -> None:
    """Reveal the banner line-by-line with a typewriter shimmer."""
    speed = 0.0 if fast or not COLOR or not sys.stdout.isatty() else 0.045
    if speed == 0.0:
        for row in banner_lines():
            print(row)
        return
    _clear_screen()
    for row in banner_lines():
        print(row)
        sys.stdout.flush()
        time.sleep(speed)
    print()


def pixel_tagline(version: str) -> str:
    return (
        f"{MUTED}▌{SOFT} pixel-grade coding agent {MUTED}· v{version} "
        f"· free model pool · skills + plugins + jarvis · {SOFT}a kayefande-droid product{RESET}"
    )


# --------------------------------------------------------------------------
# Pixel bot mascot — eyes follow your mouse cursor
# --------------------------------------------------------------------------
MASCOT_FRAMES = [
    [
        " ╭──────╮ ",
        " │ ●  ● │ ",
        " │  ──  │ ",
        " ╰──────╯ ",
    ],
    [
        " ╭──────╮ ",
        " │ ◚  ◛ │ ",
        " │  ──  │ ",
        " ╰──────╯ ",
    ],
    [
        " ╭──────╮ ",
        " │ ◉  ◉ │ ",
        " │  ╰╯  │ ",
        " ╰──────╯ ",
    ],
    [
        " ╭──────╮ ",
        " │ ░  ░ │ ",
        " │  ‿   │ ",
        " ╰──────╯ ",
    ],
]

MASCOT_MOODS = {
    "idle": "awaiting orders",
    "think": "thinking…",
    "work": "building…",
    "happy": "done!",
    "sad": "hmm, error",
}

# Mouse-watching state (module-level so any Mascot instance shares it)
_MOUSE_ENABLED = True
_MOUSE_THREAD: Optional[Any] = None
_MOUSE_POS: Dict[str, float] = {"x": 0.5, "y": 0.5}


def _start_mouse_thread() -> None:
    """Watch the mouse cursor without blocking typing.

    Windows: polls GetCursorPos via ctypes — needs no stdin, no terminal
    mode changes, and tracks the cursor even outside the terminal window.
    POSIX: best-effort SGR mouse-sequence reader on the tty.
    """
    global _MOUSE_THREAD
    if _MOUSE_THREAD is not None and _MOUSE_THREAD.is_alive():
        return
    import threading

    if os.name == "nt":

        def _win_loop() -> None:
            try:
                import ctypes

                class POINT(ctypes.Structure):
                    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

                pt = POINT()
                user32 = ctypes.windll.user32
                while _MOUSE_ENABLED:
                    if user32.GetCursorPos(ctypes.byref(pt)):
                        sw = user32.GetSystemMetrics(0) or 1
                        sh = user32.GetSystemMetrics(1) or 1
                        _MOUSE_POS["x"] = max(0.0, min(1.0, pt.x / max(1, sw)))
                        _MOUSE_POS["y"] = max(0.0, min(1.0, pt.y / max(1, sh)))
                    time.sleep(0.12)
            except Exception:
                pass

        _MOUSE_THREAD = threading.Thread(target=_win_loop, name="claume-mouse", daemon=True)
        _MOUSE_THREAD.start()
        return

    def _posix_loop() -> None:
        # Best-effort: parse SGR mouse sequences if the terminal sends them.
        try:
            import select
            import termios
            import tty

            fd = sys.stdin.fileno()
            old = termios.tcgetattr(fd)
            tty.setcbreak(fd)
            try:
                while _MOUSE_ENABLED:
                    r, _, _ = select.select([fd], [], [], 0.2)
                    if not r:
                        continue
                    chunk = os.read(fd, 64).decode("utf-8", "replace")
                    for part in chunk.split("\x1b[<"):
                        try:
                            body = part.split("M")[0].split("m")[0]
                            btn, x, y = body.split(";")[:3]
                            cols, rows = os.get_terminal_size()
                            _MOUSE_POS["x"] = float(x) / max(1, cols)
                            _MOUSE_POS["y"] = float(y) / max(1, rows)
                        except Exception:
                            continue
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
        except Exception:
            pass

    _MOUSE_THREAD = threading.Thread(target=_posix_loop, name="claume-mouse", daemon=True)
    _MOUSE_THREAD.start()


def eyes_for_cursor(nx: float) -> str:
    """Pick an eye glyph pair for the cursor's normalized x position."""
    if nx < 0.25:
        return "◐  ○"   # looking left
    if nx < 0.40:
        return "◕  ◓"   # left-center
    if nx < 0.60:
        return "◉  ◉"   # center
    if nx < 0.75:
        return "◓  ◑"   # right-center
    return "○  ◗"       # looking right


class Mascot:
    """Animated pixel bot rendered beside a status line.

    With mouse_tracking=True the bot's eyes follow the real mouse cursor
    (Windows: GetCursorPos polling thread; POSIX: SGR sequences).
    """

    def __init__(self, enabled: bool = True, mouse_tracking: bool = True) -> None:
        self.enabled = enabled and COLOR and sys.stdout.isatty()
        self._frame = 0
        self.mouse_tracking = mouse_tracking and self.enabled
        if self.mouse_tracking:
            _start_mouse_thread()

    def render(self, mood: str = "idle", note: str = "") -> str:
        if not self.enabled:
            return ""
        self._frame = (self._frame + 1) % len(MASCOT_FRAMES)
        art = list(MASCOT_FRAMES[self._frame])
        label = MASCOT_MOODS.get(mood, mood)
        if self.mouse_tracking:
            art[1] = f" │ {eyes_for_cursor(_MOUSE_POS['x'])} │ "
        lines = []
        for i, row in enumerate(art):
            eye = f"{SOFT}{row}{RESET}" if i in (1, 2) else f"{MUTED}{row}{RESET}"
            text = ""
            if i == 1:
                text = f"  {ACCENT}{BOLD}claume{RESET}"
            elif i == 2:
                text = f"  {MUTED}{label}{RESET}"
            elif i == 3 and note:
                text = f"  {GOLD}{note[:44]}{RESET}"
            lines.append(f"{eye}{text}")
        return "\n".join(lines)

    def show(self, mood: str = "idle", note: str = "") -> None:
        block = self.render(mood, note)
        if block:
            print(block)

    def stop(self) -> None:
        global _MOUSE_ENABLED
        _MOUSE_ENABLED = False


# --------------------------------------------------------------------------
# Freebuff-style input box: bordered prompt with mode/session label
# --------------------------------------------------------------------------
def _term_width() -> int:
    try:
        return max(40, min(100, os.get_terminal_size().columns))
    except Exception:
        return 80


def input_box_top(mode: str = "", session_label: str = "") -> None:
    """Print the input box top border with a centered label."""
    w = _term_width()
    label = " claume "
    if mode:
        label = f" {mode} "
    if session_label:
        label += f"· {session_label} "
    inner = w - 2
    padded = label.center(inner, "─")
    print(f"{MUTED}╭{padded[:inner]}╮{RESET}")


def input_box_prompt() -> str:
    """Left border + prompt symbol shown before input()."""
    sys.stdout.write(f"{MUTED}│{RESET} ")
    return f"{ACCENT}{BOLD}❯{RESET} "


def input_box_bottom() -> None:
    """Bottom border printed after each turn completes."""
    w = _term_width()
    print(f"{MUTED}╰{'─' * w}╯{RESET}")


# --------------------------------------------------------------------------
# Click mode: real mouse clicks on '+N more lines' hints + drag-pull copy
# --------------------------------------------------------------------------
def copy_mode(ui: Optional[Any] = None) -> None:
    """Interactive mouse mode (Windows console events):\n
    * **Click a `… +N more lines` hint** → that tool's full output expands
      inline (via the on_expand callback, typically /expand rerun).
    * **Drag-select text** → lands in the clipboard (pull-copy), announced
      with a preview.
    * **Esc / ctrl+c / Enter** → exits; console mode is always restored.

    ``ui`` (optional): the UI instance carrying the expand registry
    (ui.expandable, ui.hint_rows, ui.render_action_full). Without it the
    mode is pure drag-copy, exactly like the original behavior.
    """
    from .ui import ACCENT, GOLD, MUTED, RESET

    if os.name != "nt":
        print(f"{ACCENT}⧉ copy mode{RESET} {MUTED}— use your terminal's native selection · Enter exits{RESET}")
        try:
            input()
        except (EOFError, KeyboardInterrupt):
            pass
        print(f"{MUTED}copy mode off{RESET}")
        return

    # Live registry references — a background task may append entries while
    # this mode is open, so never work from a stale snapshot.
    expandable_ref = getattr(ui, "expandable", None) if ui else None
    n_expandable = len(expandable_ref) if expandable_ref else 0
    if n_expandable:
        print(f"{ACCENT}⧉ click mode{RESET} {MUTED}— click a ‘+N more lines’ hint to expand it · drag to copy · Esc exits{RESET}")
        print(f"{MUTED}  ({n_expandable} expandable output(s) on screen){RESET}")
    else:
        print(f"{ACCENT}⧉ copy mode{RESET} {MUTED}— drag to select text to copy · Esc exits{RESET}")

    old_mode = _set_mouse_mode(True)
    if old_mode is None:
        print(f"{GOLD}⚠ console mouse events unavailable — drag-copy still works via your terminal{RESET}")
    user32 = None
    try:
        import ctypes

        user32 = ctypes.windll.user32
    except Exception:
        pass

    def _do_expand(idx: int) -> None:
        if ui is None:
            return
        info = ui.expandable[idx - 1] if 0 < idx <= len(ui.expandable) else None
        if info:
            print(f"{ACCENT}⧉ {info['tool']}{RESET} {MUTED}· full output (+{info['hidden']} lines):{RESET}")
        try:
            ui.render_action_full(idx)
        except Exception as exc:
            print(f"{GOLD}⚠ expand failed: {exc}{RESET}")

    last_clip = _read_clipboard_text()
    drag_anchor = None  # screen pos where the left button went down

    try:
        while True:
            ev = _read_console_event(timeout=0.05)
            if ev is None:
                # Fallback: respect the native Enter-to-exit even if the
                # console record stream is unavailable.
                if user32 is not None and user32.GetAsyncKeyState(0x0D) & 1:
                    break
                continue

            kind = ev[0]

            if kind == "key":
                _, vk, down = ev
                # ESC (0x1B) or Enter (0x0D) on key-down exits.
                if down and vk in (0x1B, 0x0D):
                    break
                continue

            _, x, y, left_down, flags = ev

            if flags == 0 and left_down:  # fresh press (no move/double-click flag)
                # 1) hint hit-test: click's buffer row matches a hint row?
                #    (live rows — a background task may have shifted them)
                hint_idx = _hit_test_hint(getattr(ui, "hint_rows", {}) or {}, y) if ui else None
                if hint_idx is not None and expandable_ref and 0 < hint_idx <= len(expandable_ref):
                    info = expandable_ref[hint_idx - 1]
                    print(f"{ACCENT}⧉ expanding {info['tool']}{RESET} {MUTED}(+{info['hidden']} lines){RESET}")
                    _do_expand(hint_idx)
                    drag_anchor = None
                else:
                    drag_anchor = (x, y)
            elif flags == 0 and not left_down and drag_anchor is not None:
                # release after a real drag → pull the selection text
                dragged = abs(x - drag_anchor[0]) + abs(y - drag_anchor[1])
                drag_anchor = None
                if dragged > 6:
                    time.sleep(0.15)  # let the terminal land its selection
                    sel = _read_clipboard_text()
                    if sel and sel != last_clip:
                        last_clip = sel
                        preview = " ".join(sel.split())[:60]
                        print(f"{ACCENT}  ⧉ pulled {len(sel)} chars:{RESET} {preview}…")
                    else:
                        print(
                            f"{MUTED}  selection captured — if your terminal didn't copy it, "
                            f"press ctrl+shift+c (or right-click) and it lands in the clipboard{RESET}"
                        )
            # mouse-move events (flags == 1) are ignored
    except KeyboardInterrupt:
        pass
    finally:
        if old_mode is not None:
            _set_mouse_mode(False, old_mode)
    print(f"{MUTED}copy mode off{RESET}")


# Alias so both names read well at the call site.
click_mode = copy_mode


def _hit_test_hint(hint_rows: Dict[int, int], row: int) -> Optional[int]:
    """Map a click's buffer row to a 1-based hint index (or None).

    ``hint_rows`` maps buffer ROW → hint index; distance is measured from
    the keys (rows). ±1 row slack absorbs soft-wrapped hint lines.
    """
    if not hint_rows:
        return None
    best, best_dist = None, 2
    for hint_row, idx in hint_rows.items():
        d = abs(int(hint_row) - int(row))
        if d < best_dist:
            best, best_dist = idx, d
    return best


def _cursor_pos() -> Optional[tuple]:
    try:
        import ctypes

        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        pt = POINT()
        if ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)):
            return (pt.x, pt.y)
    except Exception:
        pass
    return None


def _read_clipboard_text() -> str:
    """Best-effort clipboard READ (Windows)."""
    if os.name != "nt":
        return ""
    user32 = None
    try:
        import ctypes

        CF_UNICODETEXT = 13
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        if not user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
            return ""
        if not user32.OpenClipboard(0):
            return ""
        try:
            handle = user32.GetClipboardData(CF_UNICODETEXT)
            if not handle:
                return ""
            ptr = kernel32.GlobalLock(handle)
            if not ptr:
                return ""
            data = ctypes.c_wchar_p(ptr).value or ""
            kernel32.GlobalUnlock(handle)
            return data
        finally:
            user32.CloseClipboard()
    except Exception:
        return ""


# --------------------------------------------------------------------------
# Small pieces
# --------------------------------------------------------------------------
def box(title: str, body_lines: List[str], color: str = "", width: int = 64) -> None:
    color = color or ACCENT
    print(f"{color}┌─{title.center(width - 4, '─')}─┐{RESET}")
    for line in body_lines:
        print(f"{color}│{RESET} {line.ljust(width - 4)} {color}│{RESET}")
    print(f"{color}└─{'─' * (width - 2)}┘{RESET}")


class Spinner:
    """Tiny spinner thread — pixel dots marching."""

    FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, label: str = "thinking") -> None:
        self.label = label
        self._running = False
        self._thread: Optional[Any] = None

    def __enter__(self) -> "Spinner":
        import threading

        if not COLOR or not sys.stdout.isatty():
            return self
        self._running = True
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()
        return self

    def _spin(self) -> None:
        i = 0
        while self._running:
            frame = self.FRAMES[i % len(self.FRAMES)]
            sys.stdout.write(f"\r{PURPLE}{frame}{RESET} {DIM}{self.label}…{RESET}")
            sys.stdout.flush()
            i += 1
            time.sleep(0.08)

    def __exit__(self, *exc: object) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=0.3)
        sys.stdout.write("\r" + " " * (len(self.label) + 8) + "\r")


# --------------------------------------------------------------------------
# Clipboard (auto-copy final answers) — zero-dependency, best effort
# --------------------------------------------------------------------------
def copy_to_clipboard(text: str) -> bool:
    """Try hard to copy text to the clipboard without dependencies.

    Order: Windows ctypes → OSC 52 escape → pbcopy/wl-copy/xclip.
    """
    if not text:
        return False
    # 1) Windows native
    if os.name == "nt":
        try:
            import ctypes

            CF_UNICODETEXT = 13
            GMEM_MOVEABLE = 0x0002
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            user32.OpenClipboard(0)
            user32.EmptyClipboard()
            data = text.encode("utf-16-le") + b"\x00\x00"
            handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
            ptr = kernel32.GlobalLock(handle)
            if not ptr:
                user32.CloseClipboard()
                return False
            ctypes.memmove(ptr, data, len(data))
            kernel32.GlobalUnlock(handle)
            user32.SetClipboardData(CF_UNICODETEXT, handle)
            user32.CloseClipboard()
            return True
        except Exception:
            pass
    # 2) OSC 52 (works over ssh / modern terminals)
    try:
        import base64

        b64 = base64.b64encode(text.encode("utf-8")).decode("ascii")
        sys.stdout.write(f"\033]52;c;{b64}\07")
        sys.stdout.flush()
        return True
    except Exception:
        pass
    # 3) CLI helpers on posix
    for cmd in (("pbcopy",), ("wl-copy",), ("xclip", "-selection", "clipboard")):
        try:
            import subprocess

            subprocess.run(cmd, input=text.encode("utf-8"), check=True, timeout=5)
            return True
        except Exception:
            continue
    return False


# --------------------------------------------------------------------------
# Mode chips (like Claude Code's ⏸ manual / ⏵⏵ accept / ⏸ plan / ⏵⏵ auto)
# --------------------------------------------------------------------------
MODE_CHIPS = {
    "manual": ("⏸", "manual mode on"),
    "accept": ("⏵⏵", "accept edits on"),
    "plan": ("⏸", "plan mode on"),
    "auto": ("⏵⏵", "auto mode on"),
}


def mode_chip(mode: str) -> str:
    icon, label = MODE_CHIPS.get(mode, ("⏸", mode))
    colors = {"manual": MUTED, "accept": SOFT, "plan": PURPLE, "auto": ACCENT}
    color = colors.get(mode, MUTED)
    return f"{color}{icon} {label}{RESET}"


# --------------------------------------------------------------------------
# Animated thinking panel — Claude-style '✻ Thinking…' shimmer
# --------------------------------------------------------------------------
class ThinkingPanel:
    """Renders a shimmering '✻ Thinking… Ns' line while the model streams,
    then collapses to a compact one-line thought summary — the Claude Code
    look. Uses only \\r rewriting, safe with normal input()."""

    FRAMES = ["✻", "✽", "✶", "✳"]

    def __init__(self) -> None:
        self._start: Optional[float] = None
        self._line_len = 0
        self._words = ""

    def begin(self, first_words: str = "") -> None:
        if not COLOR or not sys.stdout.isatty() or self._start is not None:
            return
        self._start = time.time()
        self._words = " ".join(first_words.split())[:70]
        self._line_len = 0

    def tick(self, frame: int) -> None:
        if self._start is None:
            return
        elapsed = int(time.time() - self._start)
        icon = self.FRAMES[frame % len(self.FRAMES)]
        text = f"{PURPLE}{icon} thinking…{RESET} {MUTED}{elapsed}s{RESET}"
        sys.stdout.write("\r" + " " * max(self._line_len, 40) + "\r")
        sys.stdout.write(text)
        sys.stdout.flush()
        self._line_len = len(icon) + len(f" thinking… {elapsed}s") + 12

    def set_words(self, words: str) -> None:
        self._words = " ".join((words or "").split())[:70]

    def end(self) -> None:
        if self._start is None:
            return
        elapsed = int(time.time() - self._start)
        if COLOR and sys.stdout.isatty():
            sys.stdout.write("\r" + " " * max(self._line_len, 40) + "\r")
        try:
            from . import style as _st

            print(
                _st.render_channel(
                    "thought",
                    self._words or "(completed)",
                    note=f"{elapsed}s",
                )
            )
        except Exception:
            if self._words:
                print(f"{PURPLE}✻ thought{RESET} {MUTED}({elapsed}s){RESET} {ITALIC}{self._words}{RESET}")
            else:
                print(f"{PURPLE}✻ thought{RESET} {MUTED}({elapsed}s){RESET}")
        self._start = None


# --------------------------------------------------------------------------
# Render helpers used by the agent
# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
# Live-input: busy prompt + click-to-expand hints
# --------------------------------------------------------------------------
BUSY_PROMPT = "\033[38;5;245m│\033[0m \033[38;5;220m+\033[0m "


def busy_prompt() -> str:
    """Prompt shown while a task runs — you can still type.

    Anything entered is routed by the REPL: /skip /ask <q> /queue <t>
    or plain text queued as the next task.
    """
    return BUSY_PROMPT


def _strip_ansi(line: str) -> str:
    return re.sub(r"\033\[[0-9;]*m", "", line)


def expand_hint(tool: str, hidden: int, expandable_ref: Optional[List[dict]] = None) -> str:
    """Render the '+N more lines' hint as a clickable OSC 8 hyperlink.

    ``expandable_ref`` is accepted for backwards compatibility but is
    intentionally left unmodified: registration is owned by
    ``UI.render_action`` (single source of truth), so the click row and
    the registry entry always refer to the same tool call. Falls back
    gracefully to a plain hint in terminals without color.
    """
    text = f"… +{hidden} more lines — /expand for full output"
    if expandable_ref is None or not COLOR:
        return f"\033[38;5;245m{text}\033[0m"
    url = "claume://expand/hint"
    return (
        f"\033]8;line=hint;{url}\033\\\033[38;5;245m{text}\033[0m\033]8;;\033\\"
    )


# --------------------------------------------------------------------------
# Real mouse clicks on expand hints (Windows console INPUT_RECORD events)
# --------------------------------------------------------------------------
# QuickEdit must be off for conhost to deliver mouse events; restored on exit.
_ENABLE_MOUSE_INPUT = 0x0010
_ENABLE_WINDOW_INPUT = 0x0008
_ENABLE_QUICK_EDIT_MODE = 0x0040
_ENABLE_EXTENDED_FLAGS = 0x0080


def _console_cursor_row() -> Optional[int]:
    """Absolute cursor row in the screen BUFFER (scrollback-aware).

    Buffer coordinates survive scrolling, so a hint's row stays valid even
    after more output pushes it up. None when unavailable (non-Windows).
    """
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class COORD_(ctypes.Structure):
            _fields_ = [("X", ctypes.c_short), ("Y", ctypes.c_short)]

        class SMALL_RECT_(ctypes.Structure):
            _fields_ = [("L", ctypes.c_short), ("T", ctypes.c_short),
                        ("R", ctypes.c_short), ("B", ctypes.c_short)]

        class CSBI(ctypes.Structure):
            _fields_ = [
                ("dwSize", COORD_),
                ("dwCursorPosition", COORD_),
                ("wAttributes", wintypes.WORD),
                ("srWindow", SMALL_RECT_),
                ("dwMaximumWindowSize", COORD_),
            ]

        h = ctypes.windll.kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        info = CSBI()
        if ctypes.windll.kernel32.GetConsoleScreenBufferInfo(h, ctypes.byref(info)):
            return int(info.dwCursorPosition.Y)
    except Exception:
        pass
    return None


def _set_mouse_mode(on: bool, restore: Optional[int] = None) -> Optional[int]:
    """Toggle console mouse input (clicks reach ReadConsoleInput).

    Disables QuickEdit while active (conhost requirement). Call
    ``_set_mouse_mode(True)`` → returns the previous mode; restore it with
    ``_set_mouse_mode(False, old)`` so the user's QuickEdit setting comes
    back exactly as it was.
    """
    if os.name != "nt":
        return None
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        h = kernel32.GetStdHandle(-10)  # STD_INPUT_HANDLE
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(h, ctypes.byref(mode)):
            return None
        old = mode.value
        if on:
            new = (old & ~_ENABLE_QUICK_EDIT_MODE) | _ENABLE_MOUSE_INPUT | _ENABLE_EXTENDED_FLAGS
            kernel32.SetConsoleMode(h, new)
            return old
        if restore is not None:
            kernel32.SetConsoleMode(h, restore)
        return None
    except Exception:
        return None


def _read_console_event(timeout: float = 0.05):
    """Poll ONE console input record without blocking the loop.

    Returns ('mouse', x, y, button_down) · ('key', vk, key_down) · None.
    Non-mouse/key records (focus, menu, window-buffer events) are consumed
    and skipped so the loop never stalls on them.
    """
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes
        import msvcrt

        class COORD_(ctypes.Structure):
            _fields_ = [("X", ctypes.c_short), ("Y", ctypes.c_short)]

        class MOUSE_EVENT_RECORD(ctypes.Structure):
            _fields_ = [
                ("dwMousePosition", COORD_),
                ("dwButtonState", wintypes.DWORD),
                ("dwControlKeyState", wintypes.DWORD),
                ("dwEventFlags", wintypes.DWORD),
            ]

        class KEY_EVENT_RECORD(ctypes.Structure):
            _fields_ = [
                ("bKeyDown", wintypes.BOOL),
                ("wRepeatCount", wintypes.WORD),
                ("wVirtualKeyCode", wintypes.WORD),
                ("wVirtualScanCode", wintypes.WORD),
                ("uChar", wintypes.WCHAR),
                ("dwControlKeyState", wintypes.DWORD),
            ]

        class _Event(ctypes.Union):
            _fields_ = [("MouseEvent", MOUSE_EVENT_RECORD), ("KeyEvent", KEY_EVENT_RECORD)]

        class INPUT_RECORD(ctypes.Structure):
            _anonymous_ = ("Event",)
            _fields_ = [("EventType", wintypes.WORD), ("Event", _Event)]

        kernel32 = ctypes.windll.kernel32
        h = kernel32.GetStdHandle(-10)
        rec = INPUT_RECORD()
        n = wintypes.DWORD()
        if not kernel32.PeekConsoleInputW(h, ctypes.byref(rec), 1, ctypes.byref(n)) or n.value == 0:
            time.sleep(timeout)
            return None
        if not kernel32.ReadConsoleInputW(h, ctypes.byref(rec), 1, ctypes.byref(n)):
            return None
        if rec.EventType == 0x0002:  # MOUSE_EVENT
            me = rec.MouseEvent
            return (
                "mouse",
                int(me.dwMousePosition.X),
                int(me.dwMousePosition.Y),
                bool(me.dwButtonState & 0x1),  # left button
                int(me.dwEventFlags),          # 0 = click, 1 = move
            )
        if rec.EventType == 0x0001:  # KEY_EVENT
            ke = rec.KeyEvent
            return ("key", int(ke.wVirtualKeyCode), bool(ke.bKeyDown))
        return None
    except Exception:
        return None


def handle_click(
    x: int,
    y: int,
    expandable_ref: Optional[List[dict]] = None,
    hint_rows: Optional[Dict[int, int]] = None,
) -> Optional[str]:
    """Route a terminal mouse click. Returns an action string or None.

    Row-based first: the click's screen-buffer row (y) is matched against
    the hint rows recorded by ``UI.render_action`` (±1 row slack). Falls
    back to the legacy column heuristic against the registry length.
    Pure Python — no mouse-mode escape codes, so typing is never affected.
    """
    if hint_rows:
        idx = _hit_test_hint(hint_rows, int(y))
        if idx is not None:
            return "/expand"
    if expandable_ref and 0 < int(x) <= len(expandable_ref):
        return "/expand"
    return None


class UI:
    def __init__(self, quiet: bool = False) -> None:
        self.quiet = quiet
        self._streaming = False
        self._stream_lock = threading.Lock()
        self._box_aware = True  # reflow the open input box around output
        self.expand_output = False  # show full tool output (toggled by /expand)
        self.mascot = Mascot(enabled=not quiet, mouse_tracking=True)
        self.last_final = ""  # remembered for /copy
        self.thinking = ThinkingPanel()
        # Click-to-expand registry: every trimmed tool output is remembered
        # (tool, args, result, is_error) with the screen-buffer row of its
        # '+N more lines' hint so mouse clicks can re-render it in full.
        self.expandable: List[dict] = []
        self.hint_rows: Dict[int, int] = {}  # buffer row -> 1-based hint idx

    # -- click-to-expand -------------------------------------------------
    def render_action_full(self, idx: int) -> None:
        """Re-render tool call #idx with its FULL output (no re-execution)."""
        if not 0 < idx <= len(self.expandable):
            print(f"{RED}✗ no expandable output #{idx}{RESET}")
            return
        entry = self.expandable[idx - 1]
        self.render_action(
            entry["tool"], entry["args"], entry["result"], entry["is_error"], _full=True
        )

    # -- boot ---------------------------------------------------------
    def show_banner(self, version: str, fast: bool = False) -> None:
        animate_banner(fast=fast)
        print(pixel_tagline(version))
        print()

    # -- box-aware writes -------------------------------------------------
    @staticmethod
    def _before_write() -> None:
        """Wipe the on-screen input box so output never overprints it.
        Safe from any thread; no-op when no box is open."""
        if not getattr(UI, "_box_aware", True):
            return
        try:
            from . import chatbox as _cb

            _cb.close_box()
        except Exception:
            pass

    def _box_print(self, *args, **kwargs) -> None:
        """print() that keeps the input box coherent."""
        self._before_write()
        print(*args, **kwargs)

    # -- streaming ----------------------------------------------------
    def stream_token(self, token: str, buffer: List[str]) -> None:
        if self.quiet:
            buffer.append(token)
            return
        with self._stream_lock:
            if not self._streaming:
                self._streaming = True
            buffer.append(token)
            self._before_write()
            sys.stdout.write(token.replace("\n", "\n  "))
            sys.stdout.flush()

    def next_stream_line(self, buffer: List[str]) -> None:
        """Start a new dim stream line (│ prefix) — thread-safe.

        Called by the REPL before echoing a line typed while the model is
        streaming, so worker output and user input stay visually separate.
        """
        if self.quiet:
            return
        with self._stream_lock:
            sys.stdout.write(f"\n{MUTED}│{RESET} ")
            sys.stdout.flush()
            self._streaming = True

    def end_stream(self, buffer: List[str]) -> None:
        if self._streaming:
            sys.stdout.write(RESET + "\n")
            sys.stdout.flush()
            self._streaming = False
        buffer.clear()

    # -- animated thinking ----------------------------------------------
    def thought_stream_start(self) -> None:
        """Begin the '✻ thinking' shimmer (before the model replies)."""
        if self.quiet:
            return
        self._before_write()
        self.thinking.begin()

    def thought_stream_tick(self, frame: int) -> None:
        if self.quiet:
            return
        self._before_write()
        self.thinking.tick(frame)

    def thought_stream_end(self, thought: str = "") -> None:
        if self.quiet:
            return
        self._before_write()
        if thought:
            self.thinking.set_words(thought)
        self.thinking.end()

    # -- agent renders --------------------------------------------------
    def render_thought(self, thought: str) -> None:
        """Claude Code style collapsed thought line."""
        if not thought or self.quiet:
            return
        self._before_write()
        words = " ".join(thought.split())
        try:
            from . import style as _st

            print(_st.render_channel("thought", _st.wrap(words)[0] if words else "", note="reasoning"))
        except Exception:
            head = words[:80] + ("…" if len(words) > 80 else "")
            print(f"{PURPLE}✻ thinking{RESET} {ITALIC}{head}{RESET}")

    def render_action(self, tool: str, args: dict, result: str, is_error: bool, _full: bool = False) -> None:
        if self.quiet:
            return
        self._before_write()
        icon = "✗" if is_error else "✓"
        color = RED if is_error else ACCENT
        summary = str(args.get("path") or args.get("command") or args.get("url") or args.get("query") or "")
        summary = " ".join(str(summary).split())[:70]
        self._box_print(f"{color}{icon} {BOLD}{tool}{RESET} {MUTED}{summary}{RESET}")
        if result and not self.quiet:
            lines = result.splitlines()
            shown = lines if (_full or self.expand_output) else lines[:14]
            for line in shown:
                self._box_print(f"  {MUTED}│{RESET} {SILVER}{line[:150]}{RESET}")
            hidden = len(lines) - len(shown)
            if hidden > 0:
                if not _full:
                    # remember the call so a mouse click can expand it later
                    self.expandable.append(
                        {"tool": tool, "args": args, "result": result, "is_error": is_error, "hidden": hidden}
                    )
                    # cap memory: keep the last 12 expandable outputs — and
                    # shift hint_rows so every row keeps pointing at the
                    # same (now shifted) registry entry
                    while len(self.expandable) > 12:
                        self.expandable.pop(0)
                        self.hint_rows = {
                            r: i - 1 for r, i in self.hint_rows.items() if i > 1
                        }
                    row = _console_cursor_row()
                    idx = len(self.expandable)
                    if row is not None:
                        self.hint_rows[row] = idx
                hint = expand_hint(tool, hidden, self.expandable)
                self._box_print(f"  {MUTED}│{RESET} {hint}")

    def render_error(self, message: str) -> None:
        self._before_write()
        print(f"{RED}✗ {message}{RESET}")

    def render_warning(self, message: str) -> None:
        self._before_write()
        print(f"{GOLD}⚠ {message}{RESET}")

    def render_info(self, message: str) -> None:
        self._before_write()
        print(f"{BLUE}ℹ {message}{RESET}")

    def render_success(self, message: str) -> None:
        self._before_write()
        print(f"{ACCENT}✔ {message}{RESET}")

    def prompt_symbol(self) -> str:
        mode = "manual"
        try:
            from . import config as _cfg

            mode = _cfg.Config().mode
        except Exception:
            pass
        icons = {"manual": "❯", "accept": "❯❯", "plan": "◇", "auto": "❯❯❯"}
        colors = {"manual": ACCENT, "accept": SOFT, "plan": PURPLE, "auto": ACCENT}
        icon = icons.get(mode, "❯")
        color = colors.get(mode, ACCENT)
        return f"{color}{BOLD}{icon}{RESET} "

    def confirm(self, title: str, detail: str) -> bool:
        """Ask y/n for risky actions. Returns False if declined."""
        print(f"{GOLD}⚠ {BOLD}{title}{RESET} {GOLD}needs confirmation:{RESET}")
        print(f"  {SILVER}{detail[:400]}{RESET}")
        try:
            answer = input(f"  {GOLD}run? [y/N]{RESET} ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return False
        return answer in ("y", "yes")
