"""claume pinbox — the Freebuff-style PINNED bottom chat box.

The box is drawn into the last ``RESERVE`` rows of the terminal and the
VT scroll region (DECSTBM ``ESC[1;{n}r``) is set so the region ABOVE the
box is the only part that ever scrolls. Output (tasks, thoughts, tool
lines, command output) scrolls through the upper region; the box never
moves, never reflows, and clears on Enter — the transcript keeps
scrolling above it exactly like the Freebuff terminal.

How every print reaches the right place: while pinned, ``sys.stdout`` is
replaced by ``_PinnedStdout``, which parks the cursor at the bottom row
of the scroll region before each output burst. Prints therefore scroll
the region; the box rows sit OUTSIDE the region and are only ever
touched by ``_draw_box`` (absolute positioning + clear-line).

Layout (RESERVE = 6 rows at the bottom):

    ┌────────────────────────── scroll region ─────────────────────┐
    │  ... transcript, thoughts, tool output scroll here ...       │
    └──────────────────────────────────────────────────────────────┘
    ╭ auto · project ──────────────────────────────────── 4m12s ╮
    │ ❯ type here, paste, /commands…                             │
    │   (3 drop rows — /command and @file completions)           │
    ╰────────────────────────────────────────────────────────────╯

Reuses claume.chatbox's pure Editor + key readers; this module owns the
screen geometry. Falls back to chatbox.read_line (and then plain
input()) on small/non-VT terminals.
"""
from __future__ import annotations

import os
import sys
import threading
import time
from typing import Callable, List, Optional, Tuple

from . import chatbox as _cb

RESET = "\x1b[0m"
DIM = "\x1b[2m"
INVERT = "\x1b[7m"
HIDE_CURSOR = "\x1b[?25l"
SHOW_CURSOR = "\x1b[?25h"
PASTE_ON = "\x1b[?2004h"
PASTE_OFF = "\x1b[?2004l"

RESERVE = 6  # top border, input row, 3 drop rows, bottom border

BUSY_HINT = "task running — type to queue · / for commands · /skip stops it"

_STATE = {
    "pinned": False,
    "rows": 0,
    "cols": 0,
    "labels": None,       # Callable[[], Tuple[str, str]] (left, right)
    "busy": False,
    "placeholder": "",
    "prompt": "",
    "ed": None,           # active chatbox.Editor
    "parked": False,      # cursor currently at region bottom?
    "last_output": 0.0,
    "dirty": False,
}
_lock = threading.RLock()
_watcher: Optional[threading.Thread] = None
_real_stdout = None


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _vis_len(s: str) -> int:
    import re

    return len(re.sub(r"\033\[[0-9;]*m", "", s))


def _palette() -> dict:
    try:
        from .frame import _palette as _fp

        return _fp()
    except Exception:
        return {
            "accent": "", "soft": "", "text": "", "muted": "", "gold": "",
            "red": "", "reset": RESET, "bold": "", "dim": "", "color": "",
        }


def _out() -> str:
    return _real_stdout if _real_stdout is not None else sys.stdout


def _term() -> Tuple[int, int]:
    try:
        size = os.get_terminal_size()
        return int(size.columns), int(size.lines)
    except Exception:
        return 0, 0


def supported() -> bool:
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except Exception:
        return False


def region_bottom() -> int:
    return max(1, _STATE["rows"] - RESERVE)


# ---------------------------------------------------------------------------
# pin lifecycle
# ---------------------------------------------------------------------------
def enter(labels: Optional[Callable[[], Tuple[str, str]]] = None) -> bool:
    """Pin the box: reserve the bottom rows, activate the scroll region,
    and route stdout through the transcript-parking proxy. Idempotent."""
    global _watcher, _real_stdout
    with _lock:
        if _STATE["pinned"]:
            if labels is not None:
                _STATE["labels"] = labels
            return True
        if not supported():
            return False
        _cb.enable_vt()
        cols, rows = _term()
        if rows < RESERVE + 8 or cols < 30:
            return False
        real = sys.stdout
        try:
            real.flush()
            # push prior content up so the reserved rows are blank
            real.write("\n" * (RESERVE + 1))
            real.write(PASTE_ON)
            real.flush()
        except Exception:
            pass
        _real_stdout = real
        _STATE.update(
            pinned=True, rows=rows, cols=cols, parked=False,
            last_output=time.time(), dirty=True,
        )
        if labels is not None:
            _STATE["labels"] = labels
        _set_region(rows)
        sys.stdout = _PinnedStdout(real)
        _start_watcher()
        _draw_box()
        return True


