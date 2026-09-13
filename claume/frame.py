"""claume frame — the structural REPL frame (status bar + skills panel).

Replicates the Freebuff-style thin layout in pure stdlib ANSI (no `rich`,
claume stays dependency-free):

* **Status rule bar** — an elastic full-width `━` divider with inverted
  label chips: workspace identity on the left, live session timer +
  interrupt hint on the right. Recomputed from the terminal width on every
  draw, so resizing the window re-flows it smoothly.
* **Injected System Skills panel** — the green-bordered container where
  Freebuff shows ads, claume shows *your* active engineering context:
  active skills, their instruction payloads, MCP servers and bridged tool
  counts, and the effort/mode knobs that guide every generation.
* **Placeholder row** — the input box shows a dimmed hint when empty
  ("Enter a coding task or / for commands"), replaced by real text as you
  type.

All functions return strings (or print via the ``out`` callable) so the
REPL can compose them with the chat box renderer.
"""
from __future__ import annotations

import os
import re
import shutil
import sys
import time
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Theme reuse: claume/ui owns the palette; import lazily to avoid cycles.
# ---------------------------------------------------------------------------
def _palette() -> Dict[str, str]:
    from . import ui as _ui

    return {
        "accent": _ui.ACCENT, "soft": _ui.SOFT, "text": _ui.TEXT,
        "muted": _ui.MUTED, "gold": _ui.GOLD, "red": _ui.RED,
        "reset": _ui.RESET, "bold": _ui.BOLD, "dim": _ui.DIM,
        "color": _ui.COLOR,
    }


def term_width() -> int:
    """Live terminal width (elastic re-flow on resize)."""
    try:
        return max(46, min(140, shutil.get_terminal_size().columns))
    except Exception:
        return 90


def _vis_len(s: str) -> int:
    """Visible length of a string containing ANSI escapes."""
    return len(re.sub(r"\033\[[0-9;]*m", "", s))


# ---------------------------------------------------------------------------
# Live data collectors — everything shown is REAL, never hardcoded
# ---------------------------------------------------------------------------
def _active_skills() -> List[Tuple[str, int, str]]:
    """[(name, approx injected chars, description), ...] for active skills.

    The bundled flagship (ui-ux-pro-max) is listed first so the compact
    panel always shows it; the rest follow alphabetically.
    """
    out: List[Tuple[str, int, str]] = []
    try:
        from . import skills as skillsmod

        for s in skillsmod.list_skills():
            if s.get("active"):
                doc = skillsmod.find_doc(skillsmod.skills_root() / s["name"])
                chars = 0
                if doc:
                    try:
                        chars = len(doc.read_text(encoding="utf-8", errors="replace"))
                    except Exception:
                        chars = 0
                out.append((s["name"], min(chars, skillsmod.PER_SKILL_CAP), s.get("desc", "")))
        flagship = tuple(getattr(skillsmod, "BUNDLED_SKILLS", ()))
        out.sort(key=lambda t: (0 if t[0] in flagship else 1, t[0]))
    except Exception:
        pass
    return out


def _mcp_summary() -> Tuple[int, int, List[str]]:
    """(enabled servers, bridged tool count, [names]) — no spawning."""
    try:
        from . import mcp as mcpmod

        servers = mcpmod.full_server_map()
        enabled = [n for n, spec in servers.items()
                   if isinstance(spec, dict) and spec.get("enabled", True)]
        from . import mcp as _m

        tools = sum(len(srv.list_tools()) for srv in _m._processes.values()
                    if srv is not None)
        return len(enabled), tools, enabled
    except Exception:
        return 0, 0, []


def _effort_budgets() -> Tuple[str, int, int]:
    """(effort, max_steps, max_tool_calls) from live config."""
    try:
        from . import config as cfgmod
        from .agent import EFFORT_BUDGETS

        cfg = cfgmod.Config()
        effort = cfg.effort
        steps, tools, _ = EFFORT_BUDGETS.get(effort, (24, 40, 5))
        return effort, int(cfg.get("max_steps", steps)), int(cfg.get("max_tool_calls_per_turn", tools))
    except Exception:
        return "balanced", 24, 40


