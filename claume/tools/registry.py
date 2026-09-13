"""Tool registry: name -> implementation, schema, and metadata."""
from __future__ import annotations

import inspect
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import fs, shell, web


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
    """Lazily bridge configured MCP servers' tools into the registry."""
    try:
        from .. import mcp as mcpmod

        mcpmod.set_registry_target(sys.modules[__name__])
        return mcpmod.bridge_to_registry()
    except Exception:
        return 0


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
