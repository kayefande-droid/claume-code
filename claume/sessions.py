"""Session persistence for claume-code.

Every conversation is stored as JSON under ~/.claume/sessions/<id>.json,
one file per session. Supports autosave after every turn, resuming the
most recent session (claume --continue), and picking one interactively
(/resume). Mirrors Claude Code's session model.
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import config

# Kept small so replayed history doesn't eat the context window.
MAX_MSG_CONTENT = 16_000
MAX_MESSAGES = 400


def _sessions_dir() -> Path:
    d = config.sessions_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


def new_session_id() -> str:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-{uuid.uuid4().hex[:6]}"


def _sanitize_history(history: List[Dict[str, str]]) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for m in history:
        role = m.get("role", "user")
        content = str(m.get("content", ""))[:MAX_MSG_CONTENT]
        out.append({"role": role, "content": content})
    return out[-MAX_MESSAGES:]


def save_session(
    session_id: str,
    history: List[Dict[str, str]],
    meta: Optional[Dict[str, Any]] = None,
) -> Path:
    """Write/overwrite the session file. Returns the path."""
    payload = {
        "id": session_id,
        "updated": time.time(),
        "meta": meta or {},
        "messages": _sanitize_history(history),
    }
    path = _sessions_dir() / f"{session_id}.json"
    path.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    return path


def load_session(session_id: str) -> Optional[Dict[str, Any]]:
    path = _sessions_dir() / f"{session_id}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or "messages" not in data:
            return None
        return data
    except Exception:
        return None


def list_sessions(limit: int = 20) -> List[Dict[str, Any]]:
    """Most recent sessions first: [{id, updated, title, turns}]."""
    d = _sessions_dir()
    entries: List[Dict[str, Any]] = []
    for p in d.glob("*.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            msgs = data.get("messages", [])
            first_user = next(
                (m["content"] for m in msgs if m.get("role") == "user" and not m["content"].startswith(("OBSERVATION", "SYSTEM", "Project instructions"))),
                "(no prompt)",
            )
            title = " ".join(first_user.split())[:64]
            entries.append(
                {
                    "id": data.get("id", p.stem),
                    "updated": data.get("updated", p.stat().st_mtime),
                    "title": title,
                    "turns": sum(1 for m in msgs if m.get("role") == "user" and not m["content"].startswith(("OBSERVATION", "SYSTEM"))),
                }
            )
        except Exception:
            continue
    entries.sort(key=lambda e: e["updated"], reverse=True)
    return entries[:limit]


def latest_session_id(exclude: Optional[str] = None) -> Optional[str]:
    sessions = list_sessions(limit=10)
    for s in sessions:
        if exclude and s["id"] == exclude:
            continue
        return s["id"]
    return None


def prune_sessions(max_keep: int = 30) -> int:
    """Delete oldest sessions beyond max_keep. Returns deleted count."""
    sessions = list_sessions(limit=10_000)
    removed = 0
    for s in sessions[max_keep:]:
        try:
            (_sessions_dir() / f"{s['id']}.json").unlink()
            removed += 1
        except Exception:
            continue
    return removed


def start_new() -> str:
    sid = new_session_id()
    save_session(sid, [])
    return sid
