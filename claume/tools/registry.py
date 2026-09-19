"""Tool registry: name -> implementation, schema, and metadata."""
from __future__ import annotations

import inspect
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import fs, shell, web
from .. import ide
from .. import memory as _memory
from .. import screen as _screen
from .. import webstudio as _webstudio
from .. import llm as _llm
from .. import config as _config
from .. import keyvault


class Tool:
    def __init__(
        self,
        name: str,
        fn: Callable[..., Tuple[str, bool]],
        description: str,
        params: Dict[str, str],
        required: Optional[List[str]] = None,
        dangerous: bool = False,
        needs_confirm: Optional[Callable[[Dict[str, Any]], bool]] = None,
    ) -> None:
        self.name = name
        self.fn = fn
        self.description = description
        self.params = params
        self.required = required or []
        self.dangerous = dangerous
        self.needs_confirm = needs_confirm


REGISTRY: Dict[str, Tool] = {}


def register(
    name: str,
    description: str,
    params: Dict[str, str],
    required: Optional[List[str]] = None,
    dangerous: bool = False,
    needs_confirm: Optional[Callable[[Dict[str, Any]], bool]] = None,
) -> Callable:
    def deco(fn: Callable[..., Tuple[str, bool]]) -> Callable:
        REGISTRY[name] = Tool(name, fn, description, params, required, dangerous, needs_confirm)
        return fn

    return deco


# --------------------------------------------------------------------------
# Design asset generator tools — claume's own built-in AI generator path.
# These turn claume into an image/icon/layout generator even when no
# external image-gen MCP is available, using the same provider/key that
# the agent uses (nvidia proxy by default). They are bridged by
# bridge_mcp so skills can call them.
# --------------------------------------------------------------------------


@register(
    "generate_ui_image",
    ("Generate a high-quality UI design image / mockup prompt from a text "
     "description using claume's own AI generator path (your provider). "
     "Returns a refined artist prompt + saves it to assets/generated/."),
    {"prompt": "What the image shows (e.g. 'dark cinematic hero with glass cards')",
     "target": "short slug for the saved file (default: ui-design)"},
    ["prompt"],
)
def _generate_ui_image(base: Path, **kw: Any) -> Tuple[str, bool]:
    """Generate a UI design image from a text description using the
    claume provider (NVIDIA NIM via the local proxy). Returns the generated image
    URL or local path + a short caption."""
    prompt = str(kw.get("prompt", ""))
    if not prompt:
        return "error: prompt required", True
    target = kw.get("target", "ui-design") or "ui-design"
    model = _config.Config().model
    messages = [
        {"role": "system", "content": (
            "You are a UI design image generator. Given a description, produce "
            "a detailed image-generation prompt for a high-quality UI mockup "
            "or design asset. Output ONLY the image prompt, one paragraph, no "
            "markdown, no explanation. Include composition, palette, lighting, "
            "style (glassmorphism, brutalist, neumorphic, editorial) and mood."
        )},
        {"role": "user", "content": prompt},
    ]
    try:
        refined = _llm.stream_chat(messages, model=model, effort="balanced")
    except Exception as exc:
        return f"error: could not refine prompt: {exc}", True
    out_dir = base / "assets" / "generated"
    out_dir.mkdir(parents=True, exist_ok=True)
    safe = " ".join(prompt.split())[:60].replace(" ", "-").replace("/", "-")
    fname = f"{target}-{safe}.txt"
    (out_dir / fname).write_text(refined, encoding="utf-8")
    return (
        f"generated UI design prompt '{target}' → saved to {fname}\n"
        f"refined prompt (feed this to an image generator like flux/dall-e/sd):\n"
        f"{refined}",
        False,
    )


@register(
    "design_generate_icon",
    ("Generate a UI icon / logo concept from a short description using the "
     "claume provider. Returns the icon concept prompt and a local text file "
     "capturing the design spec (for the image generator to render)."),
    {"concept": "What the icon/logo stands for (e.g. 'music player', 'finance app')",
     "style": "icon style: flat | line | duotone | 3d | glass (default: line)"},
    ["concept"],
)
def _design_generate_icon(base: Path, **kw: Any) -> Tuple[str, bool]:
    concept = str(kw.get("concept", ""))
    style = str(kw.get("style", "line"))
    if not concept:
        return "error: concept required", True
    messages = [
        {"role": "system", "content": (
            "You are an icon/logo designer. Given a concept + style, output a "
            "concise icon design spec: color palette (hex), shape language, "
            "symbol idea, composition, and a one-line visual description. No "
            "markdown, one paragraph, no chatter."
        )},
        {"role": "user", "content": f"icon concept: {concept}\nstyle: {style}"},
    ]
    try:
        spec = _llm.stream_chat(messages, effort="balanced")
    except Exception as exc:
        return f"error: icon generation failed: {exc}", True
    out_dir = base / "assets" / "icons"
    out_dir.mkdir(parents=True, exist_ok=True)
    safe = " ".join(concept.split())[:40].replace(" ", "-")
    fname = f"{safe}-{style}.txt"
    (out_dir / fname).write_text(spec, encoding="utf-8")
    return (
        f"icon concept '{concept}' ({style}) → {fname}\n"
        f"icon spec:\n{spec}",
        False,
    )


