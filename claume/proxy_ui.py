"""free-claume dashboard — a luxurious local web UI for the proxy.

Served from the same ThreadingHTTPServer used by the proxy (extra routes)
or standalone. Open with ``/proxy-ui`` in claume.
"""
from __future__ import annotations

import json
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict

from . import config, keyvault, proxy
from .version import __version__

_DASHBOARD_SERVER: Any = None

HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>free-claume dashboard</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root{
    --bg:#07090c; --panel:#0d1117; --panel2:#111823; --line:#1d2634;
    --green:#76b900; --mint:#7ef0c0; --text:#e6edf3; --dim:#8b949e;
    --gold:#e3b341; --red:#f85149;
  }
  *{box-sizing:border-box;margin:0;padding:0}
  body{
    background:
      radial-gradient(1200px 600px at 20% -10%, rgba(118,185,0,.08), transparent 60%),
      radial-gradient(900px 500px at 90% 110%, rgba(126,240,192,.05), transparent 60%),
      var(--bg);
    color:var(--text); font-family:"Segoe UI",system-ui,sans-serif; min-height:100vh;
  }
  .wrap{max-width:980px;margin:0 auto;padding:48px 24px}
  .logo{font-size:40px;font-weight:800;letter-spacing:-1px}
  .logo .g{color:var(--green)} .logo .m{color:var(--mint)}
  .sub{color:var(--dim);margin-top:6px}
  .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:16px;margin-top:36px}
  .card{
    background:linear-gradient(180deg,var(--panel2),var(--panel));
    border:1px solid var(--line); border-radius:14px; padding:20px;
    box-shadow:0 10px 30px rgba(0,0,0,.35);
    transition:transform .15s ease, border-color .15s ease;
  }
  .card:hover{transform:translateY(-2px);border-color:rgba(118,185,0,.45)}
  .k{color:var(--dim);font-size:12px;text-transform:uppercase;letter-spacing:.12em}
  .v{font-size:28px;font-weight:700;margin-top:8px}
  .v.green{color:var(--green)} .v.mint{color:var(--mint)} .v.gold{color:var(--gold)}
  .status-dot{display:inline-block;width:9px;height:9px;border-radius:50%;background:var(--green);
    box-shadow:0 0 10px var(--green); margin-right:8px; animation:pulse 2s infinite}
  @keyframes pulse{0%,100%{opacity:1}50%{opacity:.35}}
  table{width:100%;border-collapse:collapse;margin-top:10px}
  td,th{padding:10px 12px;border-bottom:1px solid var(--line);text-align:left;font-size:14px}
  th{color:var(--dim);font-weight:600}
  code{background:var(--panel2);border:1px solid var(--line);padding:2px 8px;border-radius:6px;font-size:13px}
  .bar{height:6px;border-radius:4px;background:var(--line);overflow:hidden;margin-top:10px}
  .bar>i{display:block;height:100%;background:linear-gradient(90deg,var(--green),var(--mint));width:0%;
    animation:fill 1.2s ease forwards}
  @keyframes fill{to{width:var(--w,70%)}}
  .foot{margin-top:40px;color:var(--dim);font-size:13px}
  a{color:var(--mint);text-decoration:none}
</style>
</head>
<body>
<div class="wrap">
  <div class="logo"><span class="g">free</span>-claume <span class="m">dashboard</span></div>
  <div class="sub"><span class="status-dot"></span>OpenAI-compatible gateway → NVIDIA NIM · claume-code v__VERSION__</div>

  <div class="grid">
    <div class="card"><div class="k">Endpoint</div><div class="v mint" style="font-size:20px">__BASE__</div>
      <div class="bar"><i style="--w:100%"></i></div></div>
    <div class="card"><div class="k">Keys loaded</div><div class="v green">__KEYS__</div></div>
    <div class="card"><div class="k">Requests served</div><div class="v">__REQ__</div></div>
    <div class="card"><div class="k">Errors</div><div class="v __ERRCLS__">__ERR__</div></div>
  </div>

  <div class="grid">
    <div class="card" style="grid-column:1/-1">
      <div class="k">Default model pool</div>
      <table>
        <tr><th>Model</th><th>Use</th></tr>
        __MODEL_ROWS__
      </table>
    </div>
  </div>

  <div class="grid">
    <div class="card" style="grid-column:1/-1">
      <div class="k">Quick use</div>
      <p style="margin-top:10px;color:var(--dim);font-size:14px;line-height:1.7">
        Point any OpenAI SDK at <code>__BASE__</code> and go — streaming supported.<br>
        Manage keys with <code>claume /key NAME</code> in the terminal, or add more
        NVIDIA keys as <code>NVIDIA_API_KEY_2</code>, <code>_3</code>… for rotation.
      </p>
    </div>
  </div>

  <div class="foot">claume-code · runs 100% locally · your keys never leave this machine except to NVIDIA</div>
</div>
</body>
</html>"""


class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, *a: Any) -> None:
        pass

    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/dashboard"):
            cfg = config.Config()
            state = config.load_proxy_state() or {}
            base = state.get("base_url", f"http://127.0.0.1:{cfg.get('proxy_port', 8000)}/v1")
            try:
                import urllib.request as ur

                req = ur.Request(f"{base.rstrip('/').rsplit('/v1', 1)[0]}/health")
                with ur.urlopen(req, timeout=2) as r:
                    health = json.loads(r.read().decode())
            except Exception:
                health = {"keys": 0, "requests": 0, "errors": 0}

            keys = keyvault.list_keys()
            rows = "".join(
                f"<tr><td><code>{m}</code></td><td style='color:var(--dim)'>{why}</td></tr>"
                for m, why in [
                    ("meta/llama-3.3-70b-instruct", "best all-round coder"),
                    ("meta/llama-3.1-405b-instruct", "deepest reasoning"),
                    ("qwen/qwen2.5-coder-32b-instruct", "code-edit specialist"),
                    ("deepseek-ai/deepseek-r1", "hard bugs, CoT"),
                ]
            )
            errors = health.get("errors", 0)
            html = (
                HTML.replace("__VERSION__", __version__)
                .replace("__BASE__", base)
                .replace("__KEYS__", str(health.get("keys", 0)))
                .replace("__REQ__", str(health.get("requests", 0)))
                .replace("__ERR__", str(errors))
                .replace("__ERRCLS__", "green" if errors == 0 else "gold")
                .replace("__MODEL_ROWS__", rows)
            )
            data = html.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif self.path.startswith("/health"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        else:
            self.send_response(404)
            self.end_headers()


def serve_and_open(port: int = 8100) -> None:
    global _DASHBOARD_SERVER
    if _DASHBOARD_SERVER is None:
        _DASHBOARD_SERVER = ThreadingHTTPServer(("127.0.0.1", port), DashboardHandler)
        t = threading.Thread(target=_DASHBOARD_SERVER.serve_forever, daemon=True)
        t.start()
    url = f"http://127.0.0.1:{port}/dashboard"
    print(f"\033[38;5;46m✦ dashboard → {url}\033[0m")
    webbrowser.open(url)
