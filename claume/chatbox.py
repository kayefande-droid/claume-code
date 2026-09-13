"""claume chatbox — the Freebuff-style terminal input experience.

Upgrades the REPL from plain ``input()`` to a real chat box:

* **Fuzzy autocomplete drops** — ``/`` opens the command panel, ``@`` opens
  a file panel; both filter live as you type with an inverse-video
  selection bar (↑/↓ move, Tab/→ accept, Enter submits).
* **Ghost suggestion** — the likeliest history continuation renders dimmed
  after the cursor; → accepts it.
* **Input history** — ↑/↓ walk persisted history (``~/.claume/input_history``).
* **Multi-line editor** — Alt+Enter inserts a newline for long prompts.
* **Edit keys** — Home/End/Left/Right/Backspace/Delete/Ctrl+U.

Architecture: ``Editor`` is pure state logic (no I/O) so it is unit
testable; the render loop writes ANSI directly and degrades gracefully —
any terminal where raw mode is unavailable gets the plain ``input()``
path with identical behavior.
"""
from __future__ import annotations

import glob
import os
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# ANSI enablement (Windows) + key reader
# ---------------------------------------------------------------------------
_VT_STATE = {"enabled": False, "old_mode": None}


def enable_vt() -> bool:
    """Enable ANSI VT input on the Windows console (once). Idempotent."""
    if os.name != "nt":
        return False
    if _VT_STATE["enabled"]:
        return True
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-10)  # STD_INPUT_HANDLE
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        _VT_STATE["old_mode"] = mode.value
        # ENABLE_VIRTUAL_TERMINAL_INPUT, disable line + echo input
        new_mode = (mode.value | 0x0200) & ~0x0001 & ~0x0002
        if not kernel32.SetConsoleMode(handle, new_mode):
            return False
        _VT_STATE["enabled"] = True
        # Output side: allow ANSI rendering on legacy conhost.
        out = kernel32.GetStdHandle(-11)
        omode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(out, ctypes.byref(omode)):
            kernel32.SetConsoleMode(out, omode.value | 0x0004)
        return True
    except Exception:
        return False


def restore_console() -> None:
    if os.name != "nt" or not _VT_STATE["enabled"]:
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        if _VT_STATE["old_mode"] is not None:
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-10), _VT_STATE["old_mode"])
    except Exception:
        pass
    _VT_STATE["enabled"] = False


def read_key_vt() -> str:
    """Read one key with VT input enabled (Windows). Canonical tokens."""
    import msvcrt

    ch = sys.stdin.buffer.read(1)
    if not ch:
        return ""
    c = ch.decode("utf-8", "replace")
    if c == "\x1b":
        nxt = sys.stdin.buffer.read(1).decode("utf-8", "replace") if msvcrt.kbhit() else ""
        if nxt == "[":
            third = sys.stdin.buffer.read(1).decode("utf-8", "replace")
            return {
                "A": "UP", "B": "DOWN", "C": "RIGHT", "D": "LEFT",
                "H": "HOME", "F": "END", "Z": "SHIFT+TAB",
            }.get(third, "ESC")
        if nxt in ("\r", "\n"):
            return "ALT+ENTER"
        return "ESC"
    if c in ("\r", "\n"):
        return "ENTER"
    if c in ("\x7f", "\b"):
        return "BACKSPACE"
    if c == "\t":
        return "TAB"
    if c == "\x03":
        return "CTRL+C"
    if c == "\x04":
        return "CTRL+D"
    if c == "\x15":
        return "CTRL+U"
    return c


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------
def _history_path() -> Path:
    from . import config

    return config.claume_dir() / "input_history"


def load_history(limit: int = 200) -> List[str]:
    try:
        lines = _history_path().read_text(encoding="utf-8").splitlines()
        return [l for l in lines if l.strip()][-limit:]
    except Exception:
        return []


def append_history(entry: str) -> None:
    if not entry.strip() or entry.startswith("/"):
        return
    try:
        hist = load_history()
        if hist and hist[-1] == entry:
            return
        hist.append(entry)
        _history_path().write_text("\n".join(hist[-200:]), encoding="utf-8")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Completion providers
# ---------------------------------------------------------------------------
def _fuzzy_match(haystack: str, needle: str) -> bool:
    it = iter(haystack.lower())
    return all(ch in it for ch in needle.lower())


def _strip_ansi(s: str) -> str:
    import re

    return re.sub(r"\033\[[0-9;]*m", "", s)


