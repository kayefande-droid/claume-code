"""claume webstudio — asset & font pulling + website design briefs.

Gives claume the capability to build human-grade, luxurious website
designs by *pulling real assets* instead of inventing them:

* ``pull_font``       — fetch a Google Fonts CSS + woff2 into the project
* ``pull_asset``      — download any image/logo/illustration URL into assets/
* ``design_brief``    — generate the claume-studio design brief (typography,
                        palette, motion, layout mechanics) for any target site

Tools are registry-bridged (webstudio_pull_font etc.) so the agent can
call them mid-build; the design_brief text is also injected into the
system prompt whenever the task looks design-related, so claume's own
aesthetic language (the one rendered in the /admin studio dashboard)
applies to every website/UI it builds — its own site or a user's.
"""
from __future__ import annotations

import re
import urllib.request
from pathlib import Path
from typing import List, Tuple

from . import config

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

# The claume studio design language (mirrors claume/proxy_ui.py).
STUDIO_BRIEF = """\
TYPOGRAPHY (pull from Google Fonts — never substitute system fonts):
  Display  : Fraunces (opsz 9..144, weights 300-700) — editorial serif; italics for emphasis
  UI       : Space Grotesk (300-700) — interface, labels, buttons, nav
  Code/Data: JetBrains Mono (400/500/700) — code, kickers, data tables

PALETTE:
  bg #060807 · panel #0b0f0a -> #10160e gradient · hairlines #1c2418 / #2a3522
  text #e9f2e4 · dim #7d8a76 · accent nvidia-green #76b900 · lime #b7f04a
  mint #7ef0c0 · gold #e3b341 · danger #f85149

MORPHISM RECIPE (pick ONE for the whole build — do not mix):
  GLASSMORPHISM  translucent panels (rgba(20,28,20,.55)-rgba(12,16,10,.7)),
    soft colored glow borders (box-shadow: 0 0 0 1px rgba(118,185,0,.25),
    0 8px 32px rgba(0,0,0,.45)), layered blurred gradient backgrounds,
    14-18px radii, inner hairline borders. Used when the brief says
    'glass', 'translucent', 'modern saas'.
  NEUMORPHISM   soft extruded shadows both sides (shadow: 9px 9px 18px
    rgba(0,0,0,.35), -9px -9px 18px rgba(255,255,255,.04)), low-contrast
    near-monochrome surfaces, barely-visible raised/indented states, 12-16px
    radii. Used when the brief says 'neumorphic', 'soft', 'minimal tactile'.
  CLAYMORPHISM  pill + card shapes (border-radius 18-24px), soft diffuse
    shadows (0 10px 30px rgba(0,0,0,.25)), barely-there borders, friendly warm
    palette, soft gradient fills on buttons, 14-16px radii. Used when the
    brief says 'clay', 'friendly', 'playful', 'dashboard consumer app'.
  DEFAULT        glass-depth cards (the claume-studio signature below) when the
    brief gives no morphism cue.

LAYOUT MECHANICS (the claume-studio signature):
  - kicker labels: mono 11px, 0.32em letter-spacing, uppercase, green accents
  - numbered sections (01 / 02 / 03) with large serif H2s (-0.01em tracking)
  - explode-view hero: 3 stacked layer-cards, perspective 1100px, hover
    separates layers on Z (translateZ 70/24/-24) with cubic-bezier(.19,1,.22,1)
  - glass-depth cards: 165deg panel gradient, 1px hairline borders,
    0 18px 40px rgba(0,0,0,.4) shadows, 14-16px radii
  - status pills with pulsing 7px glow-dots (animation pulse 2.4s)
  - data tables: mono 12px, hairline rows, uppercase micro-headers

MOTION:
  - staggered explodeIn on load (0.05s / 0.2s / 0.35s delays)
  - spring hovers (translateY -4 to -8px), scale(.98) on :active
  - smooth-scroll anchors; Framer Motion for React builds

ASSETS:
  - pull real icons (Phosphor/Lucide) and hero textures — never gray boxes
  - aurora canvas shader or gradient-radial fields for background depth
  - favicon: claume pixel-bot motif
  - when you need an icon/hero/background, call design_generate_icon or
    design_generate_asset first to get a spec / artist prompt, then render it
    or use the spec as the CSS illustration brief
"""

_DESIGN_WORDS = (
    "website", "web site", "landing", "portfolio", "site", "page", "ui",
    "ux", "dashboard", "hero", "design", "html", "css", "tailwind",
    "react", "next", "web app", "frontend", "front-end", "bento", "blog",
)


def is_design_task(user_text: str) -> bool:
    low = (user_text or "").lower()
    return any(w in low for w in _DESIGN_WORDS)


