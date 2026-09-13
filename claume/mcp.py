"""MCP client for claume-code — stdio JSON-RPC bridge to MCP servers.

Implements the Model Context Protocol handshake (initialize →
tools/list → tools/call) over stdio for servers registered with
/mcp-add or shipped in the DESIGN_STACK preset. Also contains the
Link System: a design pipeline that chains several MCP servers so
claume produces human-grade UI instead of generic divs.
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

# ---------------------------------------------------------------------------
# Presets
# ---------------------------------------------------------------------------
# The UI design stack (from the user's stack config). Install with:
#   /mcp-preset design
DESIGN_STACK: Dict[str, Dict[str, Any]] = {
    "uidiscovery-21st": {
        "command": "npx",
        "args": ["-y", "@21st-dev/magic"],
        "description": "Searches and fetches verified, human-written design blocks and advanced components.",
    },
    "microinteractions-reactbits": {
        "command": "npx",
        "args": ["reactbits-dev-mcp-server"],
        "description": "Injects complex physical fluid dynamics, shader canvases, and kinetic typography.",
    },
    "animation-motion": {
        "command": "npx",
        "args": ["@abhishekrajpurohit/motion-dev-mcp"],
        "description": "Calculates and maps production-ready, hardware-accelerated Framer Motion timelines.",
    },
    "atomic-shadcnspace": {
        "command": "npx",
        "args": ["shadcnspace-mcp"],
        "description": "Streams standard layout tokens, dashboard wireframes, and valid TypeScript props.",
    },
}

PRESETS: Dict[str, Dict[str, Dict[str, Any]]] = {
    "design": DESIGN_STACK,
}

_LINK_TIMEOUT = 90  # seconds per MCP tool call
_INITIALIZ_TIMEOUT = 75  # npx cold-starts can take a while on first download


def _npm_cache_dir() -> Path:
    """Every claume-managed npm/MCP download lands in ~/.claume/mcp.

    Keeps npx caches, installed MCP packages and their node_modules inside
    the claume install folder instead of scattering them across the user's
    global npm cache / project directories.
    """
    from . import config as _cfg

    d = _cfg.mcp_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / "npx-cache").mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# npm spec resolution: run MCP servers from ~/.claume/mcp/npm, not npx
# ---------------------------------------------------------------------------
# npx cold-starts spawn cmd.exe shims + cache resolution that can hang for
# minutes (or forever behind some proxies). We npm-install each MCP package
# ONCE into ~/.claume/mcp/npm and launch its bin script with `node` — the
# same mechanism animation-motion already uses, applied automatically.
_npm_lock = threading.Lock()
_npm_installed: set = set()


def _npm_root() -> Path:
    d = _npm_cache_dir() / "npm"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _spec_package_name(npm_spec: str) -> str:
    """'@21st-dev/magic@1.2' -> '@21st-dev/magic' · 'clerk@latest' -> 'clerk'."""
    spec = npm_spec.strip()
    if spec.startswith("@"):
        return "@" + spec[1:].split("@")[0]
    return spec.split("@")[0]


def _find_npm_bin(npm_spec: str) -> Optional[Path]:
    """Locate the installed package's bin/main script under ~/.claume/mcp/npm."""
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
    """npm install <spec> into ~/.claume/mcp/npm. Returns True on success."""
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
    """Translate an npx-style MCP spec into a node invocation.

    npx -y <pkg> [args…]  becomes  node <~/.claume/mcp/npm/.../bin.js> [args…]
    installing the package on first use. Returns (command, args) — either
    the resolved node invocation, or the original spec when resolution
    fails (caller falls back to npx, which may still work).
    """
    command = str(spec.get("command", ""))
    args = [str(a) for a in spec.get("args", [])]
    if command not in ("npx", "npm") or not args:
        return command, args
    # First non-flag arg is the package spec (handles `npx -y pkg …`).
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
            _npm_installed.add(key)  # do not retry-install every spawn
    if script is not None:
        return "node", [str(script)] + rest
    return command, args


class MCPError(Exception):
    pass