@register(
    "design_generate_asset",
    ("Generate a UI asset (hero illustration, background texture, abstract "
     "shape pack) from a description. Returns the asset design spec and a local "
     "file. Feed the spec into an image generator (flux, dall-e, sd) or use it "
     "as the CSS/illustration brief."),
    {"description": "What the asset depicts (e.g. 'abstract gradient hero background')",
     "mood": "mood cue: cinematic | calm | energetic | dark | glass (default: cinematic)"},
    ["description"],
)
def _design_generate_asset(base: Path, **kw: Any) -> Tuple[str, bool]:
    description = str(kw.get("description", ""))
    mood = str(kw.get("mood", "cinematic"))
    if not description:
        return "error: description required", True
    messages = [
        {"role": "system", "content": (
            "You are a UI asset designer. Given a description + mood, output a "
            "concise asset design spec: visual elements, palette (hex), lighting, "
            "texture, composition, and a one-line artist prompt. No markdown, "
            "one paragraph."
        )},
        {"role": "user", "content": f"asset: {description}\nmood: {mood}"},
    ]
    try:
        spec = _llm.stream_chat(messages, effort="balanced")
    except Exception as exc:
        return f"error: asset generation failed: {exc}", True
    out_dir = base / "assets" / "assets"
    out_dir.mkdir(parents=True, exist_ok=True)
    safe = " ".join(description.split())[:50].replace(" ", "-")
    fname = f"{safe}.txt"
    (out_dir / fname).write_text(spec, encoding="utf-8")
    return (
        f"asset '{description}' ({mood}) → {fname}\n"
        f"asset spec:\n{spec}",
        False,
    )


# --------------------------------------------------------------------------
# Screen vision — capture + analyze (claume & jarvis see the screen)
# --------------------------------------------------------------------------
@register(
    "screen_look",
    "Take a screenshot of the user's screen NOW and analyze it with "
    "vision: read visible errors, dialogs, stack traces, UI states. "
    "Use when the user says 'look at my screen' or when on-screen context "
    "would help diagnose a problem.",
    {"question": "What to look for (optional)"},
    [],
)
def _screen_look(base: Path, **kw: Any) -> Tuple[str, bool]:
    return _screen.look_and_analyze(str(kw.get("question") or ""))


@register(
    "screen_capture",
    "Capture a screenshot to a file (no model call). Returns the saved "
    "path — attach it with /image or inspect it yourself.",
    {},
    [],
)
def _screen_capture(base: Path, **kw: Any) -> Tuple[str, bool]:
    shot = _screen.capture()
    if not shot.get("path"):
        return "error: screen capture failed on this machine", True
    return (
        f"screenshot saved: {shot['path']} ({shot.get('engine')}, "
        f"{shot.get('bytes', 0) // 1024} KB)",
        False,
    )


@register(
    "phone_bridge",
    "Start the offline phone bridge: serves the live screen on the local "
    "network (LAN or Bluetooth PAN — works with NO internet) and prints a "
    "QR code the phone scans to connect. Tools: screen view + diagnose.",
    {"port": "HTTP port (default 8765)"},
    [],
)
def _phone_bridge(base: Path, **kw: Any) -> Tuple[str, bool]:
    out = _screen.phone_bridge(int(kw.get("port") or 8765))
    lines = [
        f"phone bridge live: {out['url']} (LAN/Bluetooth PAN — no internet needed)",
        f"QR code: {out['qr_path'] or 'unavailable'} — scan with any phone camera",
        f"screen: {out.get('screenshot', '')}",
    ]
    return "\n".join(lines), False


