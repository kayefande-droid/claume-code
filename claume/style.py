"""claume style — visual grammar distinguishing the three conversation
channels: THOUGHT, USER, ANSWER.

Each channel has a distinct left rail glyph, weight, color, indent and
spacing so the eye can parse the transcript at a glance:

    ◇ thinking    condensed italic violet, indented, tight spacing
    ❯ you         bright accent bold, no indent, blank line before
    ◆ claume      solid accent bold rail, indented body, blank line after

Helper ``render_channel()`` is the single place that formats these, and
``wrap()`` provides terminal-width aware wrapping with hanging indents.
"""
from __future__ import annotations

import os
import shutil
import textwrap
from typing import List, Optional

from .ui import ACCENT, BOLD, DIM, GREY, ITALIC, MUTED, PURPLE, RESET, SILVER

# ---------------------------------------------------------------------------
# channel definitions
# ---------------------------------------------------------------------------
GLYPHS = {
    "thought": "◇",
    "user": "❯",
    "answer": "◆",
}
LABELS = {
    "thought": "thinking",
    "user": "you",
    "answer": "claume",
}
COLORS = {
    "thought": PURPLE,
    "user": ACCENT,
    "answer": ACCENT,
}


def term_width() -> int:
    try:
        return max(46, min(120, shutil.get_terminal_size().columns))
    except Exception:
        return 90


def wrap(text: str, width: Optional[int] = None, indent: int = 4) -> List[str]:
    """Word-wrap to terminal width with a hanging indent for continuation
    lines. ANSI-aware enough: wraps on plain text only (style prefixes
    are added by the caller after wrapping)."""
    width = width or term_width()
    usable = max(30, width - indent - 1)
    out: List[str] = []
    for para in str(text).split("\n"):
        if not para.strip():
            out.append("")
            continue
        out.extend(
            textwrap.wrap(
                para, width=usable, break_long_words=False, break_on_hyphens=False
            ) or [""]
        )
    return out


def header(channel: str, note: str = "") -> str:
    """Styled channel header line, e.g.  ◇ thinking · 3.2s"""
    color = COLORS.get(channel, "")
    glyph = GLYPHS.get(channel, "·")
    label = LABELS.get(channel, channel)
    head = f"{color}{BOLD}{glyph} {label}{RESET}"
    if note:
        head += f" {GREY}· {note}{RESET}"
    return head


def render_channel(
    channel: str,
    text: str,
    note: str = "",
    width: Optional[int] = None,
) -> str:
    """Full multi-line channel block with header, hanging indent, weight
    and spacing baked in."""
    color = COLORS.get(channel, "")
    body_color = SILVER if channel == "user" else ""
    body_weight = DIM + ITALIC if channel == "thought" else ""
    # thought: deep indent (reasoning happens *inside* the answer)
    # user: flush-left (it's the human speaking)
    # answer: mid indent (the product)
    indent = {"thought": 6, "user": 1, "answer": 4}.get(channel, 4)
    lines = wrap(text, width=width, indent=indent)
    block = [header(channel, note)]
    for i, line in enumerate(lines):
        pad = " " * indent
        body = f"{body_color}{body_weight}{line}{RESET}" if (body_color or body_weight) else line
        block.append(f"{pad}{body}" if line else "")
    return "\n".join(block)


def blank_before(channel: str) -> bool:
    """Extra breathing room before a block of this channel."""
    return channel in ("user", "answer")


def blank_after(channel: str) -> bool:
    return channel == "answer"
