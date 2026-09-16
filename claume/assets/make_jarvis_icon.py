"""Generate jarvis.ico — the claume jarvis desktop app icon.

Pure stdlib: renders the arc-reactor orb (glowing cyan core, dark ring,
outer halo) pixel-by-pixel and packs it as a Windows .ico containing
16/32/48/256 px BMP-format entries. Run once from the repo root:

    python claume/assets/make_jarvis_icon.py
"""
from __future__ import annotations

import math
import struct
import sys
from pathlib import Path

SIZES = (16, 32, 48, 256)

# palette
BG = (10, 14, 20, 0)          # transparent outside the tile
HALO = (14, 91, 216, 90)      # deep blue halo
RING_DARK = (18, 26, 38, 255)
CYAN = (34, 211, 238, 255)
CYAN_HOT = (165, 243, 252, 255)
GAP = (10, 14, 20, 255)       # panel color between core and ring


def _clamp(v: int) -> int:
    return max(0, min(255, int(v)))


def render(size: int) -> bytes:
    """BGRA rows, top-down (BMP payload of the ICO entry)."""
    px = bytearray()
    c = size / 2.0
    r_out = size * 0.46          # outer ring
    r_ring_w = size * 0.10
    r_gap = size * 0.06
    r_core = size * 0.24
    for y in range(size):
        for x in range(size):
            d = math.hypot(x + 0.5 - c, y + 0.5 - c)
            # concentric zones
            if d > r_out:
                px += bytes(BG)
                continue
            if d > r_out - r_ring_w:
                # ring: faint radial shine
                t = (d - (r_out - r_ring_w)) / r_ring_w
                col = (18 + 10 * (1 - t), 26 + 12 * (1 - t), 38 + 14 * (1 - t), 255)
                px += bytes(_clamp(v) for v in col)
                continue
            if d > r_out - r_ring_w - r_gap:
                px += bytes(GAP)
                continue
            # core: radial gradient white-hot center → cyan edge
            t = d / max(r_core, 0.001)
            col = tuple(
                _clamp(CYAN_HOT[i] * (1 - t) + CYAN[i] * t) for i in range(3)
            ) + (255,)
            px += bytes(col)
    # AND mask (all zeros = rely on alpha)
    px += bytes(((size + 15) // 16) * 2 * size)
    return bytes(px)


def bmp_header(size: int, payload_len: int) -> bytes:
    """BITMAPINFOHEADER for an ICO entry (height = 2× size)."""
    return struct.pack(
        "<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0, payload_len, 0, 0, 0, 0
    )


def build() -> bytes:
    images = []
    for s in SIZES:
        payload = render(s)
        header = bmp_header(s, len(payload))
        images.append((s, header + payload))
    out = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries = b""
    for s, data in images:
        w = s if s < 256 else 0
        entries += struct.pack(
            "<BBBBHHII", w, w, 0, 0, 1, 32, len(data), offset
        )
        offset += len(data)
    return out + entries + b"".join(d for _, d in images)


def main() -> int:
    dest = Path(__file__).resolve().parent / "jarvis.ico"
    dest.write_bytes(build())
    print(f"wrote {dest} ({dest.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