def command_names() -> List[str]:
    from .commands import HELP_LINES  # late import avoids cycles

    cmds: List[str] = []
    for line in HELP_LINES:
        s = _strip_ansi(line).strip()
        if s.startswith("/"):
            name = s.split()[0]
            if name not in cmds:
                cmds.append(name)
    cmds += ["/exit", "/quit", "/skip", "/ask ", "/webdesign "]
    return sorted(set(cmds))


def complete_command(prefix: str) -> List[str]:
    return [c for c in command_names() if c.startswith(prefix)][:24]


def complete_file(prefix: str, cwd: Optional[Path] = None, max_results: int = 24) -> List[str]:
    """Complete '@fragment' against files under cwd (recursive)."""
    cwd = cwd or Path.cwd()
    frag = prefix[1:]
    if not frag or frag.endswith("/"):
        pattern_base = cwd / (frag or "")
        try:
            return [
                "@" + str(p.relative_to(cwd)).replace("\\", "/")
                for p in sorted(pattern_base.iterdir())[:max_results]
            ]
        except Exception:
            return []
    results: List[str] = []
    try:
        pattern = str(cwd / "**" / (frag + "*"))
        for p in sorted(glob.glob(pattern, recursive=True))[:400]:
            path = Path(p)
            if path.is_file():
                results.append("@" + str(path.relative_to(cwd)).replace("\\", "/"))
            if len(results) >= max_results:
                break
    except Exception:
        pass
    return results


def suggest_ghost(text: str, history: List[str]) -> str:
    """Continuation from history for the dimmed ghost text."""
    if not text or text.startswith(("/", "@")) or len(text) < 3:
        return ""
    for entry in reversed(history[-60:]):
        if entry != text and "\n" not in entry and entry.lower().startswith(text.lower()):
            return entry[len(text):]
    return ""


