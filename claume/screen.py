"""claume screen — vision, screenshots and the offline phone bridge (v3.1).

Three capabilities:

1. **Screen capture** — `capture()` grabs the screen (mss when installed,
   else PowerShell System.Drawing — zero required deps) into
   ~/.claume/screens/ and exposes a data-url for OpenAI-style vision.

2. **Vision feeding** — `screen_look` / `screen_analyze` tools put the
   screenshot in front of the model so claume (and jarvis) can SEE the
   screen, read errors on it and fix what it sees.

3. **Offline phone bridge** — `phone_bridge()` starts a tiny LAN HTTP
   server, renders a QR code (pure-Python byte-mode encoder + PNG writer,
   no deps) that any phone camera can scan; the phone's browser then
   connects to the computer **over the local network — no internet
   needed** — to view the screen, upload files and run quick fixes.
   Bluetooth PAN pairing is the documented fallback when no Wi-Fi router
   exists (same URL, phone paired via BT PAN gets an RFC1918 address).

Privacy: capture is explicit (tool call / /look command), screenshots are
capped and stored only under ~/.claume/screens/.
"""
from __future__ import annotations

import io
import json
import os
import socket
import struct
import threading
import time
import urllib.parse
import urllib.request
import zlib
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import config

MAX_SCREENS = 8  # rolling keep-last-N


def screens_dir() -> Path:
    d = config.claume_dir() / "screens"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------
def capture(monitor: int = 1, save: bool = True) -> Dict[str, Any]:
    """Grab the screen. Returns {path, data_url, bytes, width, height, engine}.

    Engine ladder: mss (fast, multi-monitor) → PowerShell System.Drawing.
    """
    out: Dict[str, Any] = {"engine": "", "path": "", "data_url": "", "bytes": 0}
    png_bytes = b""

    # 1) mss if the user installed it
    try:
        import mss  # type: ignore

        with mss.mss() as sct:
            mon = sct.monitors[min(monitor, len(sct.monitors) - 1)] or sct.monitors[1]
            shot = sct.grab(mon)
            from mss import tools as mss_tools  # type: ignore

            png_bytes = mss_tools.to_png(shot.rgb, shot.size)
            out["width"], out["height"] = shot.size
            out["engine"] = "mss"
    except Exception:
        png_bytes = _capture_windows_gdi()
        out["engine"] = "powershell-gdi"

    if not png_bytes:
        return out

    out["bytes"] = len(png_bytes)
    if save:
        p = screens_dir() / f"screen-{datetime.now().strftime('%Y%m%d-%H%M%S')}.png"
        p.write_bytes(png_bytes)
        out["path"] = str(p)
        _prune()
    import base64

    out["data_url"] = "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii")
    return out


def _capture_windows_gdi() -> bytes:
    """Zero-dependency Windows capture via PowerShell System.Drawing."""
    if os.name != "nt":
        return b""
    script = (
        "Add-Type -AssemblyName System.Windows.Forms,System.Drawing;"
        "$b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds;"
        "$bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height;"
        "$g = [System.Drawing.Graphics]::FromImage($bmp);"
        "$g.CopyFromScreen(0,0,0,0,$bmp.Size);"
        "$ms = New-Object System.IO.MemoryStream;"
        "$bmp.Save($ms,[System.Drawing.Imaging.ImageFormat]::Png);"
        "[Convert]::ToBase64String($ms.ToArray())"
    )
    try:
        import subprocess

        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True, timeout=20,
        )
        b64 = r.stdout.decode("ascii", "ignore").strip()
        import base64

        return base64.b64decode(b64) if b64 else b""
    except Exception:
        return b""


def _prune() -> None:
    try:
        shots = sorted(screens_dir().glob("screen-*.png"))
        for old in shots[:-MAX_SCREENS]:
            old.unlink(missing_ok=True)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Vision — feed a screenshot to the model through claume's LLM client
