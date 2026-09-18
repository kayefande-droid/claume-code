"""Skills manager for claume.

A "skill" is a GitHub repo (or local folder) containing instruction
markdown (SKILL.md / *.md) and optionally runnable scripts. claume:

* clones the repo into ~/.claume/skills/<name>  (/skill owner/repo)
* indexes every .md file as instruction docs and every script as a
  runnable command (/skills, /skill-use, /skill-run)
* injects the active skills' instructions into the agent's system
  context so the model "adopts" the skill — like the ui-ux-pro-max
  skill from GitHub

Skills can be toggled active/inactive (/skill-on, /skill-off), and the
agent context can include all active skills (/skill-all → auto) or one
specific skill (/skill-use <name>).
"""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import config

MANIFEST = "skill-manifest.json"

DESIGN_REPO_FAMILY = [
    ("awesome-design-md",   "https://github.com/VoltAgent/awesome-design-md.git"),
    ("ai-logo-studio",      "https://github.com/SamurAIGPT/ai-logo-studio.git"),
    ("image-generator",      "https://github.com/ChanMeng666/image-generator.git"),
    ("LVGL-AI-Studio",      "https://github.com/dazeb/LVGL-AI-Studio.git"),
]


def _repo_url_for_name(name: str) -> Optional[str]:
    for n, url in DESIGN_REPO_FAMILY:
        if n == name:
            return url
    return None
# Files that carry the skill's instruction payload.
DOC_NAMES = ("SKILL.md", "skill.md", "Skill.md", "README.md")


def skills_root() -> Path:
    d = config.skills_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# Install / remove