# ---------------------------------------------------------------------------
# Editor — pure state machine (no I/O, fully unit testable)
# ---------------------------------------------------------------------------
class Editor:
    """Multi-line text buffer + cursor + drop selection + history nav."""

    def __init__(
        self,
        completions: Optional[Callable[[str], List[str]]] = None,
        history: Optional[List[str]] = None,
    ) -> None:
        self.completions = completions or (lambda t: [])
        self.history = history if history is not None else []
        self.hidx = len(self.history)
        self.reset()

    def reset(self) -> None:
        self.lines: List[List[str]] = [[]]   # rows of chars
        self.row = 0
        self.col = 0
        self.drop: List[str] = []
        self.drop_sel = 0
        self.drop_kind = ""  # "cmd" | "file" | ""

    # -- state helpers -----------------------------------------------------
    @property
    def text(self) -> str:
        return "\n".join("".join(l) for l in self.lines)

    @property
    def single_line(self) -> bool:
        return len(self.lines) == 1

    def _refresh_drop(self) -> None:
        t = self.text
        self.drop_kind = ""
        if self.single_line and t.startswith("/") and " " not in t:
            self.drop = complete_command(t)
            self.drop_kind = "cmd"
        elif self.single_line and "@" in t and " " not in t[t.rindex("@"):]:
            self.drop = complete_file(t[t.rindex("@"):])
            self.drop_kind = "file"
        else:
            self.drop = []
        self.drop_sel = 0

    def _accept_drop(self, pick: str) -> None:
        t = self.text
        # Decide by the drop's kind, not by line prefix: a line may start
        # with a command AND contain an @file fragment being completed.
        if self.drop_kind == "file" and "@" in t:
            at = t.rindex("@")
            new = t[:at] + pick.rstrip() + " "
        else:
            new = pick.rstrip() + " "
        self.lines = [list(new)]
        self.row, self.col = 0, len(new)
        self.drop = []
        self.drop_kind = ""

    # -- key handling --------------------------------------------------------
    def key(self, k: str) -> Optional[str]:
        """Apply a key. Returns the submitted text on ENTER, else None.

        "INT" / "EOF" signal interrupts; "SHIFT+TAB" is surfaced to the
        caller (mode cycling).
        """
        result = self._key_inner(k)
        # Any buffer mutation re-filters the drop panel.
        if result is None and k not in ("UP", "DOWN", "LEFT", "RIGHT", "HOME", "END"):
            self._refresh_drop()
        return result

    def _key_inner(self, k: str) -> Optional[str]:
        if k == "CTRL+C":
            return "INT"
        if k == "CTRL+D":
            return "EOF"
        if k == "ENTER":
            if self.drop:
                pick = self.drop[self.drop_sel]
                self._accept_drop(pick)
                return None
            submitted = self.text
            append_history(submitted.replace("\n", " "))
            self.history = load_history()
            self.hidx = len(self.history)
            self.reset()
            return submitted
        if k == "ALT+ENTER":
            self.lines.insert(self.row + 1, [])
            self.row += 1
            self.col = 0
            return None
        if k == "TAB":
            if self.drop:
                self._accept_drop(self.drop[self.drop_sel])
            return None
        if k == "UP":
            if self.drop and self.drop_sel < len(self.drop) - 1:
                self.drop_sel += 1
            elif len(self.lines) > 1 and self.row > 0:
                self.row -= 1
                self.col = min(self.col, len(self.lines[self.row]))
            elif not self.drop and len(self.lines) == 1 and self.hidx > 0:
                self.hidx -= 1
                self.lines = [list(self.history[self.hidx])]
                self.row, self.col = 0, len(self.lines[0])
                self._refresh_drop()
            return None
        if k == "DOWN":
            if self.drop and self.drop_sel > 0:
                self.drop_sel -= 1
            elif self.drop:
                self.drop_sel = 0
            elif len(self.lines) > 1 and self.row < len(self.lines) - 1:
                self.row += 1
                self.col = min(self.col, len(self.lines[self.row]))
            elif len(self.lines) == 1 and self.hidx < len(self.history) - 1:
                self.hidx += 1
                self.lines = [list(self.history[self.hidx])]
                self.row, self.col = 0, len(self.lines[0])
                self._refresh_drop()
            elif len(self.lines) == 1:
                self.hidx = len(self.history)
                self.reset()
            return None
        if k == "LEFT":
            if self.col > 0:
                self.col -= 1
            elif self.row > 0:
                self.row -= 1
                self.col = len(self.lines[self.row])
            return None
        if k == "RIGHT":
            cur = self.lines[self.row]
            if self.col < len(cur):
                self.col += 1
            elif self.row < len(self.lines) - 1:
                self.row += 1
                self.col = 0
            return None
        if k == "HOME":
            self.col = 0
            return None
        if k == "END":
            self.col = len(self.lines[self.row])
            return None
        if k == "BACKSPACE":
            cur = self.lines[self.row]
            if self.col > 0:
                del cur[self.col - 1]
                self.col -= 1
            elif self.row > 0:
                prev = self.lines[self.row - 1]
                self.col = len(prev)
                prev.extend(cur)
                del self.lines[self.row]
                self.row -= 1
            return None
        if k == "DELETE":
            cur = self.lines[self.row]
            if self.col < len(cur):
                del cur[self.col]
            return None
        if k == "CTRL+U":
            self.reset()
            return None
        if k.startswith("ESC") or k == "SHIFT+TAB":
            return k  # let the caller decide (mode cycling etc.)
        # printable characters (a key may be a multi-char paste burst)
        cur = self.lines[self.row]
        for ch in k:
            if ch >= " ":
                cur.insert(self.col, ch)
                self.col += 1
        return None

    # -- ghost ---------------------------------------------------------------
    def ghost(self) -> str:
        if not self.single_line or self.drop:
            return ""
        return suggest_ghost(self.text, self.history)

    def accept_ghost(self) -> None:
        g = self.ghost()
        if g:
            cur = self.lines[self.row]
            cur.extend(list(g))
            self.col += len(g)
            self.drop = []


# ---------------------------------------------------------------------------
# Renderer — prompt line + drop below, cursor kept on the prompt line
# ---------------------------------------------------------------------------
RESET = "\033[0m"
DIM = "\033[2m"
INVERT = "\033[7m"
CLEAR_DOWN = "\033[J"


