"""Terminal UI for claume-code — pixel art, animations, colored output.

Zero dependencies: pure ANSI. Designed to feel like Claude Code and
Freebuff: bold banner, dim stream of thought, bright tool results.
v2: color themes, mode chips, pixel mascot, expandable output, clipboard.
"""
from __future__ import annotations

import os
import sys
import time
from typing import Dict, List, Optional

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
        "WOLD": "\033[38;5;220m",  # (typo tolerated for mono)
        "RED": "\033[38;5;247m",
        "BLUE": "\033[38;8;246m",
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
    speed = 0.0 if fast else 0.045
    if not COLOR or not sys.stdout.isatty():
        for row in banner_lines():
            print(row)
        return
    _clear_screen()
    for row in banner_lines():
        print(row)
        if speed:
            sys.stdout.flush()
            time.sleep(speed)
    print()


def pixel_tagline(version: str) -> str:
    return (
        f"{MUTED}▌{SOFT} pixel-grade coding agent {MUTED}· v{version} "
        f"· free-claume proxy · NVIDIA NIM{RESET}"
    )


# --------------------------------------------------------------------------
# Pixel bot mascot — a tiny animated agent face
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


class Mascot:
    """Animated pixel bot rendered beside a status line."""

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled and COLOR and sys.stdout.isatty()
        self._frame = 0

    def render(self, mood: str = "idle", note: str = "") -> str:
        if not self.enabled:
            return ""
        self._frame = (self._frame + 1) % len(MASCOT_FRAMES)
        art = MASCOT_FRAMES[self._frame]
        label = MASCOT_MOODS.get(mood, mood)
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
        self._thread: Optional[__import__("threading").Thread] = None

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
# Render helpers used by the agent
# --------------------------------------------------------------------------
class UI:
    def __init__(self, quiet: bool = False) -> None:
        self.quiet = quiet
        self._streaming = False
        self.expand_output = False  # show full tool output (toggled by /expand)
        self.mascot = Mascot(enabled=not quiet)
        self.last_final = ""  # remembered for /copy

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
            sys.stdout.write(f"{MUTED}▌ ")
        buffer.append(token)
        sys.stdout.write(token.replace("\n", "\n  "))
        sys.stdout.flush()

    def end_stream(self, buffer: List[str]) -> None:
        if self._streaming:
            sys.stdout.write(RESET + "\n")
            sys.stdout.flush()
            self._streaming = False
        buffer.clear()

    # -- agent renders --------------------------------------------------
    def render_thought(self, thought: str) -> None:
        if not thought or self.quiet:
            return
        print(f"{PURPLE}◈ thought{RESET} {ITALIC}{thought}{RESET}")

    def render_action(self, tool: str, args: dict, result: str, is_error: bool) -> None:
        if self.quiet:
            return
        icon = "✗" if is_error else "✓"
        color = RED if is_error else ACCENT
        summary = str(args.get("path") or args.get("command") or args.get("url") or args.get("query") or "")
        summary = " ".join(str(summary).split())[:70]
        print(f"{color}{icon} {tool}{RESET} {MUTED}{summary}{RESET}")
        if result and not self.quiet:
            lines = result.splitlines()
            shown = lines[:14]
            for line in shown:
                print(f"  {MUTED}│{RESET} {SILVER}{line[:150]}{RESET}")
            hidden = len(lines) - 14
            if hidden > 0:
                hint = f"  {MUTED}│ … +{hidden} more lines — /expand to show full output{RESET}"
                print(hint)

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
