"""HTTP+MCP client for claume-code: stdio JSON-RPC + HTTP+SSE transport to MCP agents.

v2: adds an HTTP transport so MCP "servers" can be composable API agents
(21st.dev/web agents, design MCP endpoints, anything that speaks an
OpenAI-compatible chat endpoint with tool results), not just stdio servers.

The stdio path is unchanged from the original MCP client (the Link System
still talks to local npx servers via JSON-RPC). The HTTP path lets claume
fire a tool invocation at a remote agent endpoint and get the text result
back — which is how the 21st.dev design discovery works once you point it
at a composable agent URL instead of a local process.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import config as _cfg
from . import keyvault

# ---------------------------------------------------------------------------
# npm resolution (unchanged from the original MCP client)
# ---------------------------------------------------------------------------
DESIGN_STACK: Dict[str, Dict[str, Any]] = {
    "uidiscovery-21st": {
        "command": "npx",
        "args": ["-y", "@21st-dev/magic"],
        "description": "Searches/fetches verified human-written design blocks and components (21st.dev).",
        "needs_key": "TWENTY_FIRST_API_KEY",
    },
    "microinteractions-reactbits": {
        "command": "npx",
        "args": ["reactbits-dev-mcp-server"],
        "description": "Fluid canvas shaders and kinetic typography (reactbits).",
    },
    "animation-motion": {
        "command": "node",
        "args": [],  # resolved from ~/.claume/mcp/npm on first use
        "description": "Framer Motion timelines (motion.dev).",
        "needs_key": "",
    },
    "atomic-shadcnspace": {
        "command": "npx",
        "args": ["shadcnspace-mcp"],
        "description": "Standard layout tokens, dashboard wireframes, valid TypeScript props.",
    },
}

PRESETS: Dict[str, Dict[str, Dict[str, Any]]] = {
    "design": DESIGN_STACK,
}

_LINK_TIMEOUT = 90
_INITIALIZ_TIMEOUT = 75

_npm_lock = threading.Lock()
_npm_installed: set = set()


def _npm_cache_dir() -> Path:
    d = _cfg.mcp_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / "npx-cache").mkdir(parents=True, exist_ok=True)
    return d


def _npm_root() -> Path:
    d = _npm_cache_dir() / "npm"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _spec_package_name(npm_spec: str) -> str:
    spec = npm_spec.strip()
    if spec.startswith("@"):
        return "@" + spec[1:].split("@")[0]
    return spec.split("@")[0]


def _find_npm_bin(npm_spec: str) -> Optional[Path]:
    pkg_dir = _npm_root() / "node_modules" / _spec_package_name(npm_spec)
    pj = pkg_dir / "package.json"
    if not pj.exists():
        return None
    try:
        meta = json.loads(pj.read_text(encoding="utf-8"))
    except Exception:
        return None
    rel = ""
    bin_field = meta.get("bin")
    if isinstance(bin_field, dict) and bin_field:
        name = _spec_package_name(npm_spec)
        rel = bin_field.get(name) or next(iter(bin_field.values()))
    elif isinstance(bin_field, str):
        rel = bin_field
    rel = rel or str(meta.get("main") or "")
    if not rel:
        return None
    script = (pkg_dir / rel).resolve()
    return script if script.exists() else None


def _run_npm_install(npm_spec: str, timeout: int = 300) -> bool:
    npm = shutil.which("npm")
    if not npm:
        return False
    cmd_list = [npm, "install", "--prefix", str(_npm_root()), npm_spec,
                "--no-audit", "--no-fund", "--loglevel=error"]
    if os.name == "nt" and npm.lower().endswith((".cmd", ".bat")):
        cmd_list = ["cmd.exe", "/c"] + cmd_list
    env = os.environ.copy()
    env["npm_config_cache"] = str(_npm_cache_dir() / "npx-cache")
    try:
        proc = subprocess.run(
            cmd_list, capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace", env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return proc.returncode == 0
    except Exception:
        return False


def ensure_npm_server(name: str, spec: Dict[str, Any]) -> Tuple[str, List[str]]:
    """npx-style spec -> node <script> under ~/.claume/mcp/npm."""
    command = str(spec.get("command", ""))
    args = [str(a) for a in spec.get("args", [])]
    if command not in ("npx", "npm") or not args:
        return command, args
    npm_spec = ""
    rest: List[str] = []
    for i, a in enumerate(args):
        if a.startswith("-"):
            continue
        npm_spec = a
        rest = args[i + 1:]
        break
    if not npm_spec:
        return command, args
    key = f"{name}:{npm_spec}"
    with _npm_lock:
        script = _find_npm_bin(npm_spec)
        if script is None and key not in _npm_installed:
            _run_npm_install(npm_spec)
            script = _find_npm_bin(npm_spec)
            _npm_installed.add(key)
    if script is not None:
        return "node", [str(script)] + rest
    return command, args


class MCPError(Exception):
    pass


# ---------------------------------------------------------------------------
# Stdio MCPServer (original, lightly hardened)
# ---------------------------------------------------------------------------
class MCPServer:
    def __init__(self, name: str, spec: Dict[str, Any]) -> None:
        self.name = name
        self.spec = spec if isinstance(spec, dict) else {}
        try:
            resolved_cmd, resolved_args = ensure_npm_server(name, self.spec)
        except Exception:
            resolved_cmd, resolved_args = str(spec.get("command", "")), [str(a) for a in spec.get("args", [])]
        self.command = resolved_cmd
        self.args = resolved_args
        self.description = str(spec.get("description", ""))
        self.enabled = bool(spec.get("enabled", True))
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._next_id = 1
        self._tools: List[Dict[str, Any]] = []
        self._warmed = False

    def _start(self) -> None:
        if self._proc and self._proc.poll() is None:
            return
        cmd_list: List[str] = [self.command] + self.args
        try:
            resolved = shutil.which(self.command)
        except Exception:
            resolved = None
        if resolved:
            if os.name == "nt" and resolved.lower().endswith((".cmd", ".bat")):
                cmd_list = ["cmd.exe", "/c", resolved] + self.args
            else:
                cmd_list = [resolved] + self.args
        env = os.environ.copy()
        npm_root = _npm_cache_dir()
        env["npm_config_cache"] = str(npm_root / "npx-cache")
        env["npm_config_prefix"] = str(npm_root)
        env.setdefault("npm_config_update_notifier", "false")
        extra_env = self.spec.get("env") if isinstance(self.spec, dict) else None
        if isinstance(extra_env, dict):
            for k, v in extra_env.items():
                if isinstance(v, str) and not v.startswith("<"):
                    env[k] = v
        needs_key = self.spec.get("needs_key") if isinstance(self.spec, dict) else None
        if needs_key:
            try:
                val = keyvault.resolve_key(str(needs_key))
                if val:
                    env[str(needs_key)] = val
                    env.setdefault("API_KEY_21ST", val)
            except Exception:
                pass
        try:
            self._proc = subprocess.Popen(
                cmd_list,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                shell=False,
                env=env,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except FileNotFoundError:
            raise MCPError(f"cannot spawn '{self.command}' — is it installed and on PATH?")

    def _stop(self) -> None:
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=5)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
        self._proc = None
        self._tools = []
        self._warmed = False

    def _rpc(self, method: str, params: Optional[Dict[str, Any]] = None, timeout: int = _LINK_TIMEOUT) -> Any:
        if not self.enabled:
            raise MCPError(f"server '{self.name}' is disabled")
        self._start()
        assert self._proc is not None and self._proc.stdin and self._proc.stdout
        with self._lock:
            req_id = self._next_id
            self._next_id += 1
            payload = {"jsonrpc": "2.0", "id": req_id, "method": method}
            if params is not None:
                payload["params"] = params
            try:
                self._proc.stdin.write(json.dumps(payload) + "\n")
                self._proc.stdin.flush()
            except Exception as exc:
                self._stop()
                raise MCPError(f"failed to write to '{self.name}': {exc}")

            result_holder: Dict[str, Any] = {}

            def _read() -> None:
                try:
                    for line in self._proc.stdout:  # type: ignore[union-attr]
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            msg = json.loads(line)
                        except Exception:
                            continue
                        if isinstance(msg, dict) and msg.get("id") == req_id:
                            result_holder["msg"] = msg
                            return
                except Exception:
                    pass

            reader = threading.Thread(target=_read, daemon=True)
            reader.start()
            reader.join(timeout=timeout)
            if "msg" not in result_holder:
                raise MCPError(f"'{self.name}' timed out after {timeout}s on {method}")
            msg = result_holder["msg"]
            if "error" in msg:
                raise MCPError(f"'{self.name}' error: {msg['error']}")
            return msg.get("result")

    def initialize(self) -> bool:
        try:
            self._rpc("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "claume-code", "version": "2.0.0"},
            }, timeout=_INITIALIZ_TIMEOUT)
            try:
                assert self._proc is not None and self._proc.stdin
                note = {"jsonrpc": "2.0", "method": "notifications/initialized"}
                self._proc.stdin.write(json.dumps(note) + "\n")
                self._proc.stdin.flush()
            except Exception:
                pass
            self._warmed = True
            return True
        except MCPError as exc:
            if "Not authenticated" in str(exc) or "api key" in str(exc).lower():
                needs = self.spec.get("needs_key")
                hint = f" — run /key {needs} with a key from the server's site" if needs else ""
                raise MCPError(f"'{self.name}' requires an API key{hint}") from exc
            return False

    def list_tools(self) -> List[Dict[str, Any]]:
        if self._tools:
            return self._tools
        result = self._rpc("tools/list", {})
        self._tools = list(result.get("tools", [])) if isinstance(result, dict) else []
        return self._tools

    def call_tool(self, tool: str, args: Dict[str, Any]) -> str:
        result = self._rpc("tools/call", {"name": tool, "arguments": args})
        if isinstance(result, dict):
            pieces = []
            for item in result.get("content", []):
                if item.get("type") == "text":
                    pieces.append(item.get("text", ""))
            if pieces:
                return "\n".join(pieces)
            if "structuredContent" in result:
                return json.dumps(result["structuredContent"], indent=2)
        return json.dumps(result, indent=2) if result is not None else "(empty result)"

    def shutdown(self) -> None:
        self._stop()


# ---------------------------------------------------------------------------
# HTTP transport — composable MCP agent endpoint (e.g. a 21st.dev agent URL)
# ---------------------------------------------------------------------------
class HTTPMCPServer:
    """A composable MCP-compatible agent reachable over HTTP (OpenAI tools path).

    You can register one of these as an MCP server whose ``command`` starts
    with ``http://`` or ``https://`` — claume then fires tool calls at the
    endpoint and collects the text reply. This is the path 21st.dev-style
    design discovery uses once you point it at a live agent instead of a
    local npx process.
    """

    def __init__(self, name: str, spec: Dict[str, Any]) -> None:
        self.name = name
        self.spec = spec if isinstance(spec, dict) else {}
        raw = str(spec.get("command", ""))
        self.base_url = raw if raw.startswith("http") else ""
        self.api_key_env = str(spec.get("needs_key", "")).upper()
        self.description = str(spec.get("description", ""))
        self.enabled = bool(spec.get("enabled", True))
        self._tools = self._discover_tools()
        self._warmed = False

    def _discover_tools(self) -> List[Dict[str, Any]]:
        # Public 21st.dev / composable-agent endpoint: tools are declared
        # in the server spec (for HTTP agents we trust the config, not a
        # live discovery that can hang). Falls back to a generic discover
        # tool so the agent has something callable.
        desc = self.description
        out = []
        if "21st" in self.name or "21st" in desc.lower():
            out = [
                {"name": "search_human_blocks", "description": "Search 21st.dev for human-written design blocks and components.",
                 "inputSchema": {"type": "object", "properties": {
                     "query": {"type": "string", "description": "what to find (e.g. 'pricing hero', 'bento sidebar')"},
                     "theme": {"type": "string", "description": "design theme cue (e.g. cinematic-dark, glassmorphism, brutalist)"},
                     "context": {"type": "string", "description": "existing layout/context to refine against"},
                 }, "required": ["query"]}},
                {"name": "get_component", "description": "Retrieve a specific component by name or slug.",
                 "inputSchema": {"type": "object", "properties": {
                     "name": {"type": "string", "description": "component name/slug"},
                 }, "required": ["name"]}},
            ]
        if not out:
            out = [
                {"name": "discover", "description": f"{self.name}: ask this agent for a design/component result.",
                 "inputSchema": {"type": "object", "properties": {
                     "query": {"type": "string"},
                     "context": {"type": "string"},
                 }, "required": ["query"]}},
            ]
        return out

    def _live_discover(self) -> List[Dict[str, Any]]:
        """Best-effort live tool-list from an HTTP MCP agent (optional)."""
        if not self.base_url:
            return self._tools
        try:
            import urllib.request
            import urllib.error
            req = urllib.request.Request(
                f"{self.base_url}/tools/list", method="POST",
                data=json.dumps({}).encode("utf-8"),
                headers={"Content-Type": "application/json",
                         "Authorization": f"Bearer {keyvault.resolve_key(self.api_key_env) or ''}"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8", "replace"))
                return list(data.get("tools", [])) if isinstance(data, dict) else []
        except Exception:
            return self._tools

    def _call_http(self, tool: str, args: Dict[str, Any]) -> str:
        if not self.base_url:
            return f"error: '{self.name}' is a local stdio server, not an HTTP endpoint — point its command at https://... to use this path"
        key = keyvault.resolve_key(self.api_key_env)
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        # Two shapes a composable agent might accept:
        # 1) OpenAI tools call: POST /v1/chat/completions with tool_calls
        # 2) plain MCP-over-HTTP: POST /tools/call {name, arguments}
        payload_chat = {
            "model": "21st-dev-agent",
            "messages": [{"role": "user", "content": json.dumps({"tool": tool, "arguments": args})}],
            "max_tokens": 4000,
            "temperature": 0.1,
        }
        payload_mcp = {"name": tool, "arguments": args}
        last = None
        for payload, path in ((payload_chat, "/v1/chat/completions"), (payload_mcp, "/tools/call")):
            for attempt in range(2):
                try:
                    import urllib.request
                    import urllib.error
                    req = urllib.request.Request(
                        f"{self.base_url}{path}",
                        data=json.dumps(payload).encode("utf-8"),
                        headers=headers,
                        method="POST",
                    )
                    with urllib.request.urlopen(req, timeout=60) as resp:
                        data = json.loads(resp.read().decode("utf-8", "replace"))
                    if path == "/v1/chat/completions":
                        # unwrap OpenAI completion -> text
                        choices = data.get("choices") or []
                        for c in choices:
                            m = c.get("message", {})
                            for tc in (m.get("tool_calls") or []):
                                fn = tc.get("function", {})
                                if fn.get("name") == tool:
                                    try:
                                        return json.loads(fn.get("arguments", "{}")).get("result", "") or json.dumps(fn.get("arguments", {}), indent=2)
                                    except Exception:
                                        return fn.get("arguments", "")
                        text = (choices[0].get("message", {}) if choices else {}).get("content", "") or ""
                        if text:
                            return str(text)
                        continue
                    # MCP path: {content: [{type:text, text:...}]}
                    pieces = []
                    for item in (data.get("content") or []):
                        if isinstance(item, dict) and item.get("type") == "text":
                            pieces.append(item.get("text", ""))
                    if pieces:
                        return "\n".join(pieces)
                    if "result" in data:
                        return str(data["result"])
                    return json.dumps(data, indent=2)
                except urllib.error.HTTPError as exc:
                    detail = exc.read().decode("utf-8", "replace")
                    if exc.code in (401, 403):
                        return f"error: '{self.name}' returned HTTP {exc.code} (auth) — check /mcp-key {self.name}"
                    last = f"HTTP {exc.code}: {detail[:200]}"
                    if exc.code in (429, 500, 502, 503, 504) and attempt == 0:
                        import time; time.sleep(1.0)
                        continue
                    break
                except Exception as exc:
                    last = str(exc)[:200]
                    break
        return f"error: '{self.name}' call failed: {last or 'no response'}"

    def initialize(self) -> bool:
        # HTTP agents warm up by doing a cheap discovery; no stdio handshake.
        try:
            self._tools = self._live_discover()
            self._warmed = True
            return True
        except Exception:
            return True

    def list_tools(self) -> List[Dict[str, Any]]:
        return self._tools

    def call_tool(self, tool: str, args: Dict[str, Any]) -> str:
        # route HTTP servers through the HTTP path, stdio servers through RPC
        if self.base_url:
            return self._call_http(tool, args)
        # delegate to a plain MCPServer if somehow mixed (shouldn't happen)
        return f"error: '{self.name}' HTTP mode does not expose stdio call — check spec"