def _set_region(rows: int) -> None:
    try:
        _out().write(f"\x1b[1;{region_bottom() if rows == 0 else max(1, rows - RESERVE)}r")
        _out().flush()
    except Exception:
        pass


def leave() -> None:
    """Un-pin: reset the scroll region and restore the real stdout."""
    global _real_stdout
    with _lock:
        if not _STATE["pinned"]:
            return
        _STATE["pinned"] = False
        try:
            if sys.stdout is not _real_stdout and isinstance(sys.stdout, _PinnedStdout):
                sys.stdout = _real_stdout
            o = _out()
            o.write(f"\x1b[{region_bottom()};1H\n\x1b[r{PASTE_OFF}{SHOW_CURSOR}")
            o.write("\n")
            o.flush()
        except Exception:
            pass
        _real_stdout = None
        _STATE["ed"] = None


def pinned() -> bool:
    return _STATE["pinned"]


# ---------------------------------------------------------------------------
# output routing — any thread
# ---------------------------------------------------------------------------
def _park() -> None:
    """Move the cursor to the bottom row of the scroll region (via the
    real stdout — internal use; callers hold the lock)."""
    try:
        o = _out()
        o.flush()
        o.write(f"\x1b[{region_bottom()};1H")
        o.flush()
        _STATE["parked"] = True
        _STATE["last_output"] = time.time()
        _STATE["dirty"] = True
    except Exception:
        pass


def prepare_output() -> None:
    """Force-park the cursor so the next prints scroll the transcript."""
    with _lock:
        if not _STATE["pinned"]:
            _cb.close_box()
            return
        _park()


class _PinnedStdout:
    """stdout proxy: parks the cursor at the scroll-region bottom before
    each output burst, so every print() in the app scrolls the transcript
    region instead of ever touching the box rows. When an editor is open
    (user typing), the input row is redrawn after the burst so the cursor
    snaps back into the box."""

    def __init__(self, real) -> None:
        self._real = real

    def write(self, s):
        with _lock:
            if not _STATE["pinned"]:
                return self._real.write(s)
            if not _STATE["parked"]:
                _park()
        n = self._real.write(s)
        with _lock:
            # keep the typing cursor inside the box during output bursts
            if _STATE["pinned"] and _STATE.get("ed") is not None and "\n" in s:
                _write_input_row()
        return n

    def flush(self):
        return self._real.flush()

    def __getattr__(self, name):
        return getattr(self._real, name)

    @property
    def encoding(self):
        return getattr(self._real, "encoding", "utf-8")

    def isatty(self):
        return True


def finalize(text: str) -> None:
    """Echo a submitted prompt into the transcript, then leave the input
    row empty — the box stays pinned, cleared, ready for the next task."""
    with _lock:
        if not _STATE["pinned"]:
            print(text)
            return
        _park()
        shown = text.replace("\n", DIM + " ⏎ " + RESET)
        try:
            o = _out()
            o.write(shown + "\n")
            o.flush()
        except Exception:
            pass
        _write_input_row()


def set_busy(busy: bool) -> None:
    """Update the idle hint; the watcher redraws the box within ~0.4s."""
    with _lock:
        if _STATE["busy"] != busy:
            _STATE["busy"] = busy
            _STATE["dirty"] = True


