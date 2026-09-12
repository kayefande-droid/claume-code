"""Slash command handlers for the claume REPL."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from . import config, keyvault, proxy
from .tools import registry
from .ui import BLUE, BOLD, DIM, GOLD, GREEN, GREY, MINT, RED, RESET, SILVER, box
from .version import __version__

if TYPE_CHECKING:
    from .agent import Agent

# ---------------------------------------------------------------------------
# Handlers return True to indicate "handled".
# ---------------------------------------------------------------------------

HELP_LINES = [
    f"{GREEN}claume-code{RESET} {GREY}v{__version__} — slash commands{RESET}",
    "",
    f"  {MINT}/help{RESET}              show this help",
    f"  {MINT}/new{RESET}               start a fresh conversation",
    f"  {MINT}/model{RESET} [name]     show or set the model",
    f"  {MINT}/effort{RESET} <level>   fast | balanced | deep",
    f"  {MINT}/auto{RESET} [on|off]    toggle auto mode (alias of /mode auto|manual)",
    f"  {MINT}/mode{RESET} [name]      manual | accept | plan | auto (Shift+Tab cycles)",
    f"  {MINT}/theme{RESET} [name]     color theme: nvidia-green, claude-orange, cyber-blue, synthwave, matrix, sunset, mono",
    f"  {MINT}/expand{RESET} [on|off]  show full tool output (default: 14 lines)",
    f"  {MINT}/copy{RESET} [text]      copy the last answer (or given text) to clipboard",
    f"  {MINT}/mascot{RESET}           show the claume pixel bot",
    f"  {MINT}/projects{RESET}         list everything claume built (~/.claume/projects)",
    f"  {MINT}/project{RESET} <name>   show/create a project folder there",
    f"  {MINT}/repo{RESET}             show the upstream GitHub repo + git remote status",
    f"  {MINT}/session{RESET} [id]     show session info / start a specific one",
    f"  {MINT}/resume{RESET}           resume a past session (interactive picker)",
    f"  {MINT}/continue{RESET}         resume the most recent session",
    f"  {MINT}/agents{RESET} <t1>; <t2>  run parallel subagents and merge reports",
    f"  {MINT}/design{RESET} <prompt>  run the MCP design pipeline (Link System)",
    f"  {MINT}/mcp-preset{RESET} <name>  install a server preset (design)",
    f"  {MINT}/keys{RESET}              list vaulted API keys (masked)",
    f"  {MINT}/key{RESET} <NAME>       set a key (e.g. /key GROQ_API_KEY)",
    f"  {MINT}/key-del{RESET} <NAME>   remove a key from the vault",
    f"  {MINT}/provider{RESET} <name>  nvidia | groq | openrouter | deepseek | openai …",
    f"  {MINT}/proxy{RESET}             start/reuse the free-claume proxy",
    f"  {MINT}/proxy-ui{RESET}         open the luxurious proxy dashboard in browser",
    f"  {MINT}/skills{RESET}            list installed skills",
    f"  {MINT}/skill{RESET} <owner/repo>  download a skill from GitHub",
    f"  {MINT}/mcp{RESET}               list configured MCP servers + live tools",
    f"  {MINT}/mcp-add{RESET} <name> <command...>  register an MCP server",
    f"  {MINT}/mcp-del{RESET} <name>    remove an MCP server",
    f"  {MINT}/md{RESET} <name>         create a new instruction (.md) file",
    f"  {MINT}/git{RESET}               git status",
    f"  {MINT}/config{RESET}            show config",
    f"  {MINT}/doctor{RESET}            environment health check",
    f"  {MINT}/update{RESET}            self-update from GitHub",
    f"  {MINT}/recommend{RESET}         model recommendations for your machine",
    f"  {MINT}/exit{RESET}              quit",
]


def cmd_help() -> None:
    print("\n".join(HELP_LINES))


def cmd_model(args: List[str]) -> None:
    cfg = config.Config()
    if not args:
        current = cfg.model
        print(f"{GREY}current model:{RESET} {MINT}{current}{RESET}")
        print(f"{GREY}popular NVIDIA NIM models:{RESET}")
        for m in proxy.DEFAULT_MODEL_POOL:
            marker = f"{GREEN}▸{RESET}" if m == current else " "
            print(f"  {marker} {m}")
        print(f"{GREY}set with: /model meta/llama-3.3-70b-instruct{RESET}")
        return
    model = args[0]
    cfg.set("model", model)
    print(f"{GREEN}✔ model set to {model}{RESET}")


def cmd_effort(args: List[str]) -> None:
    cfg = config.Config()
    if not args or args[0] not in ("fast", "balanced", "deep"):
        print(f"{GREY}effort = {MINT}{cfg.effort}{RESET} {GREY}(choose: fast | balanced | deep){RESET}")
        return
    cfg.set("effort", args[0])
    print(f"{GREEN}✔ effort = {args[0]}{RESET}")


def cmd_auto(args: List[str], agent: "Agent") -> None:
    """Back-compat: /auto on|off now maps onto the mode system."""
    if not args:
        state = "on" if agent.mode == "auto" else "off"
        print(f"{GREY}auto mode is {MINT}{state}{RESET} {GREY}(/mode auto|manual){RESET}")
        return
    agent.set_mode("auto" if args[0].lower() in ("on", "1", "true") else "manual")
    print(f"{GREEN}✔ mode = {agent.mode}{RESET}")


def cmd_mode(args: List[str], agent: "Agent") -> None:
    from .ui import mode_chip

    if not args:
        print(f"{GREY}current:{RESET} {mode_chip(agent.mode)}")
        print(f"{GREY}  manual — ask before every action · accept — auto-approve edits · "
              f"plan — read-only research · auto — hands-off (destructive still asks){RESET}")
        return
    mode = args[0].lower()
    if mode not in ("manual", "accept", "plan", "auto"):
        print(f"{RED}unknown mode '{mode}' — manual | accept | plan | auto{RESET}")
        return
    agent.set_mode(mode)
    print(f"{GREEN}✔ {mode_chip(mode)}{RESET}")
    if mode == "plan":
        print(f"{GREY}  claume will research and present a plan; no writes until you approve.{RESET}")


def cmd_keys() -> None:
    keys = keyvault.list_keys()
    if not keys:
        print(f"{GREY}vault is empty — add one: /key GROQ_API_KEY{RESET}")
        return
    print(f"{GREEN}vaulted keys{RESET}")
    for name, masked in sorted(keys.items()):
        print(f"  {MINT}{name:<22}{RESET} {GREY}{masked}{RESET}")


def cmd_key(args: List[str]) -> None:
    if not args:
        print(f"{RED}usage: /key NAME{RESET}")
        return
    name = args[0].upper()
    print(f"{GREY}paste the value for {MINT}{name}{GREY} (input hidden):{RESET}")
    import getpass

    value = getpass.getpass("  > ")
    if not value.strip():
        print(f"{RED}✗ empty key ignored{RESET}")
        return
    keyvault.set_key(name, value)
    config.Config().set(f"key_vault.{name}", True)
    print(f"{GREEN}✔ {name} stored in vault{RESET}")


def cmd_key_del(args: List[str]) -> None:
    if not args:
        print(f"{RED}usage: /key-del NAME{RESET}")
        return
    ok = keyvault.delete_key(args[0])
    msg = f"✔ removed {args[0].upper()}" if ok else f"✗ {args[0].upper()} not found"
    print(f"{GREEN if ok else RED}{msg}{RESET}")


def cmd_provider(args: List[str]) -> None:
    from .llm import PROVIDER_ENDPOINTS

    cfg = config.Config()
    if not args:
        print(f"{GREY}provider = {MINT}{cfg.get('provider')}{RESET}")
        for name in PROVIDER_ENDPOINTS:
            marker = f"{GREEN}▸{RESET}" if name == cfg.get("provider") else " "
            print(f"  {marker} {name}")
        return
    provider = args[0].lower()
    if provider not in PROVIDER_ENDPOINTS:
        print(f"{RED}unknown provider '{provider}'. Known: {', '.join(PROVIDER_ENDPOINTS)}{RESET}")
        return
    cfg.set("provider", provider)
    print(f"{GREEN}✔ provider = {provider} → {PROVIDER_ENDPOINTS[provider]}{RESET}")


def cmd_proxy() -> None:
    if proxy.is_running():
        cfg = config.Config()
        base = f"http://{cfg.get('proxy_host', '127.0.0.1')}:{cfg.get('proxy_port', 8000)}/v1"
        print(f"{GREEN}✔ proxy is live at {base}{RESET}")
        return
    config.clear_proxy_state()  # drop stale state from dead runs
    if not proxy.collect_keys():
        print(f"{GOLD}⚠ no NVIDIA key — prompting now (free from build.nvidia.com){RESET}")
        key = proxy.prompt_for_nvidia_key()
        if not key:
            print(f"{RED}✗ cannot start proxy without a key{RESET}")
            return
    print(f"{GREY}starting free-claume proxy…{RESET}")
    try:
        proxy.start_server()
        cfg = config.Config()
        base = f"http://{cfg.get('proxy_host', '127.0.0.1')}:{cfg.get('proxy_port', 8000)}/v1"
        print(f"{GREEN}✔ free-claume proxy → {base}{RESET}")
        print(f"{GREY}  tip: run {MINT}claume proxy{GREY} in a separate terminal to keep it alive after exiting claume{RESET}")
    except Exception as exc:
        print(f"{RED}✗ proxy failed: {exc}{RESET}")


def cmd_proxy_ui() -> None:
    """Open the proxy Admin UI (key + model picker) in the browser."""
    import webbrowser

    cfg = config.Config()
    base = f"http://{cfg.get('proxy_host', '127.0.0.1')}:{cfg.get('proxy_port', 8000)}"
    if not proxy.is_running():
        config.clear_proxy_state()
        if not proxy.collect_keys():
            print(f"{GOLD}⚠ no NVIDIA key yet — paste it in the admin UI that just opened{RESET}")
        try:
            proxy.start_server()
        except Exception as exc:
            print(f"{RED}✗ proxy failed to start: {exc}{RESET}")
            return
    url = f"{base}/admin"
    print(f"{GREEN}✦ admin UI → {url}{RESET}")
    webbrowser.open(url)


# ---------------------------------------------------------------------------
# Skills
# ---------------------------------------------------------------------------
def cmd_skills() -> None:
    sdir = config.skills_dir()
    if not sdir.exists():
        print(f"{GREY}no skills installed — try: /skill anthropics/skills{RESET}")
        return
    found = sorted(p.name for p in sdir.iterdir() if p.is_dir())
    if not found:
        print(f"{GREY}no skills installed{RESET}")
        return
    print(f"{GREEN}installed skills ({len(found)}){RESET}")
    for name in found:
        print(f"  {MINT}•{RESET} {name}")


def cmd_skill(args: List[str]) -> None:
    if not args or "/" not in args[0]:
        print(f"{RED}usage: /skill owner/repo  (e.g. /skill anthropics/skills){RESET}")
        return
    repo = args[0]
    name = repo.split("/")[-1]
    dest = config.skills_dir() / name
    if dest.exists():
        print(f"{GOLD}⚠ {name} exists — re-downloading{RESET}")
        shutil.rmtree(dest, ignore_errors=True)
    config.skills_dir().mkdir(parents=True, exist_ok=True)
    rc = subprocess.call(
        ["git", "clone", "--depth", "1", f"https://github.com/{repo}", str(dest)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if rc == 0:
        count = sum(1 for p in dest.rglob("*.md"))
        print(f"{GREEN}✔ skill '{name}' installed ({count} markdown files){RESET}")
    else:
        print(f"{RED}✗ git clone failed for {repo}{RESET}")


# ---------------------------------------------------------------------------
# MCP
# ---------------------------------------------------------------------------
def cmd_mcp() -> None:
    servers = config.Config().get("mcp_servers", {})
    if not servers:
        print(f"{GREY}no MCP servers configured{RESET}")
        print(f"{GREY}  quick start: {MINT}/mcp-preset design{GREY} (21st.dev + reactbits + motion + shadcnspace){RESET}")
        print(f"{GREY}  or: /mcp-add name command args…{RESET}")
        return
    print(f"{GREEN}MCP servers{RESET}")
    for name, spec in sorted(servers.items()):
        desc = spec.get("description", "") if isinstance(spec, dict) else ""
        print(f"  {MINT}•{RESET} {name}: {GREY}{spec.get('command', spec) if isinstance(spec, dict) else spec}{RESET}")
        if desc:
            print(f"    {GREY}{desc[:90]}{RESET}")
    # Live tool probe (may spawn servers — keep it best effort)
    try:
        from . import mcp as mcpmod

        tools = mcpmod.list_all_tools()
        live = {k: v for k, v in tools.items() if v and not v[0].startswith("<error")}
        if live:
            print(f"{GREEN}live tools{RESET}")
            for name, tnames in live.items():
                shown = ", ".join(tnames[:8])
                extra = f" … +{len(tnames) - 8}" if len(tnames) > 8 else ""
                print(f"  {MINT}{name}{RESET} {GREY}({len(tnames)}){RESET}: {shown}{extra}")
    except Exception as exc:
        print(f"{GREY}  (tool probe unavailable: {exc}){RESET}")


def cmd_mcp_add(args: List[str]) -> None:
    if len(args) < 2:
        print(f"{RED}usage: /mcp-add <name> <command> [args...]{RESET}")
        return
    name, command = args[0], " ".join(args[1:])
    cfg = config.Config()
    servers = cfg.get("mcp_servers", {})
    servers[name] = {"command": command, "enabled": True}
    cfg.set("mcp_servers", servers)
    print(f"{GREEN}✔ registered MCP server '{name}'{RESET}")


def cmd_mcp_del(args: List[str]) -> None:
    if not args:
        print(f"{RED}usage: /mcp-del <name>{RESET}")
        return
    cfg = config.Config()
    servers = cfg.get("mcp_servers", {})
    if args[0] in servers:
        del servers[args[0]]
        cfg.set("mcp_servers", servers)
        print(f"{GREEN}✔ removed '{args[0]}'{RESET}")
    else:
        print(f"{RED}✗ '{args[0]}' not found{RESET}")


# ---------------------------------------------------------------------------
# .md instruction files
# ---------------------------------------------------------------------------
def cmd_md(args: List[str], workspace: Path) -> None:
    if not args:
        print(f"{RED}usage: /md <name>  → creates CLAUDE.md-style instructions{RESET}")
        return
    name = args[0]
    if not name.endswith(".md"):
        name += ".md"
    target = workspace / name
    if target.exists():
        print(f"{GOLD}⚠ {name} exists — loading it instead{RESET}")
        print(target.read_text(encoding="utf-8", errors="replace")[:4000])
        return
    template = (
        f"# {name[:-3]} instructions\n\n"
        "<!-- claume reads this file as project guidance. -->\n"
        "## Project conventions\n\n- \n\n"
        "## Commands\n\n- Build: \n- Test: \n\n"
        "## Style\n\n- \n"
    )
    target.write_text(template, encoding="utf-8")
    print(f"{GREEN}✔ created {name} — edit it, claume picks it up automatically{RESET}")


def load_instruction_md(workspace: Path) -> Optional[str]:
    """Auto-load CLAUDE.md / CLAUUME.md / claume.md if present."""
    for candidate in ("CLAUUME.md", "claume.md", "CLAUDE.md"):
        p = workspace / candidate
        if p.exists():
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
                return f"Project instructions from {candidate}:\n\n{text[:8000]}"
            except Exception:
                pass
    return None


# ---------------------------------------------------------------------------
# Maintenance
# ---------------------------------------------------------------------------
def cmd_config() -> None:
    cfg = config.Config()
    safe = dict(cfg._data)
    safe.pop("key_vault", None)
    print(f"{GREEN}config ({config.config_path()}){RESET}")
    print(json.dumps(safe, indent=2, default=str))


def cmd_doctor() -> None:
    print(f"{GREEN}┌─ doctor ─────────────────────────────────────────────┐{RESET}")

    def row(label: str, ok: bool, note: str = "") -> None:
        mark = f"{GREEN}✔{RESET}" if ok else f"{RED}✗{RESET}"
        print(f"│ {mark} {label:<20} {GREY}{note}{RESET}")

    row("python", sys.version_info >= (3, 9), sys.version.split()[0])
    row("git", shutil.which("git") is not None, shutil.which("git") or "not found")
    keys = proxy.collect_keys()
    row("nvidia key", bool(keys), f"{len(keys)} key(s) in vault/env")

    live = proxy.is_running()
    state = config.load_proxy_state()
    row("proxy", live,
        state.get("base_url", "") if live else "not running — run 'claume proxy' or /proxy")
    sdir = config.skills_dir()
    row("skills", sdir.exists(), str(sdir))
    row("vault", config.claume_dir().exists(), str(config.claume_dir()))
    print(f"{'─' * 56}")
    print(f"{GREY}tip: run /proxy if the proxy row shows ✗{RESET}")


def cmd_update() -> None:
    """Self-update: pull latest from the permanent upstream repo."""
    from . import config as cfgmod

    repo = cfgmod.REPO_WEB
    print(f"{GREY}self-update: checking {repo}{RESET}")
    try:
        app_dir = Path(__file__).resolve().parent.parent
        if (app_dir / ".git").exists():
            # Make sure origin points at the permanent upstream.
            try:
                cur = subprocess.run(
                    ["git", "remote", "get-url", "origin"],
                    cwd=app_dir, capture_output=True, text=True, timeout=10,
                ).stdout.strip()
                if cur and cur.rstrip("/") != cfgmod.REPO_URL.rstrip("/") and cur.rstrip("/") != cfgmod.REPO_WEB:
                    subprocess.run(
                        ["git", "remote", "set-url", "origin", cfgmod.REPO_URL],
                        cwd=app_dir, capture_output=True, text=True, timeout=10,
                    )
                    print(f"{GREY}  re-pointed origin → {cfgmod.REPO_URL}{RESET}")
            except Exception:
                pass
            rc = subprocess.call(["git", "pull", "--ff-only"], cwd=app_dir)
            if rc == 0:
                print(f"{GREEN}✔ updated via git pull{RESET}")
            else:
                print(f"{GOLD}⚠ git pull failed — update manually{RESET}")
        else:
            print(f"{GREY}not a git checkout; re-run installer to update:{RESET}")
            print(f"  {MINT}irm https://raw.githubusercontent.com/kayefande-droid/claume-code/main/install.ps1 | iex{RESET}")
    except Exception as exc:
        print(f"{RED}✗ update failed: {exc}{RESET}")
    config.Config().set("last_version", __version__)


def cmd_recommend() -> None:
    print(f"{GREEN}recommended models (free, via NVIDIA NIM){RESET}")
    recs = [
        ("nvidia/nemotron-3-super-120b-a12b", "current best default; fast + tool-capable"),
        ("openai/gpt-oss-120b", "strong reasoning; great at code review"),
        ("qwen/qwen3-coder-480b-a35b-instruct", "code-edit specialist (480B MoE)"),
        ("deepseek-ai/deepseek-r1", "chain-of-thought monster for hard bugs"),
        ("meta/llama-3.1-405b-instruct", "deep generalist; slower, use effort=deep"),
    ]
    for model, why in recs:
        print(f"  {MINT}{model:<42}{RESET} {GREY}{why}{RESET}")
    print(f"{GREY}set with: /model <name> · or pick in the admin UI: /proxy-ui{RESET}")


def cmd_git(agent: "Agent") -> None:
    out, _ = registry.execute(agent.workspace, "git_status", {})
    print(out)


# ---------------------------------------------------------------------------
# v2 commands: modes, themes, clipboard, sessions, subagents, MCP pipeline
# ---------------------------------------------------------------------------
def cmd_theme(args: List[str], ui: "Any") -> None:
    from . import ui as uimod

    if not args:
        print(f"{GREEN}themes{RESET} {GREY}(current: {uimod.current_theme()}){RESET}")
        for name, t in uimod.THEMES.items():
            marker = f"{GREEN}▸{RESET}" if name == uimod.current_theme() else " "
            print(f"  {marker} {MINT}{name:<14}{RESET} {GREY}{t['label']}{RESET}")
        print(f"{GREY}switch with: /theme <name>  ·  persists across restarts{RESET}")
        return
    name = args[0].lower()
    if not uimod.set_theme(name):
        print(f"{RED}unknown theme '{name}' — /theme lists all{RESET}")
        return
    config.Config().set("theme", name)
    print(f"{GREEN}✔ theme → {uimod.THEMES[name]['label']}{RESET}")


def cmd_expand(args: List[str], ui: "Any") -> None:
    if not args:
        state = "on" if ui.expand_output else "off"
        print(f"{GREY}expand output = {MINT}{state}{RESET} {GREY}(/expand on|off){RESET}")
        return
    ui.expand_output = args[0].lower() in ("on", "1", "true")
    config.Config().set("expand_output", ui.expand_output)
    print(f"{GREEN}✔ expand output {'on' if ui.expand_output else 'off'}{RESET}")


def cmd_copy(args: List[str], ui: "Any") -> None:
    from .ui import copy_to_clipboard

    text = " ".join(args) if args else ui.last_final
    if not text:
        print(f"{GREY}nothing to copy yet — /copy <text> or run a task first{RESET}")
        return
    if copy_to_clipboard(text):
        preview = " ".join(text.split())[:60]
        print(f"{GREEN}✔ copied to clipboard{RESET} {GREY}({preview}…){RESET}")
    else:
        print(f"{RED}✗ clipboard unavailable in this terminal{RESET}")


def cmd_mascot(ui: "Any") -> None:
    ui.mascot.show(mood="happy", note="at your service")


def cmd_projects(args: List[str], agent: "Agent") -> None:
    from . import config as cfgmod

    root = cfgmod.projects_dir()
    entries = sorted(p for p in root.iterdir() if p.is_dir())
    print(f"{GREEN}claume projects{RESET} {GREY}({root}){RESET}")
    if not entries:
        print(f"{GREY}  (empty) — build something! try:{RESET} {MINT}build a snake game in projects/snake-game{RESET}")
        return
    for p in entries:
        try:
            n_files = sum(1 for _ in p.rglob("*") if _.is_file())
        except Exception:
            n_files = 0
        print(f"  {MINT}•{RESET} {p.name}{GREY}  ({n_files} files){RESET}")
    print(f"{GREY}  open one with: cd <path> then run claume inside it{RESET}")


def cmd_project(args: List[str], agent: "Agent") -> None:
    from . import config as cfgmod

    if not args:
        print(f"{RED}usage: /project <name>{RESET}")
        return
    root = cfgmod.projects_dir()
    target = root / args[0]
    target.mkdir(parents=True, exist_ok=True)
    print(f"{GREEN}✔ project folder ready:{RESET} {MINT}{target}{RESET}")
    print(f"{GREY}  tell claume: build <thing> inside {target}{RESET}")


def cmd_repo(args: List[str], agent: "Agent") -> None:
    from . import config as cfgmod

    print(f"{GREEN}upstream repo{RESET} {MINT}{cfgmod.REPO_WEB}{RESET}")
    app_dir = Path(__file__).resolve().parent.parent
    if (app_dir / ".git").exists():
        try:
            out = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                cwd=app_dir, capture_output=True, text=True, timeout=10,
            )
            remote = out.stdout.strip() or "(no origin)"
            print(f"{GREY}  git origin:{RESET} {remote}")
            if remote.rstrip("/").replace(".git", "") != cfgmod.REPO_WEB:
                print(f"{GOLD}  ⚠ remote differs from upstream — /update pulls from your checkout's remote{RESET}")
        except Exception as exc:
            print(f"{GREY}  (git remote unavailable: {exc}){RESET}")
    else:
        print(f"{GREY}  this install is not a git checkout — /update re-runs the installer{RESET}")
    print(f"{GREY}  issues/PRs:{RESET} {cfgmod.REPO_WEB}/issues{RESET}")


def cmd_session(args: List[str], agent: "Agent") -> None:
    from . import sessions

    if args:
        sid = args[0]
        data = sessions.load_session(sid)
        if not data:
            print(f"{RED}✗ session '{sid}' not found{RESET}")
            return
        agent.session_id = sid
        agent.history = list(data.get("messages", []))
        agent.step = 0
        print(f"{GREEN}✔ loaded session {sid} ({len(agent.history)} messages){RESET}")
        return
    sessions_list = sessions.list_sessions(limit=5)
    cur = agent.session_id or "(none yet)"
    print(f"{GREY}current session:{RESET} {MINT}{cur}{RESET}")
    if sessions_list:
        print(f"{GREY}recent:{RESET}")
        for s in sessions_list:
            print(f"  {MINT}{s['id']}{RESET} {GREY}· {s['turns']} turns · {s['title']}{RESET}")


def cmd_resume(args: List[str], agent: "Agent") -> None:
    from . import sessions

    entries = sessions.list_sessions(limit=12)
    if not entries:
        print(f"{GREY}no saved sessions yet{RESET}")
        return
    print(f"{GREEN}saved sessions{RESET}")
    for i, s in enumerate(entries, 1):
        print(f"  {MINT}{i:>2}{RESET}. {s['id']}  {GREY}{s['title']}{RESET}")
    try:
        raw = input(f"{GREY}resume # (enter to cancel):{RESET} ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return
    if not raw.isdigit() or not (1 <= int(raw) <= len(entries)):
        print(f"{GREY}cancelled{RESET}")
        return
    sid = entries[int(raw) - 1]["id"]
    data = sessions.load_session(sid)
    if not data:
        print(f"{RED}✗ could not load {sid}{RESET}")
        return
    agent.session_id = sid
    agent.history = list(data.get("messages", []))
    agent.step = 0
    print(f"{GREEN}✔ resumed {sid} — {len(agent.history)} messages back in context{RESET}")


def cmd_continue(args: List[str], agent: "Agent") -> None:
    from . import sessions

    sid = sessions.latest_session_id(exclude=agent.session_id)
    if not sid:
        print(f"{GREY}no previous session found{RESET}")
        return
    data = sessions.load_session(sid)
    if not data:
        print(f"{RED}✗ could not load {sid}{RESET}")
        return
    agent.session_id = sid
    agent.history = list(data.get("messages", []))
    agent.step = 0
    title = " ".join(
        next((m["content"] for m in agent.history if m.get("role") == "user"), "")[:70].split()
    )
    print(f"{GREEN}✔ continued session {sid}{RESET} {GREY}· {title}{RESET}")


def cmd_agents(args: List[str], agent: "Agent") -> None:
    """/agents task1 ; task2 ; task3 — parallel subagents, merged report."""
    raw = " ".join(args)
    if not raw:
        print(f"{RED}usage: /agents task one ; task two ; task three{RESET}")
        print(f"{GREY}  tasks separated by ';' run as parallel subagents, then merged.{RESET}")
        return
    tasks = [t.strip() for t in raw.split(";") if t.strip()]
    if len(tasks) < 2:
        print(f"{GOLD}⚠ one task given — running inline (add ';' to split into parallel agents){RESET}")
    specs = [{"name": f"agent-{i + 1}", "task": t} for i, t in enumerate(tasks)]
    from . import subagents

    agent.ui.render_info(f"spawning {len(specs)} subagent(s)…")
    results = subagents.run_swarm(agent.workspace, specs, ui=agent.ui)
    merged = subagents.combine_results(results, agent.workspace)
    for r in results:
        icon = f"{RED}✗" if r.error else f"{GREEN}✓"
        print(f"{icon} {MINT}{r.name}{RESET} {GREY}({r.steps} steps, {r.tool_calls} calls, {r.duration:.1f}s){RESET}")
        summary = r.error or (r.summary[:400] if r.summary else "(no summary)")
        for line in summary.splitlines()[:8]:
            print(f"  {GREY}│{RESET} {SILVER}{line[:140]}{RESET}")
    print(f"\n{GREEN}❯ merged report{RESET}")
    print(f"{BOLD}{merged}{RESET}")
    try:
        agent.ui.last_final = merged
    except Exception:
        pass


def cmd_design(args: List[str], agent: "Agent") -> None:
    from . import mcp

    request = " ".join(args)
    if not request:
        print(f"{RED}usage: /design <what to build>  e.g. /design fluid bento landing hero{RESET}")
        return
    agent.ui.render_info("running the claume Link System (design pipeline)…")
    report, is_err = mcp.design_pipeline(request, agent.workspace)
    print(report)
    if not is_err:
        # Hand the pipeline report to the agent so it can build immediately.
        agent.history.append(
            {
                "role": "user",
                "content": (
                    f"DESIGN PIPELINE OUTPUT for '{request}':\n{report[:8000]}\n\n"
                    "Use these blueprints/blocks/motion specs to build the UI now. "
                    "No generic placeholder divs." 
                ),
            }
        )
        print(f"{GREY}  pipeline output loaded — type build it to start implementation{RESET}")


def cmd_mcp_preset(args: List[str]) -> None:
    from . import mcp

    if not args or args[0] not in mcp.PRESETS:
        print(f"{GREY}available presets: {', '.join(mcp.PRESETS)}{RESET}")
        print(f"{GREY}  design = 21st.dev + reactbits + motion + shadcnspace (UI stack){RESET}")
        return
    preset = mcp.PRESETS[args[0]]
    cfg = config.Config()
    servers = cfg.get("mcp_servers", {})
    added = []
    for name, spec in preset.items():
        if name in servers:
            print(f"{GOLD}⚠ {name} already configured — skipping{RESET}")
            continue
        servers[name] = dict(spec)
        added.append(name)
    cfg.set("mcp_servers", servers)
    if added:
        print(f"{GREEN}✔ installed preset '{args[0]}': {', '.join(added)}{RESET}")
        print(f"{GREY}  tools bridge automatically on first use — try /design <prompt>{RESET}")
    else:
        print(f"{GREY}nothing to add{RESET}")


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------
def handle_command(line: str, agent: "Agent") -> bool:
    """Handle a /command. Returns True if it was a claume command."""
    if not line.startswith("/"):
        return False
    parts = line[1:].split()
    if not parts:
        return True
    name, args = parts[0], parts[1:]

    if name in ("help", "?"):
        cmd_help()
    elif name == "new":
        agent.reset()
        print(f"{GREEN}✔ fresh conversation{RESET}")
    elif name == "model":
        cmd_model(args)
    elif name == "effort":
        cmd_effort(args)
    elif name == "auto":
        cmd_auto(args, agent)
    elif name == "mode":
        cmd_mode(args, agent)
    elif name == "theme":
        cmd_theme(args, agent.ui)
    elif name == "expand":
        cmd_expand(args, agent.ui)
    elif name == "copy":
        cmd_copy(args, agent.ui)
    elif name == "mascot":
        cmd_mascot(agent.ui)
    elif name == "projects":
        cmd_projects(args, agent)
    elif name == "project":
        cmd_project(args, agent)
    elif name == "repo":
        cmd_repo(args, agent)
    elif name == "session":
        cmd_session(args, agent)
    elif name == "resume":
        cmd_resume(args, agent)
    elif name == "continue":
        cmd_continue(args, agent)
    elif name == "agents":
        cmd_agents(args, agent)
    elif name == "design":
        cmd_design(args, agent)
    elif name == "mcp-preset":
        cmd_mcp_preset(args)
    elif name == "keys":
        cmd_keys()
    elif name == "key":
        cmd_key(args)
    elif name == "key-del":
        cmd_key_del(args)
    elif name == "provider":
        cmd_provider(args)
    elif name == "proxy":
        cmd_proxy()
    elif name == "proxy-ui":
        cmd_proxy_ui()
    elif name == "skills":
        cmd_skills()
    elif name == "skill":
        cmd_skill(args)
    elif name == "mcp":
        cmd_mcp()
    elif name == "mcp-add":
        cmd_mcp_add(args)
    elif name == "mcp-del":
        cmd_mcp_del(args)
    elif name == "md":
        cmd_md(args, agent.workspace)
    elif name == "config":
        cmd_config()
    elif name == "doctor":
        cmd_doctor()
    elif name == "update":
        cmd_update()
    elif name == "recommend":
        cmd_recommend()
    elif name == "git":
        cmd_git(agent)
    elif name in ("exit", "quit"):
        raise SystemExit(0)
    else:
        print(f"{RED}unknown command /{name}{RESET} {GREY}— try /help{RESET}")
    return True