# ---------------------------------------------------------------------------
def install_from_github(repo: str, on_progress=None) -> Tuple[bool, str]:
    """Clone owner/repo into the skills dir. Returns (ok, message)."""
    repo = repo.strip().rstrip("/")
    if repo.count("/") < 1:
        return False, "repo must be owner/repo or a full https URL"
    if repo.startswith("http"):
        name = repo.rstrip("/").split("/")[-1]
        url = repo
    else:
        name = repo.split("/")[-1]
        url = f"https://github.com/{repo}"
    dest = skills_root() / name
    if dest.exists():
        try:
            import shutil

            shutil.rmtree(dest)
        except Exception as exc:
            return False, f"could not replace existing skill: {exc}"
    rc = subprocess.call(
        ["git", "clone", "--depth", "1", url, str(dest)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if rc != 0:
        return False, f"git clone failed for {url}"
    _write_manifest(dest, {"repo": repo, "installed": time.time()})
    docs, scripts = index_skill(dest)
    return True, f"installed '{name}' — {len(docs)} instruction doc(s), {len(scripts)} script(s)"


def _write_manifest(skill_dir: Path, data: Dict[str, Any]) -> None:
    try:
        (skill_dir / MANIFEST).write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass


def read_manifest(skill_dir: Path) -> Dict[str, Any]:
    try:
        return json.loads((skill_dir / MANIFEST).read_text(encoding="utf-8"))
    except Exception:
        return {}


def remove_skill(name: str) -> bool:
    d = skills_root() / name
    if not d.exists():
        return False
    import shutil

    shutil.rmtree(d, ignore_errors=True)
    return True


# ---------------------------------------------------------------------------
# Indexing: docs + scripts
# ---------------------------------------------------------------------------
def index_skill(skill_dir: Path) -> Tuple[List[Path], List[Path]]:
    """Return (markdown docs, runnable scripts) for a skill directory.

    Scripts = .py/.sh/.ps1/.js files under scripts/ or bin/ or cli/ dirs,
    plus any *.py/*.sh at the root that look executable.
    """
    docs: List[Path] = []
    scripts: List[Path] = []
    for p in sorted(skill_dir.rglob("*.md")):
        docs.append(p)
    script_exts = {".py", ".sh", ".ps1", ".js"}
    for p in sorted(skill_dir.rglob("*")):
        if not p.is_file() or p.suffix not in script_exts:
            continue
        rel = p.relative_to(skill_dir).parts
        if any(part in ("scripts", "bin", "cli") for part in rel[:-1]):
            scripts.append(p)
    return docs, scripts


def find_doc(skill_dir: Path) -> Optional[Path]:
    """The skill's main instruction file: SKILL.md > README.md > first .md."""
    for name in DOC_NAMES:
        for p in skill_dir.rglob(name):
            if p.is_file():
                return p
    docs, _ = index_skill(skill_dir)
    return docs[0] if docs else None


def list_skills() -> List[Dict[str, Any]]:
    """All installed skills with status: [{name, docs, scripts, active, desc}]."""
    out: List[Dict[str, Any]] = []
    cfg = config.Config()
    active_map = cfg.get("skills_active", {}) or {}
    for d in sorted(skills_root().iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue
        docs, scripts = index_skill(d)
        doc = find_doc(d)
        desc = ""
        if doc:
            try:
                in_frontmatter = False
                for line in doc.read_text(encoding="utf-8", errors="replace").splitlines():
                    stripped = line.strip()
                    if stripped == "---":
                        in_frontmatter = not in_frontmatter
                        continue
                    if in_frontmatter:
                        # YAML frontmatter: prefer the 'description:' field
                        if stripped.lower().startswith("description:"):
                            desc = stripped.split(":", 1)[1].strip().strip('"\'')[:80]
                            break
                        continue
                    if stripped.startswith("# "):
                        desc = stripped[2:].strip()
                        break
                    if stripped and not stripped.startswith("<!--"):
                        desc = stripped[:80]
                        break
            except Exception:
                pass
        out.append(
            {
                "name": d.name,
                "docs": len(docs),
                "scripts": len(scripts),
                "active": bool(active_map.get(d.name, False)),
                "desc": desc[:80],
            }
        )
    return out


def set_active(name: str, active: bool) -> bool:
    cfg = config.Config()
    skills = {s["name"] for s in list_skills()}
    if name not in skills:
        return False
    m = cfg.get("skills_active", {}) or {}
    m[name] = active
    cfg.set("skills_active", m)
    return True


def set_all_active(active: bool) -> int:
    cfg = config.Config()
    m: Dict[str, bool] = {}
    for s in list_skills():
        m[s["name"]] = active
    cfg.set("skills_active", m)
    return len(m)


# Skill folders pre-seeded with the install (bundled in the repo under
# skills/ and copied into ~/.claume/skills on first run).
# v3 — the full design/agent pack ships bundled:
#   ui-ux-pro-max  flagship design search (145 docs, CSV ranking engine)
#   taste-skill    aesthetic taste research: brandkit, brutalist,
#                  minimalist, redesign, stitch sub-skills + scripts
#   awesome-claude-design   curated design-technique reference (VoltAgent)
#   design-md-chrome        DESIGN.md design-system authoring framework
#   design-motion-principles  motion/animation principles (Framer-grade)
#   claudex-loop   cross-agent plan→build→review loop discipline
#   agency-agents  100+ role-specific agent instruction sheets
#   system-prompts-leaks    transposed Claude/Fable prompt techniques
# Plus the design-repo family — installed as default-active skills so
# claume can draw real design structure, icons, images and LVGL-style
# composable UI patterns from these repos in every build:
#   awesome-design-md      VoltAgent design-technique reference repo
#   ai-logo-studio         SamurAIGPT AI logo/icon studio repo
#   image-generator        ChanMeng666 image-generators repo
#   LVGL-AI-Studio         dazeb LVGL + AI UI studio repo
BUNDLED_SKILLS = (
    "ui-ux-pro-max-skill",
    "taste-skill",
    "awesome-claude-design",
    "design-md-chrome",
    "design-motion-principles",
    "claudex-loop",
    "agency-agents",
    "system-prompts-leaks",
    # Design-repo family — installed once, active by default.
    "awesome-design-md",
    "ai-logo-studio",
    "image-generator",
    "LVGL-AI-Studio",
)

# ---------------------------------------------------------------------------
# Plugins — heavier INTEGRATIONS (vs skills = instruction packs).
# A plugin can install dependencies, expose slash commands, and alter what
# claume CAN DO (not just how it thinks). See skills/PLUGINS.md.
# ---------------------------------------------------------------------------
PLUGINS: Dict[str, Dict[str, Any]] = {
    "graphify": {
        "description": "any input → knowledge graph → clustered communities → HTML + JSON + audit report (/graphify)",
        "command": "/graphify",
        "pip": "graphifyy",
        "skill_dir": "graphify",
    },
    "jarvis": {
        "description": "desktop voice assistant with wake word, spoken replies and a human-like UI (/jarvis)",
        "command": "/jarvis",
        "pip": "",  # stdlib-first: optional extras documented in /jarvis
        "module": "claume.jarvis",
    },
}


def plugins_root() -> Path:
    return skills_root()


def list_plugins() -> List[Dict[str, Any]]:
    """All known plugins with active status from config.plugins_active."""
    cfg = config.Config()
    active_map = cfg.get("plugins_active", {}) or {}
    out: List[Dict[str, Any]] = []
    for name, meta in PLUGINS.items():
        out.append(
            {
                "name": name,
                "description": meta.get("description", ""),
                "command": meta.get("command", ""),
                "active": bool(active_map.get(name, False)),
            }
        )
    return out


def set_plugin_active(name: str, active: bool) -> bool:
    if name not in PLUGINS:
        return False
    cfg = config.Config()
    m = cfg.get("plugins_active", {}) or {}
    m[name] = bool(active)
    cfg.set("plugins_active", m)
    return True


def plugin_active(name: str) -> bool:
    cfg = config.Config()
    m = cfg.get("plugins_active", {}) or {}
    return bool(m.get(name, False))


def seed_bundled_skills() -> List[str]:
    """Copy bundled skills into the skills dir and activate them once.

    Runs at REPL startup: makes the ui-ux-pro-max design skill work
    out-of-the-box (its .md guidance + search scripts adopt into every
    design task) instead of requiring a manual /skill install.
    Returns the list of skills seeded/activated this run.
    """
    touched: List[str] = []
    try:
        import shutil

        pkg_root = Path(__file__).resolve().parent.parent
        bundled_root = pkg_root / "skills"
        cfg = config.Config()
        active_map = cfg.get("skills_active", {}) or {}
        changed = False
        for name in BUNDLED_SKILLS:
            src = bundled_root / name
            dest = skills_root() / name
            if src.is_dir() and not dest.is_dir():
                shutil.copytree(src, dest, ignore=shutil.ignore_patterns(".git"))
                touched.append(f"seeded {name}")
                changed = True
            if dest.is_dir() and not active_map.get(name, False):
                active_map[name] = True
                changed = True
                touched.append(f"activated {name}")
            # Design-repo family: clone from the user's GitHub URLs when no
            # bundled copy exists locally (fresh installs). They still come
            # up active by default so /design and the skills actually work.
            if name in (n for n, _ in DESIGN_REPO_FAMILY) and not dest.is_dir():
                url = _repo_url_for_name(name)
                if url:
                    rc = subprocess.call(
                        ["git", "clone", "--depth", "1", url, str(dest)],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    if rc == 0:
                        touched.append(f"installed {name} from {url}")
                        changed = True
                        active_map[name] = True
                        touched.append(f"activated {name}")
        if changed:
            cfg.set("skills_active", active_map)
    except Exception:
        pass
    return touched


# ---------------------------------------------------------------------------
# Instruction injection — the ".md instruction file" adoption
# ---------------------------------------------------------------------------
MAX_SKILL_DOCS_CHARS = 24_000  # total budget across all active skills
PER_SKILL_CAP = 3_500


def active_instructions(max_chars: int = MAX_SKILL_DOCS_CHARS) -> str:
    """Concatenated instructions from every active skill, for the system prompt.

    Injection order: the flagship bundled skills (BUNDLED_SKILLS order) come
    FIRST so the design pack always lands in context even when the budget is
    tight; user-installed extras follow alphabetically. Skills that don't fit
    stay installed + active for /skill-use, /skill-run and doc search.
    """
    cfg = config.Config()
    active_map = cfg.get("skills_active", {}) or {}
    priority = {name: i for i, name in enumerate(BUNDLED_SKILLS)}
    dirs = [d for d in sorted(skills_root().iterdir())
            if d.is_dir() and not d.name.startswith(".")]
    dirs.sort(key=lambda d: priority.get(d.name, len(priority)))
    parts: List[str] = []
    total = 0
    for d in dirs:
        if not active_map.get(d.name, False):
            continue
        doc = find_doc(d)
        if not doc:
            continue
        try:
            text = doc.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        text = text[:PER_SKILL_CAP]
        if total + len(text) > max_chars:
            continue  # skip this one, try the (smaller) next
        parts.append(f"### Skill: {d.name}\nSource: {doc}\n\n{text}")
        total += len(text)
    if not parts:
        return ""
    header = (
        "## Active skills (installed instruction packs — follow them)\n"
        "These are expert instruction files the user installed on purpose. "
        "Apply their guidance, formats and workflows to relevant tasks.\n"
    )
    return header + "\n\n".join(parts)


def skill_instructions(name: str, max_chars: int = PER_SKILL_CAP) -> str:
    """Instructions from one specific skill (active or not)."""
    d = skills_root() / name
    if not d.is_dir():
        return ""
    doc = find_doc(d)
    if not doc:
        return ""
    try:
        return doc.read_text(encoding="utf-8", errors="replace")[:max_chars]
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Script runner — execute a skill's bundled scripts
# ---------------------------------------------------------------------------
def run_script(name: str, script_hint: str, args: List[str], timeout: int = 180) -> Tuple[str, bool]:
    """Run a script bundled with a skill: /skill-run <skill> <script> [args…].

    script_hint may be an exact relative path or a fuzzy substring match.
    Python scripts run with the current interpreter; .sh through bash;
    .ps1 through powershell.
    """
    d = skills_root() / name
    if not d.is_dir():
        return f"error: skill '{name}' not installed", True
    _, scripts = index_skill(d)
    matches = [s for s in scripts if script_hint in str(s.relative_to(d))]
    if not matches:
        if not scripts:
            return f"error: skill '{name}' has no scripts", True
        return (
            f"error: no script matching '{script_hint}'. Available:\n"
            + "\n".join(f"  - {s.relative_to(d)}" for s in scripts[:20]),
            True,
        )
    script = matches[0]
    ext = script.suffix.lower()
    if ext == ".py":
        import sys

        cmd = [sys.executable, str(script)]
    elif ext == ".sh":
        bash = shutil_which("bash")
        cmd = [bash, str(script)] if bash else None
        if cmd is None:
            return "error: bash not found for .sh script", True
    elif ext == ".ps1":
        ps = shutil_which("powershell")
        cmd = [ps, "-NoProfile", "-File", str(script)] if ps else None
        if cmd is None:
            return "error: powershell not found", True
    else:
        cmd = [str(script)]
    try:
        proc = subprocess.run(
            cmd + list(args),
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(d),
            encoding="utf-8",
            errors="replace",
        )
        out = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()
        text = out if out else err
        return (text[:6000] or "(no output)"), proc.returncode != 0
    except subprocess.TimeoutExpired:
        return f"error: script timed out after {timeout}s", True
    except Exception as exc:
        return f"error: {exc}", True


def shutil_which(name: str):
    import shutil

    return shutil.which(name)


def search_docs(query: str, max_results: int = 10) -> List[Tuple[str, Path, int]]:
    """Search active skill docs for a query. Returns [(skill, path, score)]."""
    query_l = query.lower()
    results: List[Tuple[str, Path, int]] = []
    for s in list_skills():
        if not s["active"]:
            continue
        d = skills_root() / s["name"]
        for md in d.rglob("*.md"):
            try:
                text = md.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            score = text.lower().count(query_l)
            if score:
                results.append((s["name"], md, score))
    results.sort(key=lambda r: -r[2])
    return results[:max_results]