# ---------------------------------------------------------------------------
# box drawing (absolute positioning; never scrolls)
# ---------------------------------------------------------------------------
def _border_rows() -> Tuple[str, str]:
    p = _palette()
    w = max(30, _STATE["cols"])
    inner = w - 2
    left, right = " claume ", ""
    if _STATE["labels"]:
        try:
            left, right = _STATE["labels"]()
        except Exception:
            left, right = " claume ", ""
    lw, rw = _vis_len(left), _vis_len(right)
    if rw:
        fill = max(2, inner - lw - rw)
        top = (
            f"{p['accent']}╭{p['reset']}{p['muted']}{left}{'─' * fill}"
            f"{right}{p['reset']}{p['accent']}╮{p['reset']}"
        )
    else:
        pad = max(0, inner - lw)
        lpad = pad // 2
        top = (
            f"{p['accent']}╭{p['reset']}{p['muted']}{'─' * lpad}{left}"
            f"{'─' * (pad - lpad)}{p['reset']}{p['accent']}╮{p['reset']}"
        )
    bottom = f"{p['accent']}╰{'─' * inner}╯{p['reset']}"
    return top, bottom


def _input_row_text() -> Tuple[str, int]:
    """Build the input row string; returns (row, cursor_col_1based)."""
    p = _palette()
    w = max(30, _STATE["cols"])
    inner = w - 2
    prompt = _STATE.get("prompt") or ""
    plen = _vis_len(prompt)
    ed: Optional[_cb.Editor] = _STATE.get("ed")

    prefix = f"{p['muted']}│{p['reset']} "
    if ed is None:
        hint = BUSY_HINT if _STATE["busy"] else (_STATE["placeholder"] or "")
        body = f"\033[38;5;240m{hint[: inner - 3]}\033[0m" if hint else ""
        return prefix + body, 1

    indicator = ""
    if not ed.single_line:
        indicator = f"{DIM}⏎{ed.row + 1}{RESET} "
    line = "".join(ed.lines[ed.row])
    avail = max(4, inner - 2 - plen - _vis_len(indicator))
    # keep the cursor visible: slide the window when the text overflows
    start = 0
    if ed.col > avail:
        start = ed.col - avail
    before = line[start:ed.col]
    at_ch = line[ed.col: ed.col + 1] or " "
    after = line[ed.col + 1:]
    after = after[: max(0, avail - len(before))]

    tail = ""
    room = max(0, avail - len(before) - len(after))
    if not line:
        hint = BUSY_HINT if _STATE["busy"] else (_STATE["placeholder"] or "")
        if hint:
            tail = f"\033[38;5;240m{hint[:room]}\033[0m"
    elif ed.single_line and not ed.drop and ed.col >= len(line):
        g = ed.ghost()
        if g:
            tail = f"\033[38;5;240m{g[:room]}\033[0m"

    row = prefix + prompt + indicator + before + INVERT + at_ch + RESET + after + tail
    cursor_col = 3 + plen + _vis_len(indicator) + (ed.col - start)
    return row, cursor_col


def _write_input_row() -> None:
    """Redraw just the input row and park the cursor correctly."""
    with _lock:
        if not _STATE["pinned"]:
            return
        row, cursor_col = _input_row_text()
        input_abs = region_bottom() + 2
        o = _out()
        try:
            o.write(f"\x1b[{input_abs};1H\x1b[2K{row}")
            if _STATE.get("ed") is not None:
                o.write(f"\x1b[{input_abs};{min(cursor_col, _STATE['cols'])}H")
            else:
                o.write(f"\x1b[{region_bottom()};1H")
                _STATE["parked"] = True
            o.flush()
        except Exception:
            pass
        _STATE["parked"] = _STATE.get("ed") is None


