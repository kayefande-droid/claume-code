"""Filesystem tools for the agent: read, write, patch, list, mkdir."""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Tuple

MAX_READ_BYTES = 200_000


def _resolve(base: Path, path_str: str) -> Path:
    s = str(path_str).strip().strip('"').strip("'")
    # Git-Bash/MSYS-style paths the model sometimes emits (/c/Users/...,
    # /mnt/c/Users/... on WSL) — rewrite to native Windows form.
    import re as _re

    m = _re.match(r"^/(?:mnt/)?([a-zA-Z])/(.*)$", s)
    if m and os.name == "nt":
        s = f"{m.group(1).upper()}:/{m.group(2)}"
    p = Path(s)
    if not p.is_absolute():
        p = base / p
    return p.resolve()


def read_file(base: Path, path: str, offset: int = 1, limit: int = 2000) -> Tuple[str, bool]:
    """Read a slice of a file. Returns (content, is_error)."""
    fp = _resolve(base, str(path))
    if not fp.exists():
        return f"error: file not found: {fp}", True
    if fp.is_dir():
        return f"error: {fp} is a directory (use list_directory)", True
    try:
        text = fp.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return f"error: cannot read {fp}: {exc}", True
    lines = text.splitlines()
    total = len(lines)
    start = max(0, int(offset) - 1)
    end = min(total, start + int(limit))
    if start >= total:
        return f"error: offset {offset} beyond EOF ({total} lines)", True
    header = f"[{fp} | lines {start + 1}-{end} of {total}]\n"
    numbered = "\n".join(f"{i + 1:6d}\t{lines[i]}" for i in range(start, end))
    return header + numbered, False