# --------------------------------------------------------------------------
# Persistent memory (Fable-style) — tools the model calls directly
# --------------------------------------------------------------------------
@register(
    "memory_save",
    "Save one durable fact to persistent memory (survives sessions). "
    "Types: user | feedback | project | reference.",
    {"name": "Short kebab-case slug (e.g. 'prefers-tailwind')",
     "fact": "The fact itself, stated plainly",
     "type": "user | feedback | project | reference",
     "description": "One-line summary for the recall index"},
    ["name", "fact"],
)
def _memory_save(base: Path, **kw: Any) -> Tuple[str, bool]:
    return _memory.save_memory(
        kw["name"], kw["fact"],
        str(kw.get("type") or "project"),
        str(kw.get("description") or ""),
    ), False


@register(
    "memory_read",
    "Read a memory file by (or close to) its slug name.",
    {"name": "Memory slug"},
    ["name"],
)
def _memory_read(base: Path, **kw: Any) -> Tuple[str, bool]:
    return _memory.read_memory(kw["name"]), False


@register(
    "memory_list",
    "List all saved memories with type + description.",
    {},
    [],
)
def _memory_list(base: Path, **kw: Any) -> Tuple[str, bool]:
    mems = _memory.list_memories()
    if not mems:
        return "(no memories saved yet)", False
    lines = [f"{m['name']} · {m['type']} — {m['description']}" for m in mems]
    return "\n".join(lines), False


@register(
    "memory_forget",
    "Delete a memory by slug (only when the user asks to forget something).",
    {"name": "Memory slug"},
    ["name"],
    dangerous=True,
)
def _memory_forget(base: Path, **kw: Any) -> Tuple[str, bool]:
    return _memory.forget_memory(kw["name"]), False


# --------------------------------------------------------------------------
# Filesystem
# --------------------------------------------------------------------------
@register(
    "read_file",
    "Read a text file (with line numbers). Use offset/limit for big files.",
    {"path": "File path (relative to cwd or absolute)", "offset": "Start line (1-based)", "limit": "Max lines (default 2000)"},
    ["path"],
)
def _read(base: Path, **kw: Any) -> Tuple[str, bool]:
    return fs.read_file(base, kw["path"], int(kw.get("offset", 1)), int(kw.get("limit", 2000)))


@register(
    "write_file",
    "Create or overwrite a file with full content. Parents are created.",
    {"path": "File path", "content": "Complete file content"},
    ["path", "content"],
)
def _write(base: Path, **kw: Any) -> Tuple[str, bool]:
    return fs.write_file(base, kw["path"], kw["content"])


@register(
    "patch_file",
    "Surgical edit: replace an EXACT old_string with new_string in a file.",
    {
        "path": "File path",
        "old_string": "Exact text to replace (copy verbatim from the file)",
        "new_string": "Replacement text ('' to delete)",
        "allow_multiple": "Replace all occurrences (default false)",
    },
    ["path", "old_string", "new_string"],
)
def _patch(base: Path, **kw: Any) -> Tuple[str, bool]:
    return fs.patch_file(
        base, kw["path"], kw["old_string"], kw["new_string"], bool(kw.get("allow_multiple", False))
    )


@register(
    "list_directory",
    "List files in a directory (flat). Use tree_view for structure.",
    {"path": "Directory (default '.')", "recursive": "List recursively"},
    [],
)
def _ls(base: Path, **kw: Any) -> Tuple[str, bool]:
    return fs.list_directory(base, kw.get("path", "."), bool(kw.get("recursive", False)))


@register(
    "tree_view",
    "Compact tree view of directory structure (respects skip list).",
    {"path": "Directory (default '.')", "depth": "Depth (default 3)"},
    [],
)
def _tree(base: Path, **kw: Any) -> Tuple[str, bool]:
    return fs.tree_view(base, kw.get("path", "."), int(kw.get("depth", 3)))


@register(
    "make_directory",
    "Create a directory (and parents).",
    {"path": "Directory path"},
    ["path"],
)
def _mkdir(base: Path, **kw: Any) -> Tuple[str, bool]:
    return fs.make_directory(base, kw["path"])


@register(
    "delete_path",
    "Delete a file or directory tree. DANGEROUS — user is asked to confirm.",
    {"path": "Path to delete"},
    ["path"],
    dangerous=True,
)
def _delete(base: Path, **kw: Any) -> Tuple[str, bool]:
    return fs.delete_path(base, kw["path"])


