"""Session persistence for claume-code.

Every conversation is stored as JSON under ~/.claume/sessions/<id>.json,
one file per session. Sessions carry a **project name** and human
timestamps so you can tell them apart (claume --continue, /resume, and
/resume-list all show name + time). Sessions can be renamed with
/rename. Mirrors Claude Code's session model, plus names.
"""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime
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


def default_project_name() -> str:
    """Sessions default to the current folder's name as their project."""
    try:
        return Path.cwd().name or "default"
    except Exception:
        return "default"


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
    existing: Dict[str, Any] = {}
    path = _sessions_dir() / f"{session_id}.json"
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            existing = {}
    # Preserve naming fields set by /rename unless meta overrides them.
    meta = meta or {}
    project = meta.get("project") or existing.get("project") or default_project_name()
    name = meta.get("name") or existing.get("name") or ""
    payload = {
        "id": session_id,
        "created": existing.get("created", time.time()),
        "updated": time.time(),
        "project": project,
        "name": name,
        "meta": meta or {},
        "messages": _sanitize_history(history),
    }
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


def rename_session(session_id: str, project: str = "", name: str = "") -> bool:
    """Set the project name and/or the display name of a session."""
    data = load_session(session_id)
    if not data:
        return False
    if project:
        data["project"] = project
    if name:
        data["name"] = name
    data["updated"] = time.time()
    path = _sessions_dir() / f"{session_id}.json"
    path.write_text(json.dumps(data, indent=1), encoding="utf-8")
    return True


def _fmt_time(ts: float) -> str:
    """'12 Sep · 14:32' style stamp (year only when it differs)."""
    try:
        dt = datetime.fromtimestamp(ts)
        if dt.year == datetime.now().year:
            return dt.strftime("%d %b · %H:%M")
        return dt.strftime("%d %b %Y · %H:%M")
    except Exception:
        return "?"


def list_sessions(limit: int = 20) -> List[Dict[str, Any]]:
    """Most recent sessions first.

    Each entry: {id, updated, project, name, title, turns, when, age}.
    """
    d = _sessions_dir()
    entries: List[Dict[str, Any]] = []
    for p in d.glob("*.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            msgs = data.get("messages", [])
            first_user = next(
                (
                    m["content"]
                    for m in msgs
                    if m.get("role") == "user"
                    and not m["content"].startswith(("OBSERVATION", "SYSTEM", "Project instructions", "DESIGN PIPELINE"))
                ),
                "(no prompt)",
            )
            title = " ".join(first_user.split())[:56]
            updated = data.get("updated", p.stat().st_mtime)
            project = data.get("project") or "(no project)"
            name = data.get("name") or ""
            entries.append(
                {
                    "id": data.get("id", p.stem),
                    "updated": updated,
                    "when": _fmt_time(updated),
                    "project": project,
                    "name": name,
                    "title": title,
                    "turns": sum(
                        1
                        for m in msgs
                        if m.get("role") == "user"
                        and not m["content"].startswith(("OBSERVATION", "SYSTEM"))
                    ),
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


def start_new(project: Optional[str] = None) -> str:
    sid = new_session_id()
    save_session(sid, [], meta={"project": project or default_project_name()})
    return sid
