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
    except Exception:
        # Near-miss JSON: trailing commas, single quotes...
        obj = repair_json(snippet)
        if obj is None:
            # Broken big write: LLMs stuffing a whole HTML file into
            # args.content routinely emit raw newlines / unescaped quotes
            # and shred the envelope. Reconstruct the tool call from the
            # raw text instead of failing the turn.
            salvaged = salvage_write(snippet)
            if salvaged is not None:
                result.thought = "(recovered a file write from a broken JSON envelope)"
                result.action = salvaged
                return result
            result.error = f"invalid JSON envelope"
            return result

    result.thought = str(obj.get("thought", ""))

    # Some providers surface explicit reasoning in a dedicated field
    # (reasoning_content / reasoning). When present, fold it into the
    # thought channel so the user sees the reasoning path, not just the
    # final text. Never prefer it over a real 'thought' the model wrote.
    reasoning = obj.get("reasoning_content") or obj.get("reasoning") or ""
    if isinstance(reasoning, str) and reasoning.strip() and not result.thought:
        result.thought = reasoning.strip()[:1200]

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


_WRITE_TOOLS = {"write_file", "create_file", "edit_file", "write", "save_file"}
_TOOL_NAME_RE = re.compile(r'"tool"\s*:\s*"([a-zA-Z0-9_]+)"')
_CONTENT_KEY_RE = re.compile(r'"content"\s*:\s*"', re.DOTALL)
_PATH_KEY_RE = re.compile(r'"(?:path|file_path|filename|file)"\s*:\s*"([^"]*)"')


def _json_unescape(raw: str) -> str:
    """Unescape the JSON escape sequences the model DID emit correctly
    (\\n, \\", \\\\, \\uXXXX); leave raw control characters (the broken
    part) untouched so they land in the file as real newlines."""
    out: list = []
    i = 0
    n = len(raw)
    while i < n:
        ch = raw[i]
        if ch == "\\" and i + 1 < n:
            nxt = raw[i + 1]
            simple = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f"}
            if nxt in simple:
                out.append(simple[nxt])
                i += 2
                continue
            if nxt == "u" and i + 6 <= n:
                try:
                    out.append(chr(int(raw[i + 2:i + 6], 16)))
                    i += 6
                    continue
                except ValueError:
                    pass
        out.append(ch)
        i += 1
    return "".join(out)


def salvage_write(snippet: str) -> Optional[Action]:
    """Reconstruct a write action from a shredded JSON envelope.

    Pattern: ``{"tool": "write_file", "args": {"path": "index.html",
    "content": "<!DOCTYPE html> ... </html>"}}`` where the content
    contains raw newlines/unescaped quotes. We take the tool name, the
    path and everything between the opening quote of ``content`` and the
    LAST quote of the snippet (which must be followed only by envelope
    punctuation) as the literal file body.
    """
    tool_m = _TOOL_NAME_RE.search(snippet)
    content_m = _CONTENT_KEY_RE.search(snippet)
    if not tool_m or not content_m:
        return None
    tool = tool_m.group(1)
    if tool not in _WRITE_TOOLS:
        return None

    end = snippet.rfind('"')
    if end <= content_m.end():
        return None
    tail = snippet[end + 1:]
    if tail.strip("}] \t\r\n,\"'") != "":
        # text after the final quote means the last quote is NOT the
        # content terminator (model appended prose/other fields)
        return None

    raw = snippet[content_m.end():end]
    if not raw.strip():
        return None

    args: Dict[str, Any] = {"content": _json_unescape(raw)}
    path_m = _PATH_KEY_RE.search(snippet[: content_m.start()])
    if path_m:
        args["path"] = path_m.group(1)
    return Action(tool=tool, args=args)
