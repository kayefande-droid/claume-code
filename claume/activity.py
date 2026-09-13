"""Session activity log for claume-code.

Every tool call, file touched, command run, MCP tool used and commit is
recorded per session in ``~/.claume/sessions/<id>.activity.json``.
``/sessions`` reads these logs so you can see exactly what claume was
*doing* in a session — not just the first prompt.

The log is best-effort: failures never break a running task.
"""
from __future__ import annotations

import json
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import config

_lock = threading.Lock()


def _path(session_id: str) -> Path:
    return config.sessions_dir() / f"{session_id}.activity.json"


def _load(session_id: str) -> Dict[str, Any]:
    try:
        if _path(session_id).exists():
            data = json.loads(_path(session_id).read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {"session": session_id, "actions": []}


def record(
    session_id: str,
    kind: str,
    tool: str = "",
    target: str = "",
    ok: bool = True,
    detail: str = "",
) -> None:
    """Append one action to the session's activity log (thread-safe)."""
    if not session_id:
        return
    try:
        with _lock:
            data = _load(session_id)
            data["actions"].append(
                {
                    "t": time.time(),
                    "kind": kind,       # tool | file | command | mcp | git | web | design
                    "tool": tool,
                    "target": str(target)[:160],
                    "ok": bool(ok),
                    "detail": str(detail)[:200],
                }
            )
            # Hard cap so sessions with huge builds don't balloon.
            if len(data["actions"]) > 2000:
                data["actions"] = data["actions"][-2000:]
            data["updated"] = time.time()
            _path(session_id).write_text(
                json.dumps(data, indent=1), encoding="utf-8"
            )
    except Exception:
        pass


def summary(session_id: str, max_lines: int = 6) -> str:
    """One-line-per-kind digest of what happened in a session."""
    data = _load(session_id)
    actions: List[Dict[str, Any]] = data.get("actions", [])
    if not actions:
        return ""
    files: List[str] = []
    cmds = 0
    mcp: List[str] = []
    web = 0
    git = 0
    for a in actions:
        kind = a.get("kind", "")
        if kind == "file":
            t = a.get("target", "")
            if t and t not in files:
                files.append(t)
        elif kind == "command":
            cmds += 1
        elif kind == "mcp":
            t = a.get("tool", "")
            if t and t not in mcp:
                mcp.append(t)
        elif kind == "web":
            web += 1
        elif kind == "git":
            git += 1
    parts: List[str] = []
    if files:
        shown = ", ".join(Path(f).name for f in files[:4])
        extra = f" +{len(files) - 4}" if len(files) > 4 else ""
        parts.append(f"{len(files)} file(s): {shown}{extra}")
    if mcp:
        parts.append("MCP " + ", ".join(m.split("_", 2)[-1][:24] for m in mcp[:3]))
    if cmds:
        parts.append(f"{cmds} command(s)")
    if web:
        parts.append(f"{web} web call(s)")
    if git:
        parts.append(f"{git} git op(s)")
    if not parts:
        parts.append(f"{len(actions)} action(s)")
    return " · ".join(parts)


def stats(session_id: str) -> Dict[str, int]:
    """Action kind counts for one session."""
    data = _load(session_id)
    return dict(Counter(a.get("kind", "?") for a in data.get("actions", [])))