def write_file(base: Path, path: str, content: str) -> Tuple[str, bool]:
    """Create/overwrite a file (parents auto-created). Returns (msg, is_error).

    Writes are ATOMIC (temp file + os.replace): IDE file watchers
    (VS Code, JetBrains, Android Studio) see a clean create/replace event
    and hot-reload the editor buffer without partial-read glitches.
    """
    fp = _resolve(base, str(path))
    try:
        fp.parent.mkdir(parents=True, exist_ok=True)
        existed = fp.exists()
        # atomic replace: same-directory temp + os.replace is atomic on
        # Windows and POSIX, and preserves the target's permissions.
        fd, tmp_name = tempfile.mkstemp(
            dir=str(fp.parent), prefix=f".{fp.name}.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as tmp:
                tmp.write(str(content))
            if existed:
                try:
                    os.chmod(tmp_name, fp.stat().st_mode)
                except Exception:
                    pass
            os.replace(tmp_name, fp)
        except Exception:
            try:
                os.unlink(tmp_name)
            except Exception:
                pass
            raise
        lines = str(content).count("\n") + 1
        verb = "updated" if existed else "created"
        return f"{verb} {fp} ({lines} lines, {len(content)} bytes)", False
    except Exception as exc:
        return f"error: cannot write {fp}: {exc}", True


def patch_file(base: Path, path: str, old_string: str, new_string: str, allow_multiple: bool = False) -> Tuple[str, bool]:
    """Replace exact string(s) in a file — the surgical edit tool."""
    fp = _resolve(base, str(path))
    if not fp.exists():
        return f"error: file not found: {fp}", True
    try:
        text = fp.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return f"error: cannot read {fp}: {exc}", True

    old = str(old_string)
    new = str(new_string)
    count = text.count(old)
    if count == 0:
        # Helpful hint for the model.
        return (
            f"error: old_string not found in {fp.name}. "
            "Read the file again and copy old_string EXACTLY (whitespace matters).",
            True,
        )
    if count > 1 and not allow_multiple:
        return (
            f"error: old_string matches {count} places in {fp.name}; "
            "add more surrounding context or set allow_multiple=true.",
            True,
        )
    if count > 1 and allow_multiple:
        text = text.replace(old, new)
        return _atomic_write(fp, text, f"patched {count} occurrence(s) in {fp}")

    text = text.replace(old, new, 1)
    return _atomic_write(fp, text, f"patched {fp} (1 occurrence)")


def _atomic_write(fp: Path, content: str, message: str) -> Tuple[str, bool]:
    """Same-directory temp + os.replace: IDE watchers see one clean event."""
    try:
        fd, tmp_name = tempfile.mkstemp(
            dir=str(fp.parent), prefix=f".{fp.name}.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as tmp:
                tmp.write(content)
            try:
                os.chmod(tmp_name, fp.stat().st_mode)
            except Exception:
                pass
            os.replace(tmp_name, fp)
        except Exception:
            try:
                os.unlink(tmp_name)
            except Exception:
                pass
            raise
        return message, False
    except Exception as exc:
        return f"error: cannot write {fp}: {exc}", True


def list_directory(base: Path, path: str = ".", recursive: bool = False) -> Tuple[str, bool]:
    """List a directory. Recursive mode respects .gitignore-ish skip list."""
    dp = _resolve(base, str(path))
    if not dp.exists():
        return f"error: directory not found: {dp}", True
    if not dp.is_dir():
        return f"error: not a directory: {dp}", True

    SKIP = {".git", "node_modules", "__pycache__", ".venv", "venv", ".idea", ".claume", "dist", "build", ".next"}

    def skip(name: str) -> bool:
        return name in SKIP or name.endswith((".pyc", ".pyo"))

    if recursive:
        entries: List[str] = []
        for root, dirs, files in __import__("os").walk(dp):
            dirs[:] = [d for d in dirs if not skip(d)]
            rel = Path(root).relative_to(dp)
            prefix = "" if str(rel) == "." else str(rel) + "/"
            for f in sorted(files)[:400]:
                if not skip(f):
                    entries.append(prefix + f)
            if len(entries) > 800:
                entries.append("… (truncated)")
                break
        return f"[{dp}]\n" + "\n".join(entries[:800]), False

    try:
        items = sorted(dp.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
    except Exception as exc:
        return f"error: {exc}", True
    lines = []
    for item in items:
        if skip(item.name):
            continue
        if item.is_dir():
            lines.append(f"  {item.name}/")
        else:
            size = item.stat().st_size
            lines.append(f"  {item.name}  ({size} B)")
    return f"[{dp}]\n" + "\n".join(lines) if lines else f"[{dp}] (empty)", False


def make_directory(base: Path, path: str) -> Tuple[str, bool]:
    dp = _resolve(base, str(path))
    try:
        dp.mkdir(parents=True, exist_ok=True)
        return f"created directory {dp}", False
    except Exception as exc:
        return f"error: {exc}", True


def delete_path(base: Path, path: str) -> Tuple[str, bool]:
    """Delete a file or tree — ALWAYS gated behind confirmation upstream."""
    dp = _resolve(base, str(path))
    if not dp.exists():
        return f"error: not found: {dp}", True
    try:
        if dp.is_dir():
            shutil.rmtree(dp)
            return f"deleted directory tree {dp}", False
        dp.unlink()
        return f"deleted {dp}", False
    except Exception as exc:
        return f"error: {exc}", True


def search_text(base: Path, pattern: str, path: str = ".") -> Tuple[str, bool]:
    """Grep-like content search (regex, first 100 matches)."""
    import re

    sp = _resolve(base, str(path))
    if not sp.exists():
        return f"error: path not found: {sp}", True
    try:
        rx = re.compile(pattern)
    except re.error as exc:
        return f"error: bad regex: {exc}", True

    SKIP = {".git", "node_modules", "__pycache__", ".venv", "venv", ".idea"}
    matches: List[str] = []
    try:
        if sp.is_file():
            targets = [sp]
        else:
            targets = [p for p in sp.rglob("*") if p.is_file() and not (set(p.parts) & SKIP)]
    except Exception as exc:
        return f"error: {exc}", True

    for fp in targets:
        try:
            if fp.stat().st_size > 1_500_000:
                continue
            for lineno, line in enumerate(fp.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if rx.search(line):
                    matches.append(f"{fp.relative_to(base) if fp.is_relative_to(base) else fp}:{lineno}: {line.strip()[:160]}")
                    if len(matches) >= 100:
                        matches.append("… (100 match cap)")
                        return "\n".join(matches), False
        except Exception:
            continue
    return "\n".join(matches) if matches else "no matches", False


def tree_view(base: Path, path: str = ".", depth: int = 3) -> Tuple[str, bool]:
    """Compact tree with box-drawing characters."""
    dp = _resolve(base, str(path))
    SKIP = {".git", "node_modules", "__pycache__", ".venv", "venv", ".idea", "dist", "build"}

    def walk(d: Path, prefix: str, level: int, out: List[str]) -> None:
        if level > int(depth):
            return
        try:
            items = sorted(d.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
        except Exception:
            return
        items = [i for i in items if i.name not in SKIP]
        for idx, item in enumerate(items[:40]):
            last = idx == len(items) - 1 or idx == 39
            connector = "└── " if last else "├── "
            out.append(prefix + connector + item.name + ("/" if item.is_dir() else ""))
            if item.is_dir():
                walk(item, prefix + ("    " if last else "│   "), level + 1, out)

    if not dp.is_dir():
        return f"error: not a directory: {dp}", True
    out = [f"[{dp.name or dp}]"]
    walk(dp, "", 1, out)
    return "\n".join(out[:250]), False
