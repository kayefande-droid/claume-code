"""Terminal UI for claume-code — pixel art, animations, colored output.

Zero dependencies: pure ANSI. Designed to feel like Claude Code and
Freebuff: bold banner, dim stream of thought, bright tool results.
"""
from __future__ import annotations

import os
import sys
import time
from typing import List, Optional

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
# Colors / theme
# --------------------------------------------------------------------------
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

GREEN = "\033[38;5;46m" if COLOR else ""      # NVIDIA green accent
MINT = "\033[38;5;120m" if COLOR else ""
GREY = "\033[38;5;245m" if COLOR else ""
SILVER = "\033[38;5;250m" if COLOR else ""
GOLD = "\033[38;5;220m" if COLOR else ""
RED = "\033[38;5;203m" if COLOR else ""
BLUE = "\033[38;5;75m" if COLOR else ""
PURPLE = "\033[38;5;135m" if COLOR else ""
BG_PANEL = "\033[48;5;236m" if COLOR else ""

# --------------------------------------------------------------------------
# Pixel banner (5-row block font, feels "pixelated" in terminal)
# --------------------------------------------------------------------------
_BANNER = [
    " ██████╗██╗      █████╗ ██╗   ██╗███╗   ███╗███████╗",
    "██╔════╝██║     ██╔══██╗██║   ██║████╗ ████║██╔════╝",
    "██║     ██║     ███████║██║   ██║██╔████╔██║███████╗",
    "██║     ██║     ██╔══██║██║   ██║██║╚██╔╝██║╚════██║",
    "╚█████╗ ███████╗██║  ██║╚██████╔╝██║ ╚═╝ ██║███████║",
    " ╚════╝ ╚══════╝╚═╝  ╚═╝ ╚═════╝ ╚═╝     ╚═╝╚══════╝",
]

_BANNER_WIDTH = max(len(row) for row in _BANNER)


def banner_lines() -> List[str]:
    out = []
    for row in _BANNER:
        out.append(f"{GREEN}{row}{RESET}")
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
        f"{GREY}▌{MINT} pixel-grade coding agent {GREY}· v{version} "
        f"· free-claume proxy · NVIDIA NIM{RESET}"
    )


# --------------------------------------------------------------------------
# Small pieces
# --------------------------------------------------------------------------
def box(title: str, body_lines: List[str], color: str = GREEN, width: int = 64) -> None:
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
# Render helpers used by the agent
# --------------------------------------------------------------------------
class UI:
    def __init__(self, quiet: bool = False) -> None:
        self.quiet = quiet
        self._streaming = False

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
            sys.stdout.write(f"{DIM}▌ ")
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
        color = RED if is_error else GREEN
        summary = str(args.get("path") or args.get("command") or args.get("url") or args.get("query") or "")
        summary = " ".join(str(summary).split())[:70]
        print(f"{color}{icon} {tool}{RESET} {GREY}{summary}{RESET}")
        if result and not self.quiet:
            lines = result.splitlines()
            shown = lines[:14]
            for line in shown:
                print(f"  {GREY}│{RESET} {SILVER}{line[:150]}{RESET}")
            if len(lines) > 14:
                print(f"  {GREY}│ … {len(lines) - 14} more lines{RESET}")

    def render_error(self, message: str) -> None:
        print(f"{RED}✗ {message}{RESET}")

    def render_warning(self, message: str) -> None:
        print(f"{GOLD}⚠ {message}{RESET}")

    def render_info(self, message: str) -> None:
        print(f"{BLUE}ℹ {message}{RESET}")

    def render_success(self, message: str) -> None:
        print(f"{GREEN}✔ {message}{RESET}")

    def prompt_symbol(self) -> str:
        return f"{GREEN}❯{RESET} "

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
