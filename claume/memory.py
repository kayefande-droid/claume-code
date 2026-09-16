"""claume memory — persistent file-based working memory (v3).

Transposed from the Claude Fable 5 system prompt (memory_filesystem +
MEMORY.md index, leaked in skills/system-prompts-leaks) and adapted to
claume's zero-dependency, ~/.claume-based architecture.

Every memory is one markdown file in ~/.claume/memory/ holding ONE durable
fact, with frontmatter:

    ---
    name: <short-kebab-case-slug>
    description: <one-line summary used for recall relevance>
    type: user | feedback | project | reference
    ---

    <the fact; feedback/project memories add **Why:** and **How to apply:**
    lines. Related memories link with [[their-name]].>

MEMORY.md is the index — one line per memory, loaded into the agent's
system context each session so claume "remembers" across sessions without
re-reading every file.

What belongs here (Fable's calibration, kept):
* user      — who the user is: stack, tastes, hard constraints
* feedback  — corrections and confirmed approaches, WITH the why
* project   — goals/decisions not derivable from the code or git history
* reference — URLs, dashboards, tickets

What never belongs: what the repo already records (structure, past fixes),
or anything that only matters to the current conversation.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import config

INDEX_NAME = "MEMORY.md"
MAX_MEMORIES_IN_CONTEXT = 30
MAX_INDEX_LINE_CHARS = 110

_MEMORY_TYPES = ("user", "feedback", "project", "reference")


def memory_dir() -> Path:
    d = config.claume_dir() / "memory"
    d.mkdir(parents=True, exist_ok=True)
    return d


def index_path() -> Path:
    return memory_dir() / INDEX_NAME


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", (name or "").strip().lower()).strip("-")
    return slug or f"memory-{int(date.today().strftime('%Y%m%d'))}"


def _parse_frontmatter(text: str) -> Tuple[Dict[str, str], str]:
    meta: Dict[str, str] = {}
    body = text
    if text.startswith("---"):
        parts = text.split("\n---", 2)
        if len(parts) >= 2:
            for line in parts[0][3:].splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip().lower()] = v.strip()
            body = parts[1].lstrip("-\n") + (parts[2] if len(parts) > 2 else "")
    return meta, body.strip()


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------
def save_memory(name: str, fact: str, mtype: str = "project",
                description: str = "") -> str:
    """Write one memory file + index line. Returns a human status."""
    slug = _slug(name)
    if mtype not in _MEMORY_TYPES:
        mtype = "project"
    desc = (description or " ".join(fact.split())[:80]).strip()
    path = memory_dir() / f"{slug}.md"
    body = fact.strip()
    if mtype in ("feedback", "project") and "**Why:**" not in body:
        body += "\n\n**Why:** (add the reason this matters)\n**How to apply:** (add when/how to use it)"
    content = (
        f"---\nname: {slug}\ndescription: {desc}\n"
        f"type: {mtype}\nsaved: {date.today().isoformat()}\n---\n\n{body}\n"
    )
    path.write_text(content, encoding="utf-8")
    _upsert_index_line(slug, desc)
    return f"memory '{slug}' saved ({mtype})"


def read_memory(name: str) -> str:
    slug = _slug(name)
    path = memory_dir() / f"{slug}.md"
    if not path.exists():
        # fuzzy: unique prefix match
        matches = [p for p in memory_dir().glob("*.md")
                   if p.stem.startswith(slug)]
        if len(matches) == 1:
            path = matches[0]
        elif matches:
            return "ambiguous memory — matches: " + ", ".join(p.stem for p in matches[:6])
        else:
            return f"no memory named '{slug}'"
    return path.read_text(encoding="utf-8", errors="replace")


def forget_memory(name: str) -> str:
    slug = _slug(name)
    path = memory_dir() / f"{slug}.md"
    if not path.exists():
        return f"no memory named '{slug}'"
    path.unlink()
    _remove_index_line(slug)
    return f"memory '{slug}' deleted"


def list_memories() -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for p in sorted(memory_dir().glob("*.md")):
        if p.name == INDEX_NAME:
            continue
        meta, _ = _parse_frontmatter(p.read_text(encoding="utf-8", errors="replace"))
        out.append({
            "name": p.stem,
            "type": meta.get("type", "project"),
            "description": meta.get("description", "")[:90],
        })
    return out


# ---------------------------------------------------------------------------
# Index (MEMORY.md) — the context-loaded line-per-memory file
# ---------------------------------------------------------------------------
def _index_lines() -> List[str]:
    p = index_path()
    if not p.exists():
        return []
    return [ln for ln in p.read_text(encoding="utf-8", errors="replace").splitlines()
            if ln.strip().startswith("- [")]


def _upsert_index_line(slug: str, desc: str) -> None:
    lines = [ln for ln in _index_lines() if f"]({slug}.md)" not in ln]
    hook = desc[:MAX_INDEX_LINE_CHARS]
    lines.append(f"- [{slug}]({slug}.md) — {hook}")
    lines.sort(key=lambda s: s.lower())
    index_path().write_text(
        "# claume memory index\n\n"
        "One line per memory. Full files sit beside this index in "
        "~/.claume/memory/ — read one before acting on its hint.\n\n"
        + "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def _remove_index_line(slug: str) -> None:
    lines = [ln for ln in _index_lines() if f"]({slug}.md)" not in ln]
    index_path().write_text(
        "# claume memory index\n\n" + "\n".join(lines) + ("\n" if lines else ""),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# System-prompt injection — the Fable-style recall block
# ---------------------------------------------------------------------------
def memory_block(max_chars: int = 2_400) -> str:
    """Index + recall instructions injected into the system prompt."""
    lines = _index_lines()[:MAX_MEMORIES_IN_CONTEXT]
    listing = "\n".join(lines) if lines else "(empty — nothing remembered yet)"
    block = (
        "## Persistent memory (Fable-style recall)\n\n"
        "You keep durable working memory in files at ~/.claume/memory/ "
        "(tools: memory_save, memory_read, memory_list, memory_forget). "
        "MEMORY.md is the index:\n\n"
        f"{listing}\n\n"
        "Recall rules (transposed from Claude Fable 5):\n"
        "* Before asking the user for context they may have given before — "
        "their stack, preferences, project goals — check the index above. "
        "Asking for something already remembered wastes their time.\n"
        "* The index is a HINT, not the content: when a line looks "
        "relevant, memory_read that file before acting on it.\n"
        "* When the user shares a durable fact (a preference, a correction, "
        "a project constraint) that the repo does not already record, save "
        "it with memory_save — type user/feedback/project/reference. "
        "Feedback memories must include the **Why:**.\n"
        "* Never save what the code/git history already shows, or anything "
        "that only matters to the current conversation.\n"
        "* Recalled memory reflects what was true when written — verify a "
        "named file/flag still exists before relying on it.\n"
    )
    return block[:max_chars]
