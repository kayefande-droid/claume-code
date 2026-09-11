"""Parse model output into structured actions.

The model is instructed to reply with a strict JSON envelope. Real
models sometimes wrap JSON in prose or markdown fences, so the parser
is deliberately forgiving:

    {"thought": "...", "action": {"tool": "write_file", "args": {...}}, "final": "..."}

* ``thought`` — reasoning step (displayed, not executed)
* ``action``  — a tool call; ``tool`` must exist in the registry
* ``final``   — when present, the turn is over and this is the answer
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class Action:
    tool: str
    args: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ParsedTurn:
    thought: str = ""
    action: Optional[Action] = None
    final: Optional[str] = None
    raw: str = ""
    error: Optional[str] = None


_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_OBJ_RE = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json(text: str) -> Optional[str]:
    text = text.strip()
    # 1) fenced block
    match = _FENCE_RE.search(text)
    if match:
        return match.group(1)
    # 2) bare object
    match = _OBJ_RE.search(text)
    if match:
        return match.group(0)
    return None


def parse_turn(text: str) -> ParsedTurn:
    result = ParsedTurn(raw=text)
    snippet = _extract_json(text)
    if not snippet:
        result.error = "no JSON object found in model output"
        return result

    try:
        obj = json.loads(snippet)
        if not isinstance(obj, dict):
            raise ValueError("JSON envelope is not an object")
    except Exception as exc:
        result.error = f"invalid JSON envelope: {exc}"
        return result

    result.thought = str(obj.get("thought", ""))

    if obj.get("final"):
        result.final = str(obj["final"])
        return result

    action_obj = obj.get("action")
    if isinstance(action_obj, dict) and action_obj.get("tool"):
        result.action = Action(
            tool=str(action_obj["tool"]),
            args=action_obj.get("args") or {},
        )
    else:
        result.error = "envelope had neither 'final' nor a valid 'action.tool'"
    return result


def repair_json(text: str) -> Optional[Dict[str, Any]]:
    """Last-ditch fixes for near-miss JSON (trailing commas, single quotes)."""
    snippet = _extract_json(text)
    if not snippet:
        return None
    candidates = [
        snippet,
        re.sub(r",\s*([}\]])", r"\1", snippet),  # trailing commas
        snippet.replace("'", '"'),
    ]
    for candidate in candidates:
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                return obj
        except Exception:
            continue
    return None