def _system_prompt_tokens() -> int:
    """Approximate tokens injected into every generation (system prompt)."""
    try:
        from . import config as cfgmod
        from . import skills as skillsmod
        from .agent import EFFORT_BUDGETS

        cfg = cfgmod.Config()
        effort = cfg.effort
        steps, tools, _ = EFFORT_BUDGETS.get(effort, (24, 40, 5))
        injected = 900  # identity + react contract + workflow baseline
        for name, chars, _desc in _active_skills():
            injected += chars // 4
        servers, _tools, _names = _mcp_summary()
        injected += servers * 24
        injected += steps * 2 + tools
        return injected
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# Status rule bar — elastic, inverted label chips
# ---------------------------------------------------------------------------
def status_bar(
    left_label: str = "",
    timing_seconds: str = "",
    right_extra: str = "",
    out=None,
) -> str:
    """Full-width `━` rule with inverted chips: identity · timer · esc hint.

    Returns the string (and prints when ``out`` is given).
    """
    p = _palette()
    w = term_width()
    left = f" {left_label or 'worki · claume-code'} "
    right_bits = [b for b in (timing_seconds, right_extra or "■ Esc") if b]
    right = f" {'  '.join(right_bits)} "

    chip_l = _invert(left, p)
    chip_r = _invert(right, p)

    pad = max(1, w - _vis_len(chip_l) - _vis_len(chip_r) - 1)
    rule = "─" * pad
    line = f"{chip_l}{p['muted']}{rule}{p['reset']}{chip_r}"
    if out:
        out(line)
    return line


def _invert(text: str, p: Dict[str, str]) -> str:
    if not p["color"]:
        return text
    return f"\033[7m{text}\033[0m"


def _clean_desc(desc: str) -> str:
    """First readable phrase of a skill doc — strips markdown junk."""
    s = (desc or "").strip()
    for junk in (">", "-", "#", "*", "`", "!"):
        s = s.lstrip(junk).strip()
    s = s.splitlines()[0] if s else ""
    return s if len(s) > 8 and s[0].isalpha() else ""


# Segments: [(style_or_empty, plain_text), ...] — escapes never get cut.
Seg = Tuple[str, str]


def _row(segments: List[Seg], inner_w: int, p: Dict[str, str]) -> str:
    """Render one panel row: truncate the last segment cleanly, pad, border."""
    budget = inner_w - 2  # side padding
    total = sum(len(t) for _s, t in segments)
    if total > budget:
        # drop trailing segments until the last one can be cut cleanly
        while len(segments) > 1 and total - len(segments[-1][1]) + 1 > budget:
            total -= len(segments[-1][1])
            segments = segments[:-1]
        style, text = segments[-1]
        keep = max(0, budget - (total - len(text)))
        if keep == 0:
            segments = segments[:-1]
        else:
            segments = segments[:-1] + [(style, text[: max(0, keep - 1)] + "…")]
    body = "".join(f"{s}{t}{p['reset']}" if s else t for s, t in segments)
    pad = max(0, budget - sum(len(t) for _s, t in segments))
    return f"{p['accent']}│{p['reset']} {body}{' ' * pad} {p['accent']}│{p['reset']}"


