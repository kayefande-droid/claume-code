"""free-claume proxy — a local OpenAI-compatible gateway to NVIDIA NIM.

The proxy listens on ``http://127.0.0.1:<port>/v1`` and exposes:

* ``POST /v1/chat/completions``  (streaming + non-streaming)
* ``GET  /v1/models``            (live model discovery)
* ``GET  /health``               (status probe)

Features
--------
* Prompts for the NVIDIA API key (``nvapi-…``) on first run and stores it
  in the local vault.
* Supports several keys (``NVIDIA_API_KEY``, ``NVIDIA_API_KEY_2``, …)
  with automatic rotation on 401/403/429 so a rate-limited key doesn't
  stop the agent.
* Retries with exponential backoff on transient errors (timeouts, 5xx).
* Streams tokens straight through as SSE, exactly like OpenAI.
* Stdlib-only (``http.server`` + ``urllib``) — zero heavy dependencies.

Run standalone with ``python -m claume.proxy``.
"""
from __future__ import annotations

import json
import os
import ssl
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import config, keyvault

NVIDIA_BASE = "https://integrate.api.nvidia.com/v1"
MODELS_URL = f"{NVIDIA_BASE}/models"

# Roughly ordered by capability for coding work.
DEFAULT_MODEL_POOL = [
    "meta/llama-3.3-70b-instruct",
    "meta/llama-3.1-405b-instruct",
    "qwen/qwen2.5-coder-32b-instruct",
    "deepseek-ai/deepseek-r1",
]

_SSL_CTX = ssl.create_default_context()


# --------------------------------------------------------------------------
# Key management
# --------------------------------------------------------------------------
def collect_keys() -> List[str]:
    """Gather every usable NVIDIA key: vault first, then env vars."""
    keys: List[str] = []

    vault = config.Config().get("key_vault", {})
    for name in sorted(vault.keys() if isinstance(vault, dict) else []):
        value = keyvault.get_key(name)
        if value:
            keys.append(value)

    env_key = keyvault.resolve_key("NVIDIA_API_KEY")
    if env_key and env_key not in keys:
        keys.append(env_key)

    i = 2
    while True:
        name = f"NVIDIA_API_KEY_{i}"
        extra = keyvault.resolve_key(name)
        if extra and extra not in keys:
            keys.append(extra)
        else:
            break
        i += 1
    return keys


def prompt_for_nvidia_key() -> Optional[str]:
    """First-run onboarding: ask for a free nvapi- key and store it."""
    # Never prompt when stdin isn't a terminal (piped/CI) — stay silent.
    try:
        if not sys.stdin.isatty():
            return None
    except Exception:
        return None
    print()
    print("\033[38;5;46m┌──────────────────────────────────────────────────────────┐")
    print("│  free-claume proxy setup                                 │")
    print("└──────────────────────────────────────────────────────────┘\033[0m")
    print(
        "\n  claume uses the free NVIDIA NIM API. Getting a key takes ~1 minute:\n"
        "   1. Visit  \033[1mhttps://build.nvidia.com\033[0m\n"
        "   2. Create a free account (no credit card needed)\n"
        "   3. On any model page, click \033[1m'Get API Key'\033[0m — it starts with 'nvapi-'\n"
    )
    try:
        raw = input("  Paste your NVIDIA API key (or press Enter to skip): ").strip()
    except (EOFError, KeyboardInterrupt):
        raw = ""
    if raw.startswith("nvapi-") and len(raw) > 20:
        keyvault.set_key("NVIDIA_API_KEY", raw)
        cfg = config.Config()
        cfg.set("key_vault.NVIDIA_API_KEY", True)
        print("\033[38;5;46m  ✔ Key stored securely in your .claume vault.\033[0m")
        return raw
    if raw:
        print("\033[38;5;203m  ✘ That doesn't look like an nvapi- key; skipping.\033[0m")
    return None


def ensure_keys() -> List[str]:
    keys = collect_keys()
    if not keys:
        key = prompt_for_nvidia_key()
        keys = [key] if key else []
    return keys