class MCPServer:
    """One running MCP server process (stdio JSON-RPC)."""

    def __init__(self, name: str, spec: Dict[str, Any]) -> None:
        self.name = name
        self.spec = spec if isinstance(spec, dict) else {}
        # npx-style specs resolve to node <script> under ~/.claume/mcp/npm
        # (auto-installed on first use) — npx cold-starts can hang forever.
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

    # -- process -------------------------------------------------------
    def _start(self) -> None:
        if self._proc and self._proc.poll() is None:
            return
        # Windows: npx/npm live as .cmd shims which CreateProcess cannot
        # resolve from a bare name — resolve via PATH and wrap if needed.
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
        # Keep every npm-managed MCP download inside ~/.claume/mcp so
        # installations live in the installed claume folder.
        npm_root = _npm_cache_dir()
        env["npm_config_cache"] = str(npm_root / "npx-cache")
        env["npm_config_prefix"] = str(npm_root)
        env.setdefault("npm_config_update_notifier", "false")
        extra_env = self.spec.get("env") if isinstance(self.spec, dict) else None
        if isinstance(extra_env, dict):
            for k, v in extra_env.items():
                if isinstance(v, str) and not v.startswith("<"):
                    env[k] = v
        # Vault keys: server spec may name an env var via needs_key.
        needs_key = self.spec.get("needs_key") if isinstance(self.spec, dict) else None
        if needs_key:
            try:
                from . import keyvault

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
            raise MCPError(
                f"cannot spawn '{self.command}' — is it installed and on PATH?"
            )

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

    # -- JSON-RPC ------------------------------------------------------
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

            # reader thread pulls lines until the matching id shows up
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

    # -- MCP protocol --------------------------------------------------
    def initialize(self) -> bool:
        try:
            self._rpc("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "claume-code", "version": "2.0.0"},
            }, timeout=_INITIALIZ_TIMEOUT)
            # 'notifications/initialized' is a JSON-RPC NOTIFICATION: the
            # server must not reply, so send it without waiting for a result.
            try:
                assert self._proc is not None and self._proc.stdin
                note = {"jsonrpc": "2.0", "method": "notifications/initialized"}
                self._proc.stdin.write(json.dumps(note) + "\n")
                self._proc.stdin.flush()
            except Exception:
                pass  # non-fatal: some servers tolerate its absence
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
# Registry of configured servers (from config mcp_servers)
# ---------------------------------------------------------------------------
_processes: Dict[str, MCPServer] = {}


def _servers_from_config() -> Dict[str, Dict[str, Any]]:
    from . import config as cfgmod

    servers = cfgmod.Config().get("mcp_servers", {})
    servers = servers if isinstance(servers, dict) else {}
    # Disabled servers are excluded from bridging/probing entirely.
    return {
        name: spec
        for name, spec in servers.items()
        if not isinstance(spec, dict) or spec.get("enabled", True)
    }


def full_server_map() -> Dict[str, Dict[str, Any]]:
    """All configured servers including disabled ones (for /mcp display)."""
    from . import config as cfgmod

    servers = cfgmod.Config().get("mcp_servers", {})
    return servers if isinstance(servers, dict) else {}


def set_enabled(name: str, enabled: bool) -> bool:
    """Enable/disable a configured server. Returns True if it existed."""
    from . import config as cfgmod

    cfg = cfgmod.Config()
    servers = cfg.get("mcp_servers", {})
    if name not in servers:
        return False
    spec = servers[name]
    if isinstance(spec, dict):
        spec["enabled"] = enabled
    else:
        servers[name] = {"command": str(spec), "enabled": enabled}
    cfg.set("mcp_servers", servers)
    # Drop any cached process so the next use re-initializes cleanly.
    _processes.pop(name, None)
    return True


def get_server(name: str) -> MCPServer:
    """Get (and cache) a running MCPServer by config name."""
    if name in _processes:
        return _processes[name]
    servers = _servers_from_config()
    if name not in servers:
        raise MCPError(f"unknown MCP server '{name}' (configured: {', '.join(servers) or 'none'})")
    srv = MCPServer(name, servers[name])
    if not srv.initialize():
        raise MCPError(f"server '{name}' failed MCP initialize handshake")
    _processes[name] = srv
    return srv


def call_tool(server: str, tool: str, args: Dict[str, Any]) -> str:
    """Call a tool on a configured server, one-shot."""
    return get_server(server).call_tool(tool, args)


def list_all_tools() -> Dict[str, List[str]]:
    """Probe every configured+enabled server; returns {server: [tool,...]}.

    Disabled servers are listed with a '<disabled>' marker so /mcp can
    show enabled/disabled state side by side.
    """
    out: Dict[str, List[str]] = {}
    all_servers = full_server_map()
    for name, spec in all_servers.items():
        if isinstance(spec, dict) and not spec.get("enabled", True):
            out[name] = ["<disabled>"]
            continue
        try:
            srv = get_server(name)
            out[name] = [t.get("name", "?") for t in srv.list_tools()]
        except MCPError as exc:
            out[name] = [f"<error: {exc}>"]
    return out


def shutdown_all() -> None:
    for srv in list(_processes.values()):
        try:
            srv.shutdown()
        except Exception:
            pass
    _processes.clear()


# ---------------------------------------------------------------------------
# Tool bridge — expose MCP tools to the agent's registry dynamically
# ---------------------------------------------------------------------------
_BRIDGED = False