# ---------------------------------------------------------------------------
VISION_PROMPT = (
    "You are looking at a screenshot of the user's computer screen. "
    "Analyze it for the user's request: read any visible errors, dialog "
    "boxes, stack traces, UI states or layouts. Be concrete: quote the "
    "error text you can see, name the app/window, and state the fix. "
    "Answer in plain text."
)


def analyze_screen(data_url: str, question: str = "") -> Tuple[str, bool]:
    """Send one screenshot (+ optional question) to the current model."""
    from . import llm

    content: List[Dict[str, Any]] = [
        {"type": "text", "text": question.strip() or VISION_PROMPT},
        {"type": "image_url", "image_url": {"url": data_url}},
    ]
    try:
        reply = llm.stream_chat(
            [{"role": "user", "content": content}], effort="balanced"
        )
        return reply, False
    except llm.LLMError as exc:
        return (
            f"error: vision call failed — {exc}. Vision needs a "
            "vision-capable model (e.g. a gemini/gpt-class model on the "
            "active provider).",
            True,
        )


def look_and_analyze(question: str = "") -> Tuple[str, bool]:
    """Capture + analyze in one step. Returns (analysis, is_error)."""
    shot = capture()
    if not shot.get("data_url"):
        return "error: screen capture failed on this machine", True
    return analyze_screen(shot["data_url"], question)


# ---------------------------------------------------------------------------
# QR encoder — byte mode, error correction L, versions 1–10, pure stdlib
# ---------------------------------------------------------------------------
_GF_EXP = [0] * 512
_GF_LOG = [0] * 256


def _init_gf() -> None:
    x = 1
    for i in range(255):
        _GF_EXP[i] = x
        _GF_LOG[x] = i
        x <<= 1
        if x & 0x100:
            x ^= 0x11D
    for i in range(255, 512):
        _GF_EXP[i] = _GF_EXP[i - 255]


_init_gf()


def _gf_mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return _GF_EXP[_GF_LOG[a] + _GF_LOG[b]]


def _rs_generator(degree: int) -> List[int]:
    """Generator polynomial, DESCENDING coefficients (g[0] = leading 1):
    g(x) = ∏ (x + α^i) for i in 0..degree-1."""
    result = [1]
    root = 1
    for _ in range(degree):
        # result *= (x + root)
        new = [0] * (len(result) + 1)
        for i, c in enumerate(result):
            new[i] ^= c                       # c·x
            new[i + 1] ^= _gf_mul(c, root)    # c·root
        result = new
        root = _gf_mul(root, 0x02)            # advance root by α
    return result


def _rs_encode(data: List[int], ec_len: int) -> List[int]:
    """Reed–Solomon remainder via LFSR synthetic division (monic divisor)."""
    divisor = _rs_generator(ec_len)
    result = [0] * ec_len
    for b in data:
        factor = b ^ result.pop(0)
        result.append(0)
        for i in range(ec_len):
            result[i] ^= _gf_mul(divisor[i + 1], factor)  # skip leading 1
    return result


def _bch15(data: int) -> int:
    """BCH(15,5) format bits with mask 0x5412."""
    d = (data << 10) | _bch_remainder(data)
    return ((d ^ 0x5412) & 0x7FFF)


def _bch_remainder(data: int) -> int:
    g = 0b10100110111
    d = data << 10
    for i in range(14, -1, -1):
        if d & (1 << (i + 10)):
            d ^= g << i
    return d & 0x3FF


# Exact ISO/IEC 18004 tables for versions 1–6, EC level L.
# _QR_L[v] = (total_codewords, (ec_per_block, [block_data_lengths]))
_QR_L = {
    1: (19, (7, [19])),
    2: (34, (10, [34])),
    3: (55, (15, [55])),
    4: (80, (20, [80])),
    5: (108, (26, [108])),
    6: (136, (18, [68, 68])),
}
# Alignment pattern center coordinates per version (row/col, besides the
# three finder-corner patterns which are never drawn as alignment).
_QR_ALIGN = {2: [18], 3: [22], 4: [26], 5: [30], 6: [34]}
_MODE4 = 0b0100  # byte mode