def _draw_box() -> None:
    """Redraw all 6 box rows in place (absolute positions, no scroll)."""
    with _lock:
        if not _STATE["pinned"]:
            return
        cols, rows = _term()
        if rows > RESERVE + 8 and cols >= 30:
            if (cols, rows) != (_STATE["cols"], _STATE["rows"]):
                # terminal resized — re-pin to the new geometry
                _STATE.update(rows=rows, cols=cols)
                try:
                    _out().write(f"\x1b[1;{region_bottom()}r")
                    _out().flush()
                except Exception:
                    pass
        else:
            leave()
            return
        top, bottom = _border_rows()
        box_top = region_bottom() + 1
        input_abs = box_top + 1
        out = [HIDE_CURSOR, f"\x1b[{box_top};1H\x1b[2K{top}"]
        row_text, cursor_col = _input_row_text()
        out.append(f"\x1b[{input_abs};1H\x1b[2K{row_text}")
        ed: Optional[_cb.Editor] = _STATE.get("ed")
        opts = ed.drop[:3] if ed is not None else []
        p = _palette()
        for i in range(3):
            abs_row = input_abs + 1 + i
            if i < len(opts):
                mark = "❯ " if i == ed.drop_sel else "  "
                style = INVERT if i == ed.drop_sel else DIM
                label = (mark + opts[i])[: _STATE["cols"] - 4]
                out.append(f"\x1b[{abs_row};1H\x1b[2K{p['muted']}│{p['reset']} {style}{label}{RESET}")
            else:
                out.append(f"\x1b[{abs_row};1H\x1b[2K{p['muted']}│{p['reset']}")
        out.append(f"\x1b[{input_abs + 4};1H\x1b[2K{bottom}")
        if ed is not None:
            out.append(f"\x1b[{input_abs};{min(cursor_col, _STATE['cols'])}H{SHOW_CURSOR}")
            _STATE["parked"] = False
        else:
            out.append(f"\x1b[{region_bottom()};1H")
            _STATE["parked"] = True
        try:
            _out().write("".join(out))
            _out().flush()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# watcher: redraw after output bursts + live timer on the border
# ---------------------------------------------------------------------------
def _start_watcher() -> None:
    global _watcher
    if _watcher is not None and _watcher.is_alive():
        return

    def _loop() -> None:
        ticks = 0
        while _STATE["pinned"]:
            time.sleep(0.4)
            ticks += 1
            with _lock:
                if not _STATE["pinned"]:
                    break
                if (time.time() - _STATE["last_output"]) < 0.35:
                    continue  # output in flight — don't fight it
                if _STATE["dirty"]:
                    _STATE["dirty"] = False
                    _draw_box()
                elif ticks % 5 == 0 and _STATE["labels"]:
                    _draw_box()  # periodic timer refresh

    _watcher = threading.Thread(target=_loop, name="claume-pinbox", daemon=True)
    _watcher.start()


# ---------------------------------------------------------------------------
# interactive read (uses chatbox.Editor + key readers)
# ---------------------------------------------------------------------------
def read_line(
    prompt: str,
    busy: bool = False,
    placeholder: str = "",
    on_shift_tab: Optional[Callable[[], None]] = None,
    labels: Optional[Callable[[], Tuple[str, str]]] = None,
) -> str:
    """Read one line in the pinned box. Returns the submitted text
    (multi-line if Alt+Enter was used). Raises KeyboardInterrupt /
    EOFError like input(). Falls back to chatbox.read_line when the
    pin isn't available."""
    if not _STATE["pinned"] and not enter(labels):
        return _cb.read_line(
            prompt, on_shift_tab=on_shift_tab, placeholder=placeholder, busy=busy
        )

    _STATE["busy"] = busy
    _STATE["placeholder"] = placeholder
    _STATE["prompt"] = prompt
    ed = _cb.Editor(history=_cb.load_history())
    _STATE["ed"] = ed
    _draw_box()
    while True:
        try:
            if os.name == "nt":
                k = _cb.read_key_vt()
            else:
                k = _cb._read_key_posix()
        except KeyboardInterrupt:
            _STATE["ed"] = None
            prepare_output()
            raise
        result = ed.key(k)
        if k in (_cb.PASTE_START, _cb.PASTE_END):
            _draw_box()
            continue
        if k == "SHIFT+TAB" or result == "SHIFT+TAB":
            if on_shift_tab:
                prepare_output()
                on_shift_tab()
            _draw_box()
            continue
        if result == "INT":
            _STATE["ed"] = None
            prepare_output()
            raise KeyboardInterrupt
        if result == "EOF":
            _STATE["ed"] = None
            prepare_output()
            raise EOFError
        if result is not None:
            _STATE["ed"] = None
            finalize(result)
            return result
        _draw_box()