def bridge_to_registry() -> int:
    """Register every MCP tool as a claume tool (mcp_<server>_<tool>).

    Returns the number of bridged tools. Called lazily on first /mcp use.
    """
    global _BRIDGED
    if _REGISTRY_TARGET is None:
        return 0
    if _BRIDGED:
        return _bridged_count
    count = 0
    for name in _servers_from_config():
        try:
            srv = get_server(name)
        except MCPError:
            continue
        for tool in srv.list_tools():
            tname = tool.get("name", "")
            if not tname:
                continue
            clname = f"mcp_{name}_{tname}"[:60]
            desc = str(tool.get("description", "MCP tool"))[:160]

            def _make(srv_name: str, tool_name: str):
                def _fn(base: Path, **kw: Any) -> Tuple[str, bool]:
                    try:
                        out = call_tool(srv_name, tool_name, kw)
                        return out, False
                    except MCPError as exc:
                        return f"error: {exc}", True

                return _fn

            _REGISTRY_TARGET.register(
                clname, f"[mcp:{name}] {desc}", {}, []
            )(_make(name, tname))
            count += 1
    _BRIDGED = True
    _bridged_count = count
    return count


_bridged_count = 0
_REGISTRY_TARGET = None


def set_registry_target(registry_module: Any) -> None:
    global _REGISTRY_TARGET
    _REGISTRY_TARGET = registry_module


# ---------------------------------------------------------------------------
# The Link System — orchestrated design pipeline
# ---------------------------------------------------------------------------
def design_pipeline(request: str, workspace: Path) -> Tuple[str, bool]:
    """Run the 4-stage UI design pipeline across the design MCP stack.

    Stage 1  atomic-shadcnspace      — base layout blueprint (grid/tokens)
    Stage 2  uidiscovery-21st        — swap boxes for human-designed blocks
    Stage 3  animation-motion        — bind Framer Motion timelines
    Stage 4  microinteractions-reactbits — wrap with fluid canvas background

    Missing/unavailable stages degrade gracefully: the pipeline still
    returns useful instructions for the agent to build with.
    """
    steps_log: List[str] = []
    layout = ""
    components = ""
    animated = ""

    def _try(server: str, tool_candidates: List[str], args: Dict[str, Any]) -> str:
        """Call the first tool name that exists on the server."""
        try:
            srv = get_server(server)
            names = {t.get("name", "") for t in srv.list_tools()}
        except MCPError as exc:
            steps_log.append(f"⚠ {server}: {exc}")
            return ""
        for tool in tool_candidates:
            if tool in names:
                try:
                    out = srv.call_tool(tool, args)
                    steps_log.append(f"✓ {server}::{tool}")
                    return out[:8000]
                except MCPError as exc:
                    steps_log.append(f"⚠ {server}::{tool}: {exc}")
                    return ""
        steps_log.append(f"⚠ {server}: no tool among {tool_candidates}")
        return ""

    # Stage 1 — structure: search Shadcn Space blocks for the layout.
    # Keyword extraction: servers do better with 1-2 plain words than sentences.
    keyword = "hero"
    for k in ("dashboard", "landing", "portfolio", "pricing", "sidebar", "bento"):
        if k in request.lower():
            keyword = k
            break
    layout = _try("atomic-shadcnspace", ["searchBlocks", "listBlocks"], {
        "query": keyword,
    })
    # Stage 2 — human blocks: 21st.dev component discovery.
    components = _try("uidiscovery-21st", ["search_human_blocks", "search", "get_component", "retrieve"], {
        "context": (layout or request)[:4000], "theme": "cinematic-dark", "query": request,
    })
    # Stage 3 — motion: search Motion.dev docs for the right animation patterns.
    animated = _try("animation-motion", ["search_motion_docs", "get_framework_guide"], {
        "query": f"staggered entry animation {request}", "framework": "react", "limit": 8,
    })
    # Stage 4 — fluid canvas: pull the React Bits 'aurora' shader background.
    background = _try("microinteractions-reactbits", ["get_component_demo", "get_component"], {
        "name": "aurora",
    })

    report = [
        "CLAUME LINK SYSTEM — design pipeline report",
        "=" * 48,
        f"request: {request}",
        "",
    ]
    report += steps_log or ["(no design servers configured — run /mcp-preset design)"]
    for label, payload in (
        ("1. LAYOUT BLUEPRINT (shadcnspace)", layout),
        ("2. HUMAN COMPONENTS (21st.dev)", components),
        ("3. MOTION TIMELINES (motion.dev)", animated),
        ("4. FLUID BACKGROUND (reactbits)", background),
    ):
        if payload:
            report += ["", f"── {label} " + "─" * 20, payload]

    report += [
        "",
        "BUILD DIRECTIVES:",
        "- Use the blueprints/blocks above instead of generic placeholder divs.",
        "- Keep the layout spacious; minimize harsh borders; use a sophisticated",
        "  typographic scale.",
        "- Wire animations with Framer Motion (hardware-accelerated), not raw JS.",
        "- If a stage failed above, build that part by hand but keep the same",
        "  quality bar.",
    ]
    return "\n".join(report), False
