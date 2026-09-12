"""Terminal UI for claume-code — pixel art, animations, colored output.

Zero dependencies: pure ANSI. Designed to feel like Claude Code and
Freebuff: bold banner, dim stream of thought, bright tool results.
v2.1: animated thinking shimmer, Claude-style chat highlighting,
mouse-tracking pixel mascot, Freebuff-style input box, copy mode.
"""
from __future__ import annotations

import os
import sys
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
    " ██████╗██╗      █████╗ ██╗   ██╗███╗   ███╗███████╗███████╗",
    "██╔════╝██║     ██╔══██╗██║   ██║████╗ ████║██╔════╝██╔════╝",
    "██║     ██║     ███████║██║   ██║██╔████╔██║███████╗█████╗  ",
    "██║     ██║     ██╔══██║██║   ██║██║╚██╔╝██║╚════██║╚════██║",
    "╚█████╗ ███████╗██║  ██║╚██████╔╝██║ ╚═╝ ██║███████║███████║",
    " ╚════╝ ╚══════╝╚═╝  ╚═╝ ╚═════╝ ╚═╝     ╚═╝╚══════╝╚══════╝",
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
        f"· free-claume proxy · NVIDIA NIM{RESET}"
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
# Click-and-pull copy mode: drag-select → clipboard (Windows)
# --------------------------------------------------------------------------
def copy_mode() -> None:
    """Interactive copy helper: on Windows, watches for a left-button
    drag; when the drag ends, reads whatever text the terminal put on the
    clipboard (Windows Terminal copies on select with the right settings,
    and ctrl+shift+c always works) and re-copies via claume so /copy and
    paste work everywhere. Enter or ctrl+c exits.
    """
    from .ui import ACCENT, BOLD, MUTED, RESET

    print(f"{ACCENT}⧉ copy mode{RESET} {MUTED}— drag to select text, then release · Enter to exit{RESET}")
    if os.name != "nt":
        print(f"{MUTED}  (use your terminal's native selection · press Enter to exit){RESET}")
        try:
            input()
        except (EOFError, KeyboardInterrupt):
            pass
        print(f"{MUTED}copy mode off{RESET}")
        return

    import ctypes

    user32 = ctypes.windll.user32
    last_clip = _read_clipboard_text()
    print(f"{MUTED}  waiting for a drag-selection…{RESET}")
    try:
        while True:
            # Enter pressed?
            if user32.GetAsyncKeyState(0x0D) & 1:
                break
            # Left button currently down?
            if user32.GetAsyncKeyState(0x01) & 0x8000:
                start = _cursor_pos()
                # wait for release
                while user32.GetAsyncKeyState(0x01) & 0x8000:
                    time.sleep(0.05)
                end = _cursor_pos()
                time.sleep(0.15)  # let the terminal update its selection
                if start and end and (abs(start[0] - end[0]) + abs(start[1] - end[1])) > 6:
                    sel = _read_clipboard_text()
                    if sel and sel != last_clip:
                        last_clip = sel
                        preview = " ".join(sel.split())[:60]
                        print(f"{ACCENT}  ⧉ pulled {len(sel)} chars:{RESET} {preview}…")
                    else:
                        print(
                            f"{MUTED}  selection detected — if your terminal didn't copy "
                            f"it, press ctrl+shift+c then it lands in the clipboard{RESET}"
                        )
            time.sleep(0.05)
    except KeyboardInterrupt:
        pass
    print(f"{MUTED}copy mode off{RESET}")


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
        if self._words:
            print(f"{PURPLE}✻ thought{RESET} {MUTED}({elapsed}s){RESET} {ITALIC}{self._words}{RESET}")
        else:
            print(f"{PURPLE}✻ thought{RESET} {MUTED}({elapsed}s){RESET}")
        self._start = None


# --------------------------------------------------------------------------
# Render helpers used by the agent
# --------------------------------------------------------------------------
class UI:
    def __init__(self, quiet: bool = False) -> None:
        self.quiet = quiet
        self._streaming = False
        self.expand_output = False  # show full tool output (toggled by /expand)
        self.mascot = Mascot(enabled=not quiet, mouse_tracking=True)
        self.last_final = ""  # remembered for /copy
        self.thinking = ThinkingPanel()

    # -- boot ---------------------------------------------------------
    def show_banner(self, version: str, fast: bool = False) -> None:
        animate_banner(fast=fast)
        print(pixel_tagline(version))
        print()

    # -- streaming ----------------------------------------------------
    def stream_token(self, token: str, buffer: List[str]) -> None:
        if self.quiet:
            buffer.append(token)
            return
        if not self._streaming:
            self._streaming = True
        buffer.append(token)
        sys.stdout.write(token.replace("\n", "\n  "))
        sys.stdout.flush()

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
        self.thinking.begin()

    def thought_stream_tick(self, frame: int) -> None:
        if self.quiet:
            return
        self.thinking.tick(frame)

    def thought_stream_end(self, thought: str = "") -> None:
        if self.quiet:
            return
        if thought:
            self.thinking.set_words(thought)
        self.thinking.end()

    # -- agent renders --------------------------------------------------
    def render_thought(self, thought: str) -> None:
        """Claude Code style collapsed thought line."""
        if not thought or self.quiet:
            return
        words = " ".join(thought.split())
        head = words[:80] + ("…" if len(words) > 80 else "")
        print(f"{PURPLE}✻ thinking{RESET} {ITALIC}{head}{RESET}")

    def render_action(self, tool: str, args: dict, result: str, is_error: bool) -> None:
        if self.quiet:
            return
        icon = "✗" if is_error else "✓"
        color = RED if is_error else ACCENT
        summary = str(args.get("path") or args.get("command") or args.get("url") or args.get("query") or "")
        summary = " ".join(str(summary).split())[:70]
        print(f"{color}{icon} {BOLD}{tool}{RESET} {MUTED}{summary}{RESET}")
        if result and not self.quiet:
            lines = result.splitlines()
            shown = lines if self.expand_output else lines[:14]
            for line in shown:
                print(f"  {MUTED}│{RESET} {SILVER}{line[:150]}{RESET}")
            hidden = len(lines) - len(shown)
            if hidden > 0:
                print(f"  {MUTED}│ … +{hidden} more lines — /expand to show full output{RESET}")

    def render_error(self, message: str) -> None:
        print(f"{RED}✗ {message}{RESET}")

    def render_warning(self, message: str) -> None:
        print(f"{GOLD}⚠ {message}{RESET}")

    def render_info(self, message: str) -> None:
        print(f"{BLUE}ℹ {message}{RESET}")

    def render_success(self, message: str) -> None:
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
