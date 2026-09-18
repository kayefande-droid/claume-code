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
# Offline phone bridge — LAN/BT-PAN HTTP(S) server + QR
#
# Two-way live cast + file transfer ("phone link" style) over the local
# network or a Bluetooth PAN pairing — NO internet needed:
#   PC    -> phone : /stream.mjpeg live screen cast (plain HTTP, any browser)
#   phone -> PC    : camera/screen cast via /phone.frame POST (needs HTTPS
#                    for getUserMedia/getDisplayMedia — shown when a cert
#                    exists) rendered in the PC-side tkinter viewer
#   files both ways: /files listing, /download/<name>, POST /upload,
#                    /delete — a two-way AirDrop-style exchange
# Transports: WiFi/LAN when both devices share a network (preferred, fast),
# Bluetooth PAN otherwise (phone hotspot/PAN pairing — slower but offline).
# The server binds 0.0.0.0 so BOTH transports work simultaneously; each gets
# its own QR code (bridge-qr-wifi-<port>.png / bridge-qr-bluetooth-<port>.png).
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


# ---------------------------------------------------------------------------
# Transport selection — WiFi (same network) preferred, Bluetooth PAN fallback
# ---------------------------------------------------------------------------
def _iface_ips() -> List[str]:
    """All IPv4 addresses of this machine (WiFi, Ethernet, BT-PAN, ...)."""
    ips: List[str] = []
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
        for info in infos:
            ip = info[4][0]
            if ip not in ips and not ip.startswith("127."):
                ips.append(ip)
    except Exception:
        pass
    probe = local_ip()
    if probe not in ips and not probe.startswith("127."):
        ips.append(probe)
    return ips


def bluetooth_pan_ip() -> str:
    """Local IPv4 of the Bluetooth PAN adapter, "" if none is paired/up.
    Windows: the 'Bluetooth Network Connection' shows up in ipconfig.
    Linux: bt-pan/bluez exposes bnep0. macOS: Bluetooth PAN interface."""
    import re as _re

    import subprocess as _sp
    try:
        if os.name == "nt":
            out = _sp.run(["ipconfig"], capture_output=True, text=True, timeout=6).stdout
            # adapter block ends with the IPv4 line
            blocks = _re.split(r"\n\s*\n", out)
            for block in blocks:
                if _re.search(r"bluetooth", block, _re.IGNORECASE):
                    m = _re.search(r"IPv4[^:\n]*:\s*([0-9.]+)", block)
                    if m:
                        return m.group(1)
        elif os.name == "posix":
            out = _sp.run(["ip", "-4", "addr"], capture_output=True, text=True,
                          timeout=6).stdout
            for block in out.split("\n"):
                if "bnep" in block or "btpan" in block:
                    m = _re.search(r"inet\s+([0-9.]+)", block)
                    if m:
                        return m.group(1)
    except Exception:
        pass
    return ""


def wifi_link_active() -> bool:
    """True when a WiFi adapter is connected (or, as a fallback, when any
    non-loopback IPv4 exists — i.e. we are on some LAN)."""
    import subprocess as _sp
    try:
        if os.name == "nt":
            out = _sp.run(["netsh", "wlan", "show", "interfaces"],
                          capture_output=True, text=True, timeout=6).stdout
            if "state" in out.lower():
                return "connected" in out.lower()
    except Exception:
        pass
    return bool(_iface_ips())


def same_subnet(a: str, b: str) -> bool:
    """/24 membership — good enough for home & phone-hotspot networks."""
    try:
        ka = tuple(int(x) for x in a.split("."))
        kb = tuple(int(x) for x in b.split("."))
        return ka[:3] == kb[:3]
    except Exception:
        return False


def pick_transport() -> Tuple[str, str]:
    """Choose the URL base for the QR: WiFi/LAN when a WiFi link is up,
    Bluetooth PAN otherwise. Returns (ip, transport)."""
    bt = bluetooth_pan_ip()
    lan = local_ip()
    if lan.startswith("127.") and bt:
        return bt, "bluetooth"
    if wifi_link_active() or not bt:
        return lan, "wifi"
    return bt, "bluetooth"