def qr_matrix(text: str) -> List[List[bool]]:
    """Encode text (≤ ~128 bytes) as a QR matrix (True = dark), EC level L,
    mask 0. Pure stdlib, exact ISO/IEC 18004 tables for versions 1–6."""
    data = text.encode("utf-8")
    # capacity(v) = sum(block lengths) − 2 header bytes (mode+count)
    version = next((v for v in range(1, 7) if len(data) + 2 <= sum(_QR_L[v][1][1])), 0)
    if not version:
        raise ValueError("text too long for the built-in QR encoder (keep under ~128 bytes)")
    total_cw, (ec_len, block_lens) = _QR_L[version]
    size = 17 + 4 * version

    # --- bit stream: mode(4 bits) + count(8 bits) + data + terminator -----
    bits: List[int] = []
    for i in range(3, -1, -1):
        bits.append((_MODE4 >> i) & 1)
    for i in range(7, -1, -1):
        bits.append((len(data) >> i) & 1)
    for byte in data:
        for i in range(7, -1, -1):
            bits.append((byte >> i) & 1)
    cap_bits = sum(block_lens) * 8
    bits += [0] * min(4, max(0, cap_bits - len(bits)))      # terminator
    while len(bits) % 8:
        bits.append(0)
    pad = [0xEC, 0x11]
    i = 0
    while len(bits) < cap_bits:
        bits += [(pad[i % 2] >> s) & 1 for s in range(7, -1, -1)]
        i += 1
    codewords = [
        bits[j] * 128 + bits[j + 1] * 64 + bits[j + 2] * 32 + bits[j + 3] * 16
        + bits[j + 4] * 8 + bits[j + 5] * 4 + bits[j + 6] * 2 + bits[j + 7]
        for j in range(0, cap_bits, 8)
    ]

    # --- split into blocks, compute EC, interleave -----------------------
    data_blocks: List[List[int]] = []
    pos = 0
    for bl in block_lens:
        data_blocks.append(codewords[pos:pos + bl])
        pos += bl
    ec_blocks = [_rs_encode(db, ec_len) for db in data_blocks]
    final: List[int] = []
    max_len = max(block_lens)
    for i in range(max_len):
        final += [db[i] for db in data_blocks if i < len(db)]
    for i in range(ec_len):
        final += [eb[i] for eb in ec_blocks]
    # remainder bits (v2-6: 7) are zero — nothing to append (bitsFlat pads 0)

    # --- matrix ------------------------------------------------------------
    m: List[List[Optional[bool]]] = [[None] * size for _ in range(size)]

    finder = [
        [True, True, True, True, True, True, True],
        [True, False, False, False, False, False, True],
        [True, False, True, True, True, False, True],
        [True, False, True, True, True, False, True],
        [True, False, True, True, True, False, True],
        [True, False, False, False, False, False, True],
        [True, True, True, True, True, True, True],
    ]

    def stamp(r: int, c: int, pat: List[List[bool]]) -> None:
        for dr, row in enumerate(pat):
            for dc, v in enumerate(row):
                if 0 <= r + dr < size and 0 <= c + dc < size:
                    m[r + dr][c + dc] = v

    def place_finder(r: int, c: int) -> None:
        stamp(r, c, finder)
        # separators (guard to matrix edge — skip out-of-bounds)
        for dc in range(-1, 8):
            if 0 <= c + dc < size:
                if r - 1 >= 0:
                    m[r - 1][c + dc] = False
                if r + 7 < size:
                    m[r + 7][c + dc] = False
        for dr in range(-1, 8):
            if 0 <= r + dr < size:
                if c - 1 >= 0:
                    m[r + dr][c - 1] = False
                if c + 7 < size:
                    m[r + dr][c + 7] = False

    place_finder(0, 0)
    place_finder(0, size - 7)
    place_finder(size - 7, 0)
    # timing patterns
    for i in range(8, size - 8):
        v = (i % 2 == 0)
        m[6][i] = v
        m[i][6] = v
    # alignment pattern(s) — the bottom-right center(s) per version;
    # never inside the three finder corners
    align = [
        [True, True, True, True, True],
        [True, False, False, False, True],
        [True, False, True, False, True],
        [True, False, False, False, True],
        [True, True, True, True, True],
    ]
    for ar in _QR_ALIGN.get(version, []):
        stamp(ar - 2, ar - 2, align)
    # dark module
    m[size - 8][8] = True

    # --- format info: EC level L (01) + mask 0 (00) → data 0b01000 --------
    # Drawn BEFORE data placement — these are function modules.
    fmt_bits = _bch15(0b01000)

    def _fb(i: int) -> bool:
        return bool((fmt_bits >> i) & 1)

    # copy 1 (around the top-left finder; LSB first per ISO 18004)
    for i in range(6):
        m[i][8] = _fb(i)          # down column 8, rows 0-5
    m[7][8] = _fb(6)
    m[8][8] = _fb(7)
    m[8][7] = _fb(8)
    for i in range(9, 15):
        m[8][14 - i] = _fb(i)     # along row 8, cols 5..0
    # copy 2 — split per ISO 18004 / reference libs:
    #   vertical: bits 8..14 up column 8 (rows n-15+i, i.e. bottom 7 rows)
    #   horizontal: bits 0..7 along row 8 (cols n-1-i, rightmost 8)
    for i in range(8, 15):
        m[size - 15 + i][8] = _fb(i)
    for i in range(8):
        m[8][size - 1 - i] = _fb(i)

    # --- place data, mask 0 ((r+c) mod 2 == 0 inverts) ---------------------
    bits_flat: List[int] = []
    for cw in final:
        bits_flat += [(cw >> s) & 1 for s in range(7, -1, -1)]
    bit_i = 0
    c = size - 1
    while c > 0:
        if c == 6:
            c -= 1  # skip timing column
        # direction per column pair per ISO 18004 (NOT a simple toggle):
        upward = ((c + 1) & 2) == 0
        rng = range(size - 1, -1, -1) if upward else range(size)
        for r in rng:
            for cc in (c, c - 1):
                if m[r][cc] is None:
                    bit = bits_flat[bit_i] if bit_i < len(bits_flat) else 0
                    bit_i += 1
                    mask = ((r + cc) % 2) == 0
                    m[r][cc] = bool(bit) ^ mask
        c -= 2

    return [[bool(v) for v in row] for row in m]