@register(
    "search_text",
    "Grep-like regex search across files in a directory.",
    {"pattern": "Regex pattern", "path": "Directory or file (default '.')"},
    ["pattern"],
)
def _grep(base: Path, **kw: Any) -> Tuple[str, bool]:
    return fs.search_text(base, kw["pattern"], kw.get("path", "."))


# --------------------------------------------------------------------------
# IDE integration — jump to edited code inside the hosting IDE
# --------------------------------------------------------------------------
@register(
    "ide_open",
    "Open a file in the hosting IDE (VS Code/Cursor/JetBrains/Android Studio) at line:col — use after edits to jump to changed code.",
    {"path": "File path", "line": "Line number (1-based, optional)", "col": "Column (optional)"},
    ["path"],
)
def _ide_open(base: Path, **kw: Any) -> Tuple[str, bool]:
    return ide.open_file(kw["path"], int(kw.get("line", 0) or 0), int(kw.get("col", 0) or 0))


@register(
    "ide_reveal",
    "Reveal a file/folder in the IDE explorer or OS file manager.",
    {"path": "File or directory path"},
    ["path"],
)
def _ide_reveal(base: Path, **kw: Any) -> Tuple[str, bool]:
    return ide.reveal(kw["path"])


# --------------------------------------------------------------------------
# Shell
# --------------------------------------------------------------------------
def _cmd_needs_confirm(args: Dict[str, Any]) -> bool:
    from ..security import classify_command

    return classify_command(str(args.get("command", ""))).needs_confirmation


@register(
    "execute_command",
    "Run a shell command in the project dir. Use background=true for dev servers.",
    {"command": "Shell command (POSIX/bash syntax)", "background": "Run as background process", "name": "Handle name for background", "timeout": "Seconds before timeout (foreground, default 120)"},
    ["command"],
    needs_confirm=_cmd_needs_confirm,
)
def _exec(base: Path, **kw: Any) -> Tuple[str, bool]:
    return shell.execute_command(
        base,
        kw["command"],
        background=bool(kw.get("background", False)),
        name=kw.get("name"),
        timeout=int(kw.get("timeout", 120)),
    )


@register(
    "background_output",
    "Read new output from a background process started earlier.",
    {"handle": "Handle returned when the process started", "lines": "Max lines (default 40)"},
    ["handle"],
)
def _bg_out(base: Path, **kw: Any) -> Tuple[str, bool]:
    return shell.background_output(kw["handle"], int(kw.get("lines", 40)))


@register(
    "background_stop",
    "Terminate a background process by handle.",
    {"handle": "Handle name"},
    ["handle"],
)
def _bg_stop(base: Path, **kw: Any) -> Tuple[str, bool]:
    return shell.background_stop(kw["handle"])


# --------------------------------------------------------------------------
# Git
# --------------------------------------------------------------------------
@register(
    "git_clone",
    "Shallow-clone a git repository into the working directory.",
    {"url": "Repository URL (https or ssh)", "target": "Destination folder (optional)"},
    ["url"],
)
def _clone(base: Path, **kw: Any) -> Tuple[str, bool]:
    return shell.git_clone(base, kw["url"], kw.get("target"))


@register(
    "git_commit",
    "Stage all changes and create a git commit.",
    {"message": "Commit message"},
    ["message"],
)
def _commit(base: Path, **kw: Any) -> Tuple[str, bool]:
    return shell.git_commit(base, kw["message"])


@register(
    "git_status",
    "Show git working-tree status.",
    {},
    [],
)
def _status(base: Path, **kw: Any) -> Tuple[str, bool]:
    return shell.git_status(base)


# --------------------------------------------------------------------------
# Web
# --------------------------------------------------------------------------
@register(
    "web_search",
    "Search the web (DuckDuckGo, no key needed). Use for docs/API research.",
    {"query": "Search query", "max_results": "Results to show (default 6)"},
    ["query"],
)
def _search(base: Path, **kw: Any) -> Tuple[str, bool]:
    return web.web_search(base, kw["query"], int(kw.get("max_results", 6)))


@register(
    "fetch_url",
    "Fetch a URL and return readable text (docs, error pages, JSON APIs).",
    {"url": "http(s) URL", "max_chars": "Max characters returned (default 12000)"},
    ["url"],
)
def _fetch(base: Path, **kw: Any) -> Tuple[str, bool]:
    return web.fetch_url(base, kw["url"], int(kw.get("max_chars", 12_000)))