# ---------------------------------------------------------------------------
# Injected System Skills panel — the claume replacement for the ad block
# ---------------------------------------------------------------------------
def skills_panel(out=None) -> str:
    """Green container showing what is actually injected into the agent."""
    p = _palette()
    w = term_width()
    inner_w = w - 4

    skills = _active_skills()
    servers, tool_count, names = _mcp_summary()
    effort, steps, tools = _effort_budgets()
    tokens = _system_prompt_tokens()

    rows: List[List[Seg]] = []
    if skills:
        # Compact panel: cap at 4 rows (+N more) so the frame never bleeds
        # down the screen regardless of how many skills are active.
        for name, chars, desc in skills[:4]:
            clean = _clean_desc(desc)
            seg: List[Seg] = [
                (p["soft"], f"⚡ {name}"),
                (p["muted"], f" · injected {chars // 4} instruction tokens"),
            ]
            if clean:
                seg.append((p["muted"], f" · {clean}"))
            rows.append(seg)
        if len(skills) > 4:
            rows.append([(p["muted"], f"  … +{len(skills) - 4} more active skill(s)")])
    else:
        rows.append([(p["muted"], "no skills active — /skill nextlevelbuilder/ui-ux-pro-max-skill")])
    if names:
        tool_txt = f"{tool_count} tool(s) bridged" if tool_count else "tools bridge on first use"
        shown = ", ".join(names[:2])
        extra = f" +{len(names) - 2}" if len(names) > 2 else ""
        rows.append([
            (p["text"], "⬡ mcp"),
            (p["muted"], f" · {servers} server(s) · {tool_txt} · {shown}{extra}"),
        ])
    rows.append([
        (p["gold"], f"✻ effort {effort}"),
        (p["muted"], f" · ≤{steps} steps · ≤{tools} tool calls/turn · system context ≈{tokens} tokens"),
    ])

    title = " Injected System Skills "
    top = f"{p['accent']}╭{'─' * (inner_w - len(title))}{'─' * len(title)}╮{p['reset']}"
    # title chip embedded in top border
    vis = _vis_len(title)
    top = f"{p['accent']}╭{title}{'─' * max(2, inner_w - vis)}╮{p['reset']}"
    rendered = [top]
    for seg in rows:
        rendered.append(_row(seg, inner_w, p))
    rendered.append(f"{p['accent']}╰{'─' * inner_w}╯{p['reset']}")
    block = "\n".join(rendered)
    if out:
        out(block)
    return block


# ---------------------------------------------------------------------------
# Input box helpers — placeholder row + borders for the chat box
# ---------------------------------------------------------------------------
PLACEHOLDER = "Enter a coding task or / for commands"


def input_placeholder() -> str:
    return f"\033[38;5;240m{PLACEHOLDER}\033[0m"


def chat_prompt_with_placeholder(prompt: str) -> str:
    """Prompt the chat box renders when the buffer is empty."""
    return prompt


def input_box_top_labeled(
    mode: str = "",
    session_label: str = "",
    right_label: str = "",
    width: Optional[int] = None,
) -> str:
    """Labeled top border: mode · session on the left, live timer right."""
    p = _palette()
    w = width or term_width()
    left = " claume "
    if mode:
        left = f" {mode} "
    if session_label:
        left += f"· {session_label} "
    inner = w - 2
    if right_label:
        right = f" {right_label} "
        fill = max(2, inner - len(left) - len(right))
        return (
            f"{p['accent']}╭{p['reset']}{p['muted']}{left}{'─' * fill}{right}{p['reset']}{p['accent']}╮{p['reset']}"
        )
    padded = left.center(inner, "─")
    return f"{p['accent']}╭{p['reset']}{p['muted']}{padded[:inner]}{p['reset']}{p['accent']}╮{p['reset']}"


def input_box_bottom_rule(width: Optional[int] = None) -> str:
    """Bottom border matching input_box_top_labeled's width."""
    p = _palette()
    w = width or term_width()
    return f"{p['accent']}╰{'─' * (w - 2)}╯{p['reset']}"


def render_frame(
    current_input_buffer: str = "",
    timing_seconds: str = "",
    mode: str = "manual",
    session_label: str = "",
) -> None:
    """One-shot frame draw (status bar + skills panel + input preview)."""
    def out(s: str) -> None:
        print(s)

    status_bar(f"worki · claume-code", timing_seconds, out=out)
    print()
    skills_panel(out=out)
    print()
    w = term_width()
    print(input_box_top_labeled(mode, session_label, width=w))
    if current_input_buffer:
        print(f"│ ❯ {current_input_buffer}")
    else:
        print(f"│ ❯ {input_placeholder()}")
    print(f"╰{'─' * (w - 2)}╯")
