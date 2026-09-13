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
    """Prepare the console for the chat box (Windows). Idempotent.

    IMPORTANT: input console modes are left UNTOUCHED — mutating them
    broke typing entirely (Python's stdin buffering never delivered the
    events). We only enable VT *output* processing for legacy conhost;
    keys are read per-event via msvcrt (see read_key_vt).
    """
    if os.name != "nt":
        return False
    if _VT_STATE["enabled"]:
        return True
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        out = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        omode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(out, ctypes.byref(omode)):
            kernel32.SetConsoleMode(out, omode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        _VT_STATE["enabled"] = True
        return True
    except Exception:
        return False


def restore_console() -> None:
    """Restore console state (bracketed paste off; nothing else changed)."""
    if os.name != "nt" or not _VT_STATE["enabled"]:
        return
    try:
        sys.stdout.write("\033[?2004l")  # bracketed paste off
        sys.stdout.flush()
    except Exception:
        pass
    _VT_STATE["enabled"] = False


# Special tokens returned by the key readers.
PASTE_START = "__PASTE_START__"
PASTE_END = "__PASTE_END__"

# ---------------------------------------------------------------------------
# Open-box registry — lets worker-thread output reflow the open box
# ---------------------------------------------------------------------------
# The REPL keeps the box rendered while a task runs in the background.
# When the worker prints, it calls close_box() so output lands on clean
# lines ABOVE where the box was; the next keystroke redraws the box below
# the new output. Pure-stdout, no cursor juggling — safe from any thread.
_OPEN_BOX: Optional["Renderer"] = None


def box_open() -> bool:
    return _OPEN_BOX is not None


def close_box() -> None:
    """Wipe the on-screen box frame (call before printing output)."""
    global _OPEN_BOX
    r = _OPEN_BOX
    if r is not None:
        try:
            r.clear()
        except Exception:
            pass
        _OPEN_BOX = None


def reopen_box() -> None:
    """Redraw the box after output pushed the scroll position (best effort)."""
    r = _OPEN_BOX
    if r is not None and r.ed is not None:
        try:
            r.render(r.ed, r.ed.ghost())
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Image attachments — /image <path> pins a file onto the next task
# ---------------------------------------------------------------------------
_MIME = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp",
}