# --------------------------------------------------------------------------
# Upstream calls
# --------------------------------------------------------------------------
class UpstreamError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def _post_chat(
    payload: Dict[str, Any],
    api_key: str,
    timeout: float = 180.0,
) -> Tuple[int, Any]:
    """POST to NVIDIA; returns (status, parsed-or-raw-bytes)."""
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{NVIDIA_BASE}/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "text/event-stream" if payload.get("stream") else "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX)
        return resp.status, resp
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise UpstreamError(exc.code, detail) from exc
    except urllib.error.URLError as exc:
        raise UpstreamError(502, f"upstream unreachable: {exc}") from exc


def _list_models(api_key: str) -> List[Dict[str, Any]]:
    req = urllib.request.Request(
        MODELS_URL,
        headers={"Authorization": f"Bearer {api_key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30, context=_SSL_CTX) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("data", [])
    except Exception:
        # Fall back to a static pool if discovery fails.
        return [{"id": m, "object": "model"} for m in DEFAULT_MODEL_POOL]


def _sse_iter(resp: Any) -> Iterable[bytes]:
    while True:
        chunk = resp.readline()
        if not chunk:
            break
        yield chunk


# --------------------------------------------------------------------------
# HTTP handler
# --------------------------------------------------------------------------
class ProxyHandler(BaseHTTPRequestHandler):
    server_version = "free-claume/1.0"
    protocol_version = "HTTP/1.1"

    # Runtime state shared across handler instances.
    state: Dict[str, Any] = {
        "keys": [],
        "key_index": 0,
        "lock": threading.Lock(),
        "requests": 0,
        "errors": 0,
        "last_error": "",
        "model_pool": list(DEFAULT_MODEL_POOL),
    }

    def log_message(self, fmt: str, *args: Any) -> None:  # quiet by default
        if ProxyHandler.state.get("verbose"):
            super().log_message(fmt, *args)

    # -- helpers -----------------------------------------------------
    def _json(self, status: int, obj: Dict[str, Any]) -> None:
        data = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _next_key(self) -> str:
        keys = ProxyHandler.state["keys"]
        if not keys:
            raise UpstreamError(401, "no NVIDIA API key configured — run 'claume proxy --setup'")
        with ProxyHandler.state["lock"]:
            key = keys[ProxyHandler.state["key_index"] % len(keys)]
            ProxyHandler.state["key_index"] += 1
        return key

    def _rotate_key(self, failed: str) -> None:
        keys = ProxyHandler.state["keys"]
        if len(keys) > 1:
            with ProxyHandler.state["lock"]:
                ProxyHandler.state["key_index"] = (
                    keys.index(failed) + 1 if failed in keys else 0
                ) % len(keys)

    def _refresh_keys(self) -> None:
        keys = collect_keys()
        if keys:
            ProxyHandler.state["keys"] = keys

    # -- routes ------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        if self.path in ("/health", "/healthz"):
            self._json(
                200,
                {
                    "status": "ok",
                    "service": "free-claume-proxy",
                    "upstream": NVIDIA_BASE,
                    "keys": len(ProxyHandler.state["keys"]),
                    "requests": ProxyHandler.state["requests"],
                    "errors": ProxyHandler.state["errors"],
                    "models": ProxyHandler.state["model_pool"][:3],
                },
            )
            return
        if self.path == "/v1/models":
            self._handle_models()
            return
        self._json(404, {"error": {"message": f"unknown path {self.path}"}})

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/v1/chat/completions":
            self._handle_chat()
            return
        self._json(404, {"error": {"message": f"unknown path {self.path}"}})

    def _handle_models(self) -> None:
        self._refresh_keys()
        keys = ProxyHandler.state["keys"]
        if not keys:
            self._json(401, {"error": {"message": "no API key configured"}})
            return
        models = _list_models(keys[0])
        ProxyHandler.state["model_pool"] = [m.get("id", "") for m in models] or list(
            DEFAULT_MODEL_POOL
        )
        self._json(200, {"object": "list", "data": models})

    def _handle_chat(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception:
            self._json(400, {"error": {"message": "invalid JSON body"}})
            return

        payload.setdefault("model", config.Config().model)
        wants_stream = bool(payload.get("stream"))

        self._refresh_keys()
        ProxyHandler.state["requests"] += 1

        attempts = 0
        last_err: Optional[UpstreamError] = None
        while attempts < 4:
            attempts += 1
            key = self._next_key()
            try:
                if wants_stream:
                    self._stream_response(dict(payload), key)
                else:
                    status, resp = _post_chat(dict(payload), key)
                    data = resp.read()
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                return
            except UpstreamError as exc:
                last_err = exc
                ProxyHandler.state["errors"] += 1
                ProxyHandler.state["last_error"] = str(exc)[:200]
                if exc.status in (401, 403, 429):
                    self._rotate_key(key)
                    time.sleep(min(2.0 * attempts, 6.0))
                    continue
                if exc.status >= 500:
                    time.sleep(min(2.0 * attempts, 6.0))
                    continue
                break

        status = last_err.status if last_err else 502
        message = last_err.args[0] if last_err else "unknown proxy failure"
        self._json(status, {"error": {"message": message, "type": "proxy_error"}})

    # -- streaming -----------------------------------------------------
    def _stream_response(self, payload: Dict[str, Any], key: str) -> None:
        payload["stream"] = True
        status, resp = _post_chat(payload, key)
        self.send_response(status)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            for chunk in _sse_iter(resp):
                if chunk.startswith(b"data: ") or chunk == b"data:\n":
                    self.wfile.write(chunk)
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass


# --------------------------------------------------------------------------
# Server lifecycle
# --------------------------------------------------------------------------
_server: Optional[ThreadingHTTPServer] = None


def start_server(host: Optional[str] = None, port: Optional[int] = None, verbose: bool = False) -> ThreadingHTTPServer:
    global _server
    cfg = config.Config()
    host = host or cfg.get("proxy_host", "127.0.0.1")
    port = int(port or cfg.get("proxy_port", 8000))

    ProxyHandler.state["keys"] = collect_keys()
    ProxyHandler.state["verbose"] = verbose

    _server = ThreadingHTTPServer((host, port), ProxyHandler)
    _server.daemon_threads = True
    thread = threading.Thread(target=_server.serve_forever, daemon=True)
    thread.start()

    config.save_proxy_state(
        {
            "host": host,
            "port": port,
            "pid": os.getpid(),
            "base_url": f"http://{host}:{port}/v1",
            "started_at": time.time(),
            "models": ProxyHandler.state["model_pool"][:5],
        }
    )
    return _server


def stop_server() -> None:
    global _server
    if _server is not None:
        _server.shutdown()
        _server = None
        config.clear_proxy_state()


def is_running() -> bool:
    """Probe the /health endpoint for a LIVE proxy (state file can be stale)."""
    state = config.load_proxy_state() or {}
    cfg = config.Config()
    host = state.get("host") or cfg.get("proxy_host", "127.0.0.1")
    port = state.get("port") or cfg.get("proxy_port", 8000)
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/health", timeout=1.5) as resp:
            return resp.status == 200
    except Exception:
        return False


def serve_foreground(verbose: bool = False) -> int:
    """Run the proxy in the foreground until Ctrl+C (used by `claume proxy`)."""
    start_server(verbose=verbose)
    cfg = config.Config()
    nkeys = len(ProxyHandler.state["keys"])
    print(f"{GREEN}✦ free-claume proxy{RESET}  http://{cfg.get('proxy_host')}:{cfg.get('proxy_port')}/v1")
    print(f"{GREY}  upstream:{RESET} {NVIDIA_BASE}  {GREY}· keys loaded:{RESET} {nkeys}")
    print(f"{GREY}  any OpenAI SDK can point here. Press Ctrl+C to stop.{RESET}")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        stop_server()
        print("proxy stopped.")
        return 0


GREEN = "\033[38;5;46m"
GREY = "\033[38;5;245m"
RESET = "\033[0m"


if __name__ == "__main__":
    sys.exit(serve_foreground(verbose="--verbose" in sys.argv))