_BRIDGE_STATE: Dict[str, Any] = {
    "server": None,
    "port": 0,
    "shot": None,
    "thread": None,
    "live": False,           # PC->phone MJPEG casting toggle
    "phone_frames": None,    # deque of jpeg bytes from the phone cast
    "viewer": None,          # PC-side tkinter viewer root (or None)
    "https": False,
    "urls": {},              # transport -> url ("wifi", "bluetooth")
}


def _bridge_frame_jpeg(max_w: int = 1100) -> bytes:
    """One fresh screen frame as JPEG. mss+Pillow when installed, else the
    slower GDI PNG bytes (browsers render PNG inside MJPEG poorly, but the
    fallback still streams — Pillow makes it a true JPEG)."""
    try:
        import io as _io

        import mss  # type: ignore
        from PIL import Image  # type: ignore

        with mss.mss() as sct:
            mon = sct.monitors[1]
            shot = sct.grab(mon)
        img = Image.frombytes("RGB", shot.size, shot.rgb)
        if img.width > max_w:
            img = img.resize((max_w, int(img.height * max_w / img.width)))
        buf = _io.BytesIO()
        img.save(buf, "JPEG", quality=62)
        return buf.getvalue()
    except Exception:
        return _capture_windows_gdi()


def _bridge_page(ip: str, port: int, https: bool = False) -> bytes:
    scheme = "https" if https else "http"
    secure_block = (
        "<div id='sec' style='display:none'>"
        "<button id='camBtn' class='sec'>&#127909; cast my camera to the PC</button>"
        "<button id='scrBtn' class='sec'>&#128421; cast my phone screen to the PC</button>"
        "<video id='v' autoplay playsinline muted style='max-width:100%;border-radius:12px'></video>"
        "</div>"
        if https
        else "<p class='muted'>&#128274; phone->PC casting needs HTTPS; add "
        "'cryptography' (pip install cryptography) and restart the bridge to enable it.</p>"
    )
    return (
        "<!doctype html><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>claume bridge &middot; {ip}:{port}</title>"
        "<style>body{background:#0a0e14;color:#c8d3de;font-family:system-ui;margin:0;padding:16px}"
        "h1{font-size:18px;margin:4px 0}button{background:#22d3ee;color:#04202a;border:0;border-radius:10px;"
        "padding:11px 16px;margin:4px 4px 4px 0;font-weight:700;font-size:14px}"
        "button.sec{background:#134e4a;color:#7df3ff}"
        "input{font-size:14px;padding:8px;border-radius:8px;border:1px solid #2a3644;"
        "background:#0f1520;color:#c8d3de}"
        "img,video{max-width:100%;border-radius:12px;margin-top:10px}"
        "li{margin:4px 0}a{color:#22d3ee}.muted{color:#5c6b7a;font-size:12px}</style>"
        "<h1>&#9670; claume bridge</h1>"
        f"<p class='muted'>{scheme} &middot; {ip}:{port} &middot; offline LAN/BT-PAN link</p>"
        "<button onclick=\"document.getElementById('pc').src='/stream.mjpeg'\">&#9654; cast PC screen (live)</button>"
        "<button onclick=\"document.getElementById('pc').src=''\">&#9632; stop</button>"
        "<img id='pc' alt='PC screen cast appears here'>"
        + secure_block +
        "<h2 style='font-size:15px'>Files</h2>"
        "<input type='file' id='f' multiple> <button onclick='up()'>&#11014; send to PC</button>"
        "<div id='msg' class='muted'></div>"
        "<ul id='list'></ul>"
        "<script>"
        "async function up(){const fl=document.getElementById('f').files;"
        "const m=document.getElementById('msg');"
        "if(!fl.length){m.textContent='pick files first';return}"
        "for(const file of fl){m.textContent='sending '+file.name+'...';"
        "await fetch('/upload?name='+encodeURIComponent(file.name),"
        "{method:'POST',body:await file.arrayBuffer()});}"
        "m.textContent='sent OK';location.reload()}"
        "fetch('/files').then(r=>r.json()).then(l=>{"
        "document.getElementById('list').innerHTML=l.map(n=>"
        "\"<li><a href='/download/\"+encodeURIComponent(n)+\"'>&#11015; \"+n+\"</a> \"+"
        "\"<a style='color:#f87171' href='#' onclick=\\\"del('\"+encodeURIComponent(n)+\"')\\\">del</a></li>\")"
        ".join('')});"
        "function del(n){fetch('/delete?name='+n).then(()=>location.reload())}"
        "if(location.protocol==='https:'){"
        "document.getElementById('sec').style.display='block';"
        "const v=document.getElementById('v');"
        "const grab=async g=>{const s=await g();v.srcObject=s;post(s)};"
        "document.getElementById('camBtn').onclick=()=>"
        "grab(()=>navigator.mediaDevices.getUserMedia({video:{facingMode:'environment'}}));"
        "document.getElementById('scrBtn').onclick=()=>"
        "grab(()=>navigator.mediaDevices.getDisplayMedia({video:true}));"
        "function post(s){const tc=document.createElement('canvas');"
        "const ctx=tc.getContext('2d');let busy=false;"
        "s.getVideoTracks()[0].onended=()=>{fetch('/phone.stop');v.srcObject=null};"
        "setInterval(async()=>{if(busy||!v.videoWidth)return;busy=true;"
        "tc.width=640;tc.height=Math.round(640*v.videoHeight/v.videoWidth);"
        "ctx.drawImage(v,0,0,tc.width,tc.height);"
        "tc.toBlob(async b=>{if(b)await fetch('/phone.frame',{method:'POST',body:b});"
        "busy=false},'image/jpeg',0.6)},250)}}"
        "</script>"
    ).encode("utf-8")