# ---------------------------------------------------------------------------
# Google Fonts pulling
# ---------------------------------------------------------------------------
_GOOGLE_FONTS_KNOWN = {
    "fraunces", "space grotesk", "jetbrains mono", "inter", "playfair display",
    "cormorant garamond", "manrope", "sora", "outfit", "dm sans", "ibm plex mono",
    "instrument serif", "newsreader", "spectral", "libre caslon text", "eb garamond",
}


def pull_font(workspace: Path, family: str, weights: str = "300;400;600;700") -> Tuple[str, bool]:
    """Fetch a Google Fonts stylesheet + woff2 files into <workspace>/assets/fonts."""
    family = (family or "").strip()
    if not family:
        return "error: font family required (e.g. 'Fraunces')", True
    fam_api = family.strip().replace(" ", "+")
    url = f"https://fonts.googleapis.com/css2?family={fam_api}:wght@{weights}&display=swap"
    dest_dir = workspace / "assets" / "fonts"
    dest_dir.mkdir(parents=True, exist_ok=True)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=30) as resp:
            css = resp.read().decode("utf-8", "replace")
    except Exception as exc:
        return f"error: could not fetch Google Fonts CSS for '{family}': {exc}", True

    # Download each woff2 referenced by the CSS and rewrite URLs to local files.
    # NOTE: group(2) is the URL — group(1) is the optional quote character.
    seen: List[Tuple[str, str]] = []
    failures = {"n": 0}

    def _dl(match: re.Match) -> str:
        remote = match.group(2)
        if remote in dict(seen):
            return f"url('{dict(seen)[remote]}')"
        fname = remote.rsplit("/", 1)[-1].split("?")[0]
        if not fname.endswith(".woff2"):
            fname = f"{family.replace(' ', '')}-{len(seen)}.woff2"
        try:
            req2 = urllib.request.Request(remote, headers={"User-Agent": _USER_AGENT})
            with urllib.request.urlopen(req2, timeout=30) as r2:
                (dest_dir / fname).write_bytes(r2.read())
            seen.append((remote, fname))
            return f"url('{fname}')"
        except Exception:
            failures["n"] += 1
            return match.group(0)  # keep remote URL as fallback

    css_local = re.sub(r"url\((['\"]?)(https://fonts\.gstatic\.com/[^'\"]+)\1\)", _dl, css)
    css_path = dest_dir / f"{family.replace(' ', '-').lower()}.css"
    css_path.write_text(css_local, encoding="utf-8")
    is_err = len(seen) == 0 and failures["n"] > 0
    note = (
        f"font '{family}' saved: {css_path.name} + {len(seen)} woff2 file(s) locally"
        + (f" ({failures['n']} download(s) failed — those keep remote URLs)" if failures["n"] else "")
        + f" in assets/fonts/\n"
        f"Link it with: <link rel=\"stylesheet\" href=\"assets/fonts/{css_path.name}\">"
    )
    return note, is_err


# ---------------------------------------------------------------------------
# Generic asset pulling
# ---------------------------------------------------------------------------
def pull_asset(workspace: Path, url: str, name: str = "") -> Tuple[str, bool]:
    """Download an asset (image/logo/svg/illustration) into <workspace>/assets/."""
    url = (url or "").strip()
    if not url.startswith(("http://", "https://")):
        return "error: url must start with http(s)://", True
    fname = (name or "").strip() or url.rsplit("/", 1)[-1].split("?")[0] or "asset.bin"
    fname = re.sub(r"[^A-Za-z0-9._-]", "_", fname)
    dest_dir = workspace / "assets"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / fname
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=45) as resp:
            data = resp.read()
        dest.write_bytes(data)
    except Exception as exc:
        return f"error: download failed for {url}: {exc}", True
    kb = max(1, len(data) // 1024)
    return f"asset saved: assets/{fname} ({kb} KB) — reference it as assets/{fname}", False


def studio_brief(target: str = "") -> Tuple[str, bool]:
    """Return the claume-studio design brief, scoped to a target."""
    head = f"CLAUME STUDIO DESIGN BRIEF — target: {target or 'claume website'}"
    rule = "=" * min(72, len(head) + 4)
    tail = (
        "\n\nApply this brief to EVERY page/section of the build. Pull the exact fonts "
        "with webstudio_pull_font, pull real assets with webstudio_pull_asset, and use the "
        "Link System MCP pipeline (layout → components → motion → canvas) when available. "
        "No placeholder divs, no lorem ipsum, no gray boxes."
    )
    return f"{rule}\n{head}\n{rule}\n\n{STUDIO_BRIEF}{tail}", False