def attach_image(path: str) -> Optional[Dict[str, str]]:
    """Read an image file and return {name, data_url, bytes} for an
    OpenAI-style vision payload, or None if unreadable/unsupported."""
    import base64

    try:
        p = Path(path).expanduser()
        if not p.is_file():
            return None
        mime = _MIME.get(p.suffix.lower())
        if not mime:
            return None
        raw = p.read_bytes()
        if len(raw) > 12 * 1024 * 1024:
            return None  # keep requests sane (>12 MB)
        b64 = base64.b64encode(raw).decode("ascii")
        return {
            "name": p.name,
            "data_url": f"data:{mime};base64,{b64}",
            "bytes": str(len(raw) // 1024) + " KB",
        }
    except Exception:
        return None

_LEGACY_SPECIAL = {
    "H": "UP", "P": "DOWN", "K": "LEFT", "M": "RIGHT",
    "G": "HOME", "O": "END", "S": "DELETE", "R": "INSERT",
}


def _map_vt_sequence(seq: str) -> str:
    """Map a CSI sequence body (after ESC[') to a token."""
    if seq.startswith("200~"):
        return PASTE_START
    if seq.startswith("201~"):
        return PASTE_END
    return {
        "A": "UP", "B": "DOWN", "C": "RIGHT", "D": "LEFT",
        "H": "HOME", "F": "END", "Z": "SHIFT+TAB",
        "1~": "HOME", "7~": "HOME", "4~": "END", "8~": "END",
        "3~": "DELETE",
    }.get(seq, "ESC")


def _map_legacy(code: str) -> str:
    """Map the char after a \x00/\xe0 prefix (legacy console codes)."""
    if code == "\r":
        return "ALT+ENTER"
    return _LEGACY_SPECIAL.get(code.upper(), "ESC")


def read_key_vt() -> str:
    """Read one key on Windows via msvcrt — per-event, never blocks on
    line buffering. Handles legacy (\xe0-prefixed) AND VT (ESC[…) arrow
    keys, Alt+Enter, and bracketed-paste markers."""
    import msvcrt

    ch = msvcrt.getwch()
    if ch in ("\x00", "\xe0"):  # legacy special-key prefix
        return _map_legacy(msvcrt.getwch())
    if ch == "\x1b":  # ESC: VT sequence, Alt+Enter, or bare Esc
        if msvcrt.kbhit():
            nxt = msvcrt.getwch()
            if nxt == "[":
                seq = ""
                deadline = 24  # hard cap on sequence length
                while deadline:
                    deadline -= 1
                    if not msvcrt.kbhit():
                        break
                    c = msvcrt.getwch()
                    seq += c
                    if c.isalpha() or c == "~":
                        break
                return _map_vt_sequence(seq) if seq else "ESC"
            if nxt in ("\r", "\n"):
                return "ALT+ENTER"
            if nxt in ("\x00", "\xe0"):
                return _map_legacy(msvcrt.getwch())
            return "ESC"
        return "ESC"
    if ch in ("\r", "\n"):
        return "ENTER"
    if ch in ("\x7f", "\b", "\x08"):
        return "BACKSPACE"
    if ch == "\t":
        return "TAB"
    if ch == "\x04":
        return "CTRL+D"
    if ch == "\x15":
        return "CTRL+U"
    # \x03 (Ctrl+C) is delivered as a signal by Windows; Python raises
    # KeyboardInterrupt inside getwch — handled by the caller.
    return ch


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
        self._pasting = False
        self.paste_hints = 0  # newlines seen while pasting

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
            # Paste-safe submit: an Enter inside a pasted multi-line blob
            # inserts a newline UNLESS the cursor sits at the blob's end
            # (then it submits). Prevents giant pastes self-submitting on
            # their internal line breaks while keeping one-press submit.
            if self._pasting:
                self.paste_hints += 1
                cur = self.lines[self.row]
                at_end = self.col >= len(cur)
                last_row = self.row >= len(self.lines) - 1
                if not (at_end and last_row):
                    return self.key("ALT+ENTER")
            submitted = self.text
            append_history(submitted.replace("\n", " ")[:200])
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
        if k == PASTE_START:
            self._pasting = True
            return None
        if k == PASTE_END:
            self._pasting = False
            return None
        if k.startswith("ESC") or k == "SHIFT+TAB":
            return k  # let the caller decide (mode cycling etc.)
        # printable characters / paste bursts
        if "\n" in k or "\r" in k:
            # multi-line paste chunk: split at newlines into editor rows
            chunk = k.replace("\r\n", "\n").replace("\r", "\n")
            parts = chunk.split("\n")
            cur = self.lines[self.row]
            tail = cur[self.col:]
            del cur[self.col:]
            for i, part in enumerate(parts):
                for ch in part:
                    if ch >= " ":
                        cur.append(ch)
                if i < len(parts) - 1:
                    self.lines.insert(self.row + 1, tail if i == len(parts) - 2 else [])
                    self.row += 1
                    cur = self.lines[self.row]
                    self.col = 0
            self.col = len(self.lines[self.row])
            return None
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

    def __init__(self, prompt: str, width: int = 100, placeholder: str = "") -> None:
        self.prompt = prompt
        # prompt may contain ANSI escapes — measure the visible length only.
        self.plain_len = len(_strip_ansi(prompt))
        self.width = max(40, min(width, (os.get_terminal_size().columns - 1) if _cols() else 100))
        self.placeholder = placeholder
        self.rows_drawn = 0  # total lines currently on screen for this frame
        self.ed: Optional[Editor] = None  # set by read_line (for reopen_box)
        self.busy = False  # True while a task runs in the background

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
        elif not line and self.busy:
            # busy hint outranks the idle placeholder
            ghost_txt = "\033[38;5;240mtask running — type to queue · / for commands · /skip stops it" + RESET
        elif not line and self.placeholder:
            # dimmed placeholder while the buffer is empty
            ghost_txt = "\033[38;5;240m" + self.placeholder[: max(0, self.width - len(before) - 2)] + RESET
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
        self._deregister()

    def clear(self) -> None:
        if self.rows_drawn:
            sys.stdout.write(f"\033[{self.rows_drawn - 1}A\r{CLEAR_DOWN}")
            sys.stdout.flush()
        self.rows_drawn = 0
        self._deregister()

    def _deregister(self) -> None:
        """Any clear path un-registers this box (stale-open guard)."""
        global _OPEN_BOX
        if _OPEN_BOX is self:
            _OPEN_BOX = None


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
    placeholder: str = "",
    busy: bool = False,
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
    rend = Renderer(prompt, placeholder=placeholder)
    rend.ed = ed
    global _OPEN_BOX, last_attachments
    _OPEN_BOX = rend
    last_attachments = []
    paste_bytes = 0
    rend.busy = busy
    if busy:
        rend.width = max(40, min(rend.width, 88))
    try:
        # enable bracketed paste so terminal paste arrives as one chunk
        try:
            sys.stdout.write("\033[?2004h")
            sys.stdout.flush()
        except Exception:
            pass
        while True:
            rend.render(ed, ed.ghost())
            try:
                if os.name == "nt":
                    k = read_key_vt()
                else:
                    k = _read_key_posix()
            except KeyboardInterrupt:
                # Ctrl+C surfaces as an exception inside getwch on Windows
                k = "CTRL+C"
            result = ed.key(k)
            if k == PASTE_START:
                paste_bytes = 0
                continue
            if k == PASTE_END:
                paste_bytes = 0
                continue
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
                if _OPEN_BOX is rend:
                    _OPEN_BOX = None
                return result
    finally:
        restore_console()
        rend.clear()
        if _OPEN_BOX is rend:
            _OPEN_BOX = None


# Attachments collected for the NEXT submitted task (/image <path>).
last_attachments: List[Dict[str, str]] = []


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
                seq = ""
                while True:
                    c3 = sys.stdin.read(1)
                    seq += c3
                    if c3.isalpha() or c3 == "~" or not c3:
                        break
                return _map_vt_sequence(seq)
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
        if c == "\x15":
            return "CTRL+U"
        return c
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