def _bridge_inbox() -> Path:
    d = config.claume_dir() / "bridge_inbox"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _start_phone_viewer() -> None:
    """PC-side tkinter viewer for the phone cast (stdlib; Pillow optional)."""
    if _BRIDGE_STATE.get("viewer"):
        return
    try:
        import tkinter as tk
    except Exception:
        return

    root = tk.Tk()
    root.title("claume bridge - phone cast")
    root.configure(bg="#0a0e14")
    root.geometry("720x560")
    lbl = tk.Label(root, bg="#0a0e14", fg="#22d3ee",
                   text="waiting for the phone cast...", font=("Consolas", 11))
    lbl.pack(expand=True, fill="both")

    def poll() -> None:
        frames = _BRIDGE_STATE.get("phone_frames")
        fr = frames[-1] if frames else None
        if fr:
            try:
                from PIL import Image, ImageTk  # type: ignore

                img = Image.open(io.BytesIO(fr))
                w, h = img.size
                maxw = max(root.winfo_width() - 20, 200)
                if w > maxw:
                    img = img.resize((maxw, int(h * maxw / w)))
                photo = ImageTk.PhotoImage(img)
                lbl.configure(image=photo, text="")
                lbl.image = photo  # hold a reference
            except Exception:
                lbl.configure(text="phone casting... (install Pillow for video)")
        root.after(120, poll)

    def close() -> None:
        _BRIDGE_STATE["viewer"] = None
        root.destroy()

    poll()
    root.protocol("WM_DELETE_WINDOW", close)
    _BRIDGE_STATE["viewer"] = root
    threading.Thread(target=root.mainloop, daemon=True).start()