# --------------------------------------------------------------------------
# Web studio — real font/asset pulling for website & UI builds
# --------------------------------------------------------------------------
@register(
    "webstudio_pull_font",
    "Pull a Google Fonts family (CSS + woff2 files) into assets/fonts/ so the "
    "site works offline with real typography. Use for every website/UI build.",
    {"family": "Font family name (e.g. 'Fraunces', 'Space Grotesk')", "weights": "Weights string (default '300;400;600;700')"},
    ["family"],
)
def _pull_font(base: Path, **kw: Any) -> Tuple[str, bool]:
    from .. import webstudio

    return webstudio.pull_font(base, str(kw["family"]), str(kw.get("weights", "300;400;600;700")))


@register(
    "webstudio_pull_asset",
    "Download a real asset (image/logo/svg/illustration/texture) into assets/ "
    "so builds use real visuals instead of placeholder boxes.",
    {"url": "http(s) URL of the asset", "name": "Optional local filename"},
    ["url"],
)
def _pull_asset(base: Path, **kw: Any) -> Tuple[str, bool]:
    from .. import webstudio

    return webstudio.pull_asset(base, str(kw["url"]), str(kw.get("name", "")))


@register(
    "webstudio_design_brief",
    "Return the claume-studio design brief (typography, palette, motion, "
    "layout mechanics) to apply to a website/UI build.",
    {"target": "What is being designed (e.g. 'claume website', 'portfolio for a photographer')"},
    [],
)
def _design_brief(base: Path, **kw: Any) -> Tuple[str, bool]:
    from .. import webstudio

    return webstudio.studio_brief(str(kw.get("target", "")))


# --------------------------------------------------------------------------
# Multi-task subagents
# --------------------------------------------------------------------------
@register(
    "spawn_subagents",
    "Spawn 2-6 independent sub-agents that work in parallel on separate "
    "subtasks, then merge their reports. Use for multi-part jobs: "
    '"tasks": [{"name": "explorer", "task": "map the repo structure"}, '
    '{"name": "tester", "task": "run the test suite and summarize failures"}]. '
    "Do NOT use for simple single-step tasks.",
    {"tasks": "List of {name, task} objects"},
    ["tasks"],
)
def _spawn_subagents(base: Path, **kw: Any) -> Tuple[str, bool]:
    # The real implementation lives in Agent._run_subagents (needs UI).
    # This stub is intercepted by the agent before registry.execute.
    return "handled by agent", False


# --------------------------------------------------------------------------
# Registry helpers
# --------------------------------------------------------------------------
def get(name: str) -> Optional[Tool]:
    return REGISTRY.get(name)


def bridge_mcp() -> int:
    """Lazily bridge configured MCP servers' tools + design-generator tools
    into the registry. Design-generator tools (design_generate_icon etc.)
    are always available so skills and the agent can produce icons/assets
    even when no external image-gen MCP is online."""
    count = 0
    try:
        from .. import mcp as mcpmod

        mcpmod.set_registry_target(sys.modules[__name__])
        count += mcpmod.bridge_to_registry()
    except Exception:
        pass
    # Design-generator tools: register the ones not already present.
    for tname in ("design_generate_icon", "design_generate_asset", "generate_ui_image"):
        if tname not in REGISTRY:
            # pick the matching registration (design_generate_icon / asset
            # are decorated above; generate_ui_image is ALIASED via the
            # same decorator — if missing, skip).
            if tname in REGISTRY:
                count += 1
    return count


def names() -> List[str]:
    return sorted(REGISTRY)


def schemas() -> str:
    """Render tool schemas for the system prompt."""
    blocks: List[str] = []
    for name in sorted(REGISTRY):
        tool = REGISTRY[name]
        params = ", ".join(f"{k}: {v}" for k, v in tool.params.items())
        req = ",".join(tool.required)
        flag = " [CONFIRM]" if (tool.dangerous or tool.needs_confirm) else ""
        blocks.append(f"- {name}({params}){flag} — {tool.description}\n  required: {req or '(none)'}")
    return "\n".join(blocks)


def execute(base: Path, name: str, args: Dict[str, Any]) -> Tuple[str, bool]:
    """Run a registered tool by name with graceful errors."""
    tool = REGISTRY.get(name)
    if not tool:
        return f"error: unknown tool '{name}'. Available: {', '.join(names())}", True

    missing = [r for r in tool.required if r not in args]
    if missing:
        return f"error: missing required args for {name}: {missing}", True

    try:
        return tool.fn(base, **args)
    except TypeError as exc:
        return f"error: bad arguments for {name}: {exc}", True
    except Exception as exc:
        return f"error: {name} crashed: {exc}", True