class Renderer:
    """Draws prompt+buffer on one line and the drop panel below it."""

    def __init__(self, prompt: str, width: int = 100) -> None:
        self.prompt = prompt
        # prompt may contain ANSI escapes — measure the visible length only.
        self.plain_len = len(_strip_ansi(prompt))
        self.width = max(40, min(width, (os.get_terminal_size().columns - 1) if _cols() else 100))
        self.rows_drawn = 0  # total lines currently on screen for this frame

    def render(self, ed: Editor, ghost: str = "") -> None:
        out = []
        if self.rows_drawn:
            # return to the prompt row (cursor sits at line start before redraw)
            out.append(f"\033[{self.rows_drawn - 1}A\r{CLEAR_DOWN}")
        line = "".join(ed.lines[ed.row]) if ed.lines else ""
        before = line[: ed.col]
        at_ch = line[ed.col: ed.col + 1] or " "
        after = line[ed.col + 1:]
        ghost_txt = ""
        if ed.col >= len(line) and ghost:
            ghost_txt = "\033[38;5;240m" + ghost[: max(0, self.width - len(before) - 2)] + RESET
        out.append(f"\r{self.prompt}{before}{INVERT}{at_ch}{RESET}{after}{ghost_txt}")
        rows = 1
        if ed.drop:
            shown = ed.drop[:7]
            for i, opt in enumerate(shown):
                mark = "❯ " if i == ed.drop_sel else "  "
                style = INVERT if i == ed.drop_sel else DIM
                label = (mark + opt)[: self.width - 2]
                out.append("\n" + style + label.ljust(self.width - 2) + RESET)
            rows += len(shown)
        if rows > 1:
            # park the cursor back on the prompt row, at the edit column
            out.append(f"\033[{rows - 1}A")
        out.append(f"\r\033[{self.plain_len + ed.col + 1}C")
        sys.stdout.write("".join(out))
        sys.stdout.flush()
        self.rows_drawn = rows

    def finish(self, ed: Editor, final_text: str) -> None:
        """Collapse the frame into the final submitted line."""
        if self.rows_drawn:
            sys.stdout.write(f"\033[{self.rows_drawn - 1}A\r{CLEAR_DOWN}")
        sys.stdout.write(f"{self.prompt}{final_text.replace(chr(10), DIM + '⏎' + RESET)}\n")
        sys.stdout.flush()
        self.rows_drawn = 0

    def clear(self) -> None:
        if self.rows_drawn:
            sys.stdout.write(f"\033[{self.rows_drawn - 1}A\r{CLEAR_DOWN}")
            sys.stdout.flush()
        self.rows_drawn = 0


def _cols() -> bool:
    try:
        os.get_terminal_size()
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------
def read_line(
    prompt: str,
    completions: Optional[Callable[[str], List[str]]] = None,
    history: Optional[List[str]] = None,
    on_shift_tab: Optional[Callable[[], None]] = None,
) -> str:
    """Read one logical line with the full chat box experience.

    Falls back to plain input() when raw mode is unavailable.
    Returns the text (may be multi-line if Alt+Enter was used).
    Raises KeyboardInterrupt / EOFError like input().
    """
    if not sys.stdin.isatty():
        try:
            return input(prompt)
        except EOFError:
            raise
    if os.name == "nt":
        raw_ok = enable_vt()
        if not raw_ok:
            try:
                return input(prompt)
            except EOFError:
                raise
    else:
        raw_ok = True

    ed = Editor(completions=completions, history=history if history is not None else load_history())
    rend = Renderer(prompt)
    try:
        while True:
            rend.render(ed, ed.ghost())
            if os.name == "nt":
                k = read_key_vt()
            else:
                k = _read_key_posix()
            result = ed.key(k)
            if result == "INT":
                rend.clear()
                print()
                raise KeyboardInterrupt
            if result == "EOF":
                rend.clear()
                raise EOFError
            if isinstance(result, str) and result == "SHIFT+TAB":
                rend.clear()
                if on_shift_tab:
                    on_shift_tab()
                continue
            if result is not None:
                rend.finish(ed, result)
                return result
    finally:
        restore_console()
        rend.clear()


def _read_key_posix() -> str:
    import termios
    import tty

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    tty.setraw(fd)
    try:
        c = sys.stdin.read(1)
        if c == "\x1b":
            c2 = sys.stdin.read(1)
            if c2 == "[":
                c3 = sys.stdin.read(1)
                return {"A": "UP", "B": "DOWN", "C": "RIGHT", "D": "LEFT", "H": "HOME", "F": "END", "Z": "SHIFT+TAB"}.get(c3, "ESC")
            if c2 in ("\r", "\n"):
                return "ALT+ENTER"
            return "ESC"
        if c in ("\r", "\n"):
            return "ENTER"
        if c in ("\x7f", "\b"):
            return "BACKSPACE"
        if c == "\t":
            return "TAB"
        if c == "\x03":
            return "CTRL+C"
        if c == "\x04":
            return "CTRL+D"
        return c
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
