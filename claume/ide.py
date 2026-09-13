"""claume ide — integrate with whatever IDE hosts the terminal.

claume runs INSIDE the IDE's integrated terminal (VS Code, Cursor,
JetBrains family — PyCharm, IntelliJ, Android Studio — or any plain
terminal). This module:

* **detects** the hosting IDE from environment markers and CLIs on PATH;
* **opens files at line:col** in the editor (the IDE's own window), so
  after claume edits code you can jump straight to the changed lines;
* **reveals files/folders** in the IDE explorer or the OS file manager;
* reports its findings to the agent's context so the model knows which
  IDE features are live.

Everything is stdlib-only and degrades silently: no IDE detected means
the tools fall back to the OS default opener.

Detection signals
-----------------
- ``TERM_PROGRAM=vscode``            → VS Code (also set by Cursor forks
  with ``CURSOR_TRACE_ID`` present)
- ``VSCODE_GIT_ASKPASS_NODE``        → VS Code integrated terminal
- ``TERMINAL_EMULATOR=JetBrains-JediTerm`` → any JetBrains IDE terminal
- ``__INTELLIJ_COMMAND_HISTFILE__``  → IntelliJ-family terminal
- ``STUDIO_PROPERTIES`` / Android Studio on PATH → Android Studio
- CLI fallbacks on PATH: code, code-insiders, cursor, pycharm, idea, studio
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# detection
# ---------------------------------------------------------------------------
def _which(*names: str) -> Optional[str]:
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    return None


def detect() -> Dict[str, Any]:
    """Detect the hosting IDE. Returns {name, kind, cli, open_support}.

    kind: "vscode" | "jetbrains" | "external"
    cli:  path to the launcher executable ("" when only OS opener exists)
    """
    env = os.environ
    term = env.get("TERM_PROGRAM", "")

    # --- Cursor (VS Code fork; check before generic vscode) --------------
    if env.get("CURSOR_TRACE_ID") or term.lower() == "cursor":
        cli = _which("cursor")
        return {"name": "Cursor", "kind": "vscode", "cli": cli or "", "open_support": bool(cli)}

    # --- VS Code ----------------------------------------------------------
    if term.lower() == "vscode" or env.get("VSCODE_GIT_ASKPASS_NODE"):
        cli = _which("code", "code.cmd", "code-insiders", "code-insiders.cmd")
        return {"name": "VS Code", "kind": "vscode", "cli": cli or "", "open_support": bool(cli)}

    # --- JetBrains family (PyCharm, IntelliJ, Android Studio, …) ---------
    jb_term = env.get("TERMINAL_EMULATOR", "") == "JetBrains-JediTerm"
    jb_hist = "__INTELLIJ_COMMAND_HISTFILE__" in env
    studio_prop = "STUDIO_PROPERTIES" in env or "ANDROID_STUDIO" in env
    if jb_term or jb_hist or studio_prop:
        # Which JetBrains IDE? Probe specific launchers, most specific first.
        studio_cli = _which("studio", "studio.sh", "studio64.exe")
        if studio_prop or studio_cli and _looks_like_studio(env):
            cli = studio_cli or ""
            return {"name": "Android Studio", "kind": "jetbrains", "cli": cli, "open_support": bool(cli)}
        pycharm_cli = _which("pycharm", "pycharm.sh", "pycharm64.exe", "charm")
        if pycharm_cli:
            return {"name": "PyCharm", "kind": "jetbrains", "cli": pycharm_cli, "open_support": True}
        idea_cli = _which("idea", "idea.sh", "idea64.exe")
        if idea_cli:
            return {"name": "IntelliJ IDEA", "kind": "jetbrains", "cli": idea_cli, "open_support": True}
        name = "Android Studio" if studio_prop else "JetBrains IDE"
        return {"name": name, "kind": "jetbrains", "cli": "", "open_support": False}

    # --- terminal-hosted markers for other editors ------------------------
    if term.lower() == "wave":
        return {"name": "Wave Terminal", "kind": "external", "cli": "", "open_support": False}

    # --- plain terminal: still allow CLI-driven editors if installed ------
    for name, clis in (
        ("VS Code", ("code", "code.cmd")),
        ("Cursor", ("cursor", "cursor.cmd")),
    ):
        cli = _which(*clis)
        if cli:
            return {"name": name, "kind": "vscode", "cli": cli, "open_support": True}
    if _which("pycharm", "pycharm.sh"):
        return {"name": "PyCharm", "kind": "jetbrains", "cli": _which("pycharm", "pycharm.sh"), "open_support": True}
    if _which("studio", "studio.sh"):
        return {"name": "Android Studio", "kind": "jetbrains", "cli": _which("studio", "studio.sh"), "open_support": True}

    return {"name": _os_terminal_name(), "kind": "external", "cli": "", "open_support": False}


def _looks_like_studio(env: Dict[str, str]) -> bool:
    for k in env:
        lk = k.lower()
        if "studio" in lk or "android" in lk:
            return True
    return False


def _os_terminal_name() -> str:
    if os.name == "nt":
        return "Windows Terminal" if os.environ.get("WT_SESSION") else "System terminal"
    if sys.platform == "darwin":
        return "Terminal.app"
    term = os.environ.get("TERM", "")
    return f"terminal ({term})" if term else "terminal"


# ---------------------------------------------------------------------------
# open / reveal
# ---------------------------------------------------------------------------
def open_file(path: str, line: int = 0, col: int = 0) -> Tuple[str, bool]:
    """Open a file in the hosting IDE at line:col when supported."""
    info = detect()
    fp = Path(path).expanduser()
    if not fp.is_absolute():
        fp = Path.cwd() / fp
    fp = fp.resolve()
    if not fp.exists():
        return f"error: file not found: {fp}", True

    cli = info.get("cli") or ""
    try:
        if info["kind"] == "vscode" and cli:
            # --goto file:line:col, -r reuses the window
            target = str(fp)
            if line:
                target += f":{int(line)}"
                if col:
                    target += f":{int(col)}"
            subprocess.Popen(
                [cli, "-r", "--goto", target],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            return f"opened {fp.name}" + (f" at line {line}" if line else "") + f" in {info['name']}", False

        if info["kind"] == "jetbrains" and cli:
            args = [cli]
            if line:
                args += ["--line", str(int(line))]
            args.append(str(fp))
            subprocess.Popen(
                args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            return f"opened {fp.name}" + (f" at line {line}" if line else "") + f" in {info['name']}", False

        # fallback: OS default opener
        _os_open(str(fp))
        return f"opened {fp.name} with the OS default application", False
    except Exception as exc:
        return f"error: could not open {fp}: {exc}", True


def reveal(path: str) -> Tuple[str, bool]:
    """Reveal a file/folder in the IDE explorer or OS file manager."""
    fp = Path(path).expanduser()
    if not fp.is_absolute():
        fp = Path.cwd() / fp
    fp = fp.resolve()
    if not fp.exists():
        return f"error: path not found: {fp}", True
    info = detect()
    cli = info.get("cli") or ""
    try:
        if info["kind"] == "vscode" and cli:
            subprocess.Popen([cli, "-r", str(fp if fp.is_dir() else fp.parent)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return f"revealed {fp.name} in {info['name']}", False
        # OS file managers (explorer can select a file, others open the dir)
        try:
            if os.name == "nt":
                if fp.is_file():
                    subprocess.Popen(["explorer", "/select,", str(fp)])
                else:
                    subprocess.Popen(["explorer", str(fp)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R", str(fp)] if fp.is_file() else ["open", str(fp)])
            else:
                subprocess.Popen(["xdg-open", str(fp.parent if fp.is_file() else fp)])
            return f"revealed {fp.name} in the file manager", False
        except Exception:
            _os_open(str(fp.parent if fp.is_file() else fp))
            return f"opened {fp.parent}", False
    except Exception as exc:
        return f"error: could not reveal {fp}: {exc}", True


def _os_open(target: str) -> None:
    if os.name == "nt":
        os.startfile(target)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        subprocess.Popen(["xdg-open", target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ---------------------------------------------------------------------------
# status for the agent context + /ide command
# ---------------------------------------------------------------------------
def status_line() -> str:
    """One-line IDE report for the boot context and /ide."""
    info = detect()
    bits = [f"ide {info['name']}"]
    if info.get("cli"):
        bits.append("file-open live (line:col jumps)")
    else:
        bits.append("OS-default file open")
    bits.append("edits hot-reload in the editor")
    return " · ".join(bits)


def context_note() -> str:
    """Context block fragment telling the model which IDE is live."""
    info = detect()
    if info["kind"] == "external" and not info.get("cli"):
        return ""
    cli_hint = ""
    if info.get("cli"):
        cli_hint = " — use ide_open after edits so the user jumps to changed lines"
    return f"- Hosting IDE: {info['name']}{cli_hint}"