def phone_bridge(port: int = 8765, duration: float = 0.0, open_viewer: bool = True) -> Dict[str, Any]:
    """Start the offline two-way phone bridge (live cast both ways + file
    transfer). Returns {url, qr_path, ip, port, https, screenshot}.
    duration>0 auto-stops after N seconds (0 = until bridge_stop/exit)."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    shot = capture()
    _BRIDGE_STATE["shot"] = shot
    import collections

    frames = collections.deque(maxlen=3)
    _BRIDGE_STATE["phone_frames"] = frames
    _BRIDGE_STATE["live"] = False
    inbox = _bridge_inbox()

    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a: Any) -> None:
            return

        def _hdrs(self, typ: str, length: int = -1, cache: str = "no-store") -> None:
            self.send_response(200)
            self.send_header("Content-Type", typ)
            if length >= 0:
                self.send_header("Content-Length", str(length))
            self.send_header("Cache-Control", cache)
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            p = urllib.parse.urlparse(self.path).path
            if p == "/screen.png":
                data = (_BRIDGE_STATE.get("shot") or {}).get("path", "")
                body = open(data, "rb").read() if data else b"no screenshot"
                self._hdrs("image/png", len(body))
                self.wfile.write(body)
            elif p == "/stream.mjpeg":
                # LIVE PC -> phone screen cast (multipart JPEG)
                _BRIDGE_STATE["live"] = True
                self.send_response(200)
                self.send_header("Content-Type",
                                 "multipart/x-mixed-replace; boundary=frame")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                try:
                    while _BRIDGE_STATE["live"]:
                        jpg = _bridge_frame_jpeg()
                        if not jpg:
                            break
                        self.wfile.write(
                            b"--frame\r\nContent-Type: image/jpeg\r\n"
                            + b"Content-Length: " + str(len(jpg)).encode()
                            + b"\r\n\r\n" + jpg + b"\r\n"
                        )
                        time.sleep(0.18)
                except Exception:
                    pass
                finally:
                    _BRIDGE_STATE["live"] = False
            elif p == "/files":
                names = sorted(x.name for x in inbox.iterdir() if x.is_file())
                body = json.dumps(names).encode()
                self._hdrs("application/json", len(body))
                self.wfile.write(body)
            elif p.startswith("/download/"):
                name = Path(urllib.parse.unquote(p[len("/download/"):])).name
                f = inbox / name
                if f.is_file():
                    body = f.read_bytes()
                    self._hdrs("application/octet-stream", len(body), "")
                    self.wfile.write(body)
                else:
                    self.send_error(404)
            elif p == "/delete":
                q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                name = Path(urllib.parse.unquote(q.get("name", [""])[0])).name
                (inbox / name).unlink(missing_ok=True)
                self._hdrs("text/plain", 2)
                self.wfile.write(b"ok")
            elif p == "/phone.stop":
                frames.clear()
                self.send_response(204)
                self.send_header("Content-Length", "0")
                self.end_headers()
            elif p == "/qr.png":
                q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                net = q.get("net", [""])[0]
                url_for = (_BRIDGE_STATE.get("urls") or {}).get(net) \
                    or f"http://{local_ip()}:{_BRIDGE_STATE['port']}"
                png = qr_png(url_for, scale=6)
                self._hdrs("image/png", len(png))
                self.wfile.write(png)
            else:
                body = _bridge_page(local_ip(), _BRIDGE_STATE["port"], _BRIDGE_STATE["https"])
                self._hdrs("text/html", len(body))
                self.wfile.write(body)

        def do_POST(self) -> None:  # noqa: N802
            p = urllib.parse.urlparse(self.path).path
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            if p == "/upload":
                q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                name = Path(urllib.parse.unquote(q.get("name", ["file"])[0])).name
                (inbox / name).write_bytes(body)
                self._hdrs("text/plain", 2)
                self.wfile.write(b"ok")
            elif p == "/phone.frame":
                frames.append(body)
                if open_viewer:
                    _start_phone_viewer()
                self._hdrs("text/plain", 2)
                self.wfile.write(b"ok")
            else:
                self.send_error(404)

    ip = local_ip()
    bt_ip = bluetooth_pan_ip()
    # Bind all interfaces so BOTH the WiFi/LAN address and the Bluetooth PAN
    # address (when a PAN pairing exists) reach the same server.
    server = ThreadingHTTPServer(("0.0.0.0", port), H)
    _BRIDGE_STATE["server"] = server
    _BRIDGE_STATE["port"] = port

    # HTTPS upgrade (self-signed) so the phone page can use getUserMedia /
    # getDisplayMedia for phone->PC casting. Optional dependency.
    https = False
    try:
        import datetime as _dt
        from ipaddress import ip_address

        from cryptography import x509  # type: ignore
        from cryptography.hazmat.primitives import hashes, serialization  # type: ignore
        from cryptography.hazmat.primitives.asymmetric import rsa  # type: ignore
        from cryptography.x509.oid import NameOID  # type: ignore

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "claume-bridge")])
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(_dt.datetime.now(_dt.timezone.utc))
            .not_valid_after(_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(days=365))
            .add_extension(
                x509.SubjectAlternativeName(
                    [x509.DNSName("claume-bridge.local")]
                    + [x509.IPAddress(ip_address(a)) for a in {ip, bt_ip} if a]
                ),
                critical=False,
            )
            .sign(key, hashes.SHA256())
        )
        cert_dir = config.claume_dir() / "certs"
        cert_dir.mkdir(parents=True, exist_ok=True)
        key_pem = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
        (cert_dir / "bridge-key.pem").write_bytes(key_pem)
        (cert_dir / "bridge-cert.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        import ssl as _ssl

        ctx = _ssl.SSLContext(_ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(str(cert_dir / "bridge-cert.pem"), str(cert_dir / "bridge-key.pem"))
        server.socket = ctx.wrap_socket(server.socket, server_side=True)
        https = True
    except Exception:
        https = False

    _BRIDGE_STATE["https"] = https
    scheme = "https" if https else "http"
    url = f"{scheme}://{ip}:{port}"
    urls: Dict[str, str] = {"wifi": url}
    if bt_ip:
        urls["bluetooth"] = f"{scheme}://{bt_ip}:{port}"
    _BRIDGE_STATE["urls"] = urls

    def serve() -> None:
        try:
            server.serve_forever(poll_interval=0.3)
        except Exception:
            pass

    t = threading.Thread(target=serve, name="claume-bridge", daemon=True)
    t.start()
    _BRIDGE_STATE["thread"] = t

    qr_path = ""
    qr_paths: Dict[str, str] = {}
    try:
        for net, u in urls.items():
            png = qr_png(u, scale=6)
            p = screens_dir() / f"bridge-qr-{net}-{port}.png"
            p.write_bytes(png)
            qr_paths[net] = str(p)
        qr_path = qr_paths.get("wifi", next(iter(qr_paths.values()), ""))
    except Exception:
        pass

    out = {"url": url, "qr_path": qr_path, "qr_paths": qr_paths,
           "urls": urls, "transport": "wifi" if wifi_link_active() else "bluetooth",
           "bluetooth_pan_ip": bt_ip,
           "screenshot": shot.get("path", ""),
           "ip": ip, "port": port, "engine": shot.get("engine", ""), "https": https}
    if duration > 0:
        def stopper() -> None:
            time.sleep(duration)
            bridge_stop()
        threading.Thread(target=stopper, daemon=True).start()
    return out


def bridge_stop() -> None:
    _BRIDGE_STATE["live"] = False
    srv = _BRIDGE_STATE.get("server")
    if srv:
        try:
            srv.shutdown()
        except Exception:
            pass
        _BRIDGE_STATE["server"] = None
    frames = _BRIDGE_STATE.get("phone_frames")
    if frames is not None:
        frames.clear()
    v = _BRIDGE_STATE.get("viewer")
    if v:
        try:
            v.after(0, v.destroy)
        except Exception:
            pass
        _BRIDGE_STATE["viewer"] = None