def qr_png(text: str, scale: int = 8, quiet: int = 3) -> bytes:
    """Render a QR code to PNG bytes — pure stdlib (no Pillow)."""
    m = qr_matrix(text)
    n = len(m)
    dim = (n + quiet * 2) * scale
    rows = []
    white = b"\x00" * (dim // 8) if dim % 8 == 0 else None
    # build as 1-byte grayscale then expand
    raw = bytearray()
    dark = 0
    light = 255
    for y in range(dim):
        qy = (y // scale) - quiet
        rowbytes = bytearray()
        runs = []
        for x in range(dim):
            qx = (x // scale) - quiet
            on = 0 <= qy < n and 0 <= qx < n and m[qy][qx]
            runs.append(dark if on else light)
        # pack 8-px aligned: simplest — write as RGB instead (3 bytes/px)
        raw += bytes(runs)
    # Build a real 8-bit grayscale PNG
    def chunk(typ: bytes, data: bytes) -> bytes:
        c = struct.pack(">I", len(data)) + typ + data
        return c + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", dim, dim, 8, 0, 0, 0, 0)
    raw2 = bytearray()
    for y in range(dim):
        qy = (y // scale) - quiet
        row = bytearray([0])  # filter 0
        for x in range(dim):
            qx = (x // scale) - quiet
            on = 0 <= qy < n and 0 <= qx < n and m[qy][qx]
            row.append(dark if on else light)
        raw2 += row
    return (
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(bytes(raw2), 9))
        + chunk(b"IEND", b"")
    )


# ---------------------------------------------------------------------------
# Offline phone bridge — LAN/BT-PAN HTTP server + QR
# ---------------------------------------------------------------------------
def local_ip() -> str:
    """Best-effort host LAN address (works offline once an interface is up)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))  # no packet sent; interface probe
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


_BRIDGE_STATE: Dict[str, Any] = {"server": None, "port": 0, "shot": None, "thread": None}


def _bridge_page(ip: str, port: int) -> bytes:
    shot = _BRIDGE_STATE.get("shot")
    img_tag = (
        f'<img id="s" src="screen.png?{int(time.time())}" style="max-width:100%;border-radius:12px">'
        if shot else "<p>No screenshot yet — run /look on the computer.</p>"
    )
    return (
        "<!doctype html><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>claume phone bridge</title>"
        "<style>body{background:#0a0e14;color:#c8d3de;font-family:system-ui;margin:0;padding:16px}"
        "h1{font-size:18px}button{background:#22d3ee;border:0;border-radius:10px;padding:10px 14px;"
        "margin:4px;font-weight:600}pre{background:#0f1520;padding:10px;border-radius:8px;"
        "white-space:pre-wrap;font-size:11px}</style>"
        "<h1>◆ claume phone bridge</h1>"
        f"<p>offline link · {ip}:{port} · refreshes live</p>"
        "<button onclick='location.reload()'>↻ refresh screen</button>"
        "<button onclick=\"fetch('/analyze').then(r=>r.text()).then(t=>alert(t))\">🔍 diagnose screen</button>"
        f"{img_tag}"
        "<p style='color:#5c6b7a'>paired over LAN / Bluetooth PAN — claume needs no internet for this.</p>"
    ).encode("utf-8")


def phone_bridge(port: int = 8765, duration: float = 0.0) -> Dict[str, Any]:
    """Start the offline phone bridge: capture a screen, serve it on LAN,
    return the QR (png path) + URL. duration>0 auto-stops after N seconds
    (0 = runs until process exit / bridge_stop)."""
    from http.server import BaseHTTPRequestHandler, HTTPServer

    shot = capture()
    _BRIDGE_STATE["shot"] = shot

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a: Any) -> None:  # silence
            return

        def do_GET(self) -> None:
            p = urllib.parse.urlparse(self.path).path
            if p == "/screen.png":
                data = (_BRIDGE_STATE.get("shot") or {}).get("path", "")
                body = open(data, "rb").read() if data else b"no screenshot"
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.end_headers()
                self.wfile.write(body)
            elif p == "/analyze":
                analysis, err = look_and_analyze()
                _BRIDGE_STATE["shot"] = capture()  # refresh
                body = analysis.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(body)
            else:
                body = _bridge_page(local_ip(), port)
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(body)

    ip = local_ip()
    url = f"http://{ip}:{port}"
    server = HTTPServer((ip, port), H)
    _BRIDGE_STATE["server"] = server
    _BRIDGE_STATE["port"] = port

    def serve() -> None:
        try:
            server.serve_forever(poll_interval=0.3)
        except Exception:
            pass

    t = threading.Thread(target=serve, name="claume-bridge", daemon=True)
    t.start()
    _BRIDGE_STATE["thread"] = t

    qr_path = ""
    try:
        png = qr_png(url, scale=6)
        p = screens_dir() / f"bridge-qr-{port}.png"
        p.write_bytes(png)
        qr_path = str(p)
    except Exception:
        pass

    out = {"url": url, "qr_path": qr_path, "screenshot": shot.get("path", ""),
           "ip": ip, "port": port, "engine": shot.get("engine", "")}
    if duration > 0:
        def stopper() -> None:
            time.sleep(duration)
            bridge_stop()
        threading.Thread(target=stopper, daemon=True).start()
    return out


def bridge_stop() -> None:
    srv = _BRIDGE_STATE.get("server")
    if srv:
        try:
            srv.shutdown()
        except Exception:
            pass
        _BRIDGE_STATE["server"] = None
