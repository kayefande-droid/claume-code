"""Shell tool: execute commands with safety classification and background support."""
from __future__ import annotations

import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..security import classify_command

MAX_OUTPUT = 12_000

# Long-running processes registry: name -> Popen
_background: Dict[str, subprocess.Popen] = {}
_bg_lock = threading.Lock()
_bg_counter = 0


def _truncate(text: str) -> str:
    if len(text) <= MAX_OUTPUT:
        return text
    return text[: MAX_OUTPUT // 2] + f"\n… [{len(text)} chars total, truncated] …\n" + text[-MAX_OUTPUT // 2 :]


def _read_stream(stream, chunks: List[str]) -> None:
    try:
        for line in iter(stream.readline, ""):
            chunks.append(line)
    except Exception:
        pass


def execute_command(
    base: Path,
    command: str,
    background: bool = False,
    name: Optional[str] = None,
    timeout: int = 120,
) -> Tuple[str, bool]:
    """Run a shell command. Returns (output, is_error).

    background=True: start and return immediately with a handle. Use
    ``background_output``/``background_stop`` to interact with it later.
    """
    cmd = str(command).strip()
    if not cmd:
        return "error: empty command", True

    global _bg_counter
    verdict = classify_command(cmd)

    if background:
        return _start_background(base, cmd, name)

    try:
        proc = subprocess.Popen(
            cmd,
            shell=True,
            cwd=str(base),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        try:
            out, _ = proc.communicate(timeout=int(timeout))
        except subprocess.TimeoutExpired:
            proc.kill()
            out, _ = proc.communicate()
            return _truncate(f"[timed out after {timeout}s]\n{out or ''}"), True
    except Exception as exc:
        return f"error: failed to launch: {exc}", True

    output = (out or "").strip()
    note = f"[exit {proc.returncode}]"
    if verdict.level == "destructive":
        note += " ⚠ destructive command (was user-confirmed)"
    return _truncate(f"{note}\n{output}"), proc.returncode != 0


def _start_background(base: Path, cmd: str, name: Optional[str]) -> Tuple[str, bool]:
    global _bg_counter
    with _bg_lock:
        _bg_counter += 1
        handle = name or f"bg-{_bg_counter}"
        try:
            proc = subprocess.Popen(
                cmd,
                shell=True,
                cwd=str(base),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            )
        except Exception as exc:
            return f"error: {exc}", True
        _background[handle] = proc
    time.sleep(1.5)  # give it a moment to emit startup output
    return f"started '{cmd}' as [{handle}] (pid {proc.pid})\n{background_output(handle)[0]}", False


def background_output(handle: str, lines: int = 40) -> Tuple[str, bool]:
    """Drain recent output of a background process."""
    proc = _background.get(str(handle))
    if not proc:
        return f"error: unknown handle [{handle}] (known: {list(_background)})", True
    collected: List[str] = []
    while True:
        line = proc.stdout.readline() if proc.stdout else ""
        if not line:
            break
        collected.append(line.rstrip())
        if len(collected) >= int(lines) * 3:
            break
    status = "running" if proc.poll() is None else f"exited({proc.returncode})"
    return f"[{handle}] {status}\n" + ("\n".join(collected[-int(lines):]) or "(no new output)"), False


def background_stop(handle: str) -> Tuple[str, bool]:
    proc = _background.get(str(handle))
    if not proc:
        return f"error: unknown handle [{handle}]", True
    try:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        del _background[str(handle)]
        return f"stopped [{handle}]", False
    except Exception as exc:
        return f"error: {exc}", True


def background_list() -> Tuple[str, bool]:
    if not _background:
        return "no background processes", False
    rows = []
    for handle, proc in _background.items():
        status = "running" if proc.poll() is None else "exited"
        rows.append(f"  [{handle}] pid={proc.pid} {status}")
    return "\n".join(rows), False


# ---------------------------------------------------------------------------
# Git tools
# ---------------------------------------------------------------------------
def git_clone(base: Path, url: str, target: Optional[str] = None) -> Tuple[str, bool]:
    dest = target or Path(url.rstrip("/").split("/")[-1].removesuffix(".git"))
    return execute_command(base, f"git clone --depth 1 {url} {dest}", timeout=300)


def git_commit(base: Path, message: str) -> Tuple[str, bool]:
    msg = str(message).replace('"', "'")
    out1, err1 = execute_command(base, "git add -A", timeout=60)
    out2, err2 = execute_command(base, f'git commit -m "{msg}"', timeout=60)
    combined = out1 + "\n" + out2
    return combined, err1 or err2


def git_status(base: Path) -> Tuple[str, bool]:
    return execute_command(base, "git status --short --branch", timeout=30)
