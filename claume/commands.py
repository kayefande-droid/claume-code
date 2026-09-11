"""Slash command handlers for the claume REPL."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

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
    f"  {MINT}/auto{RESET} [on|off]    toggle auto mode (fewer confirmations)",
    f"  {MINT}/keys{RESET}              list vaulted API keys (masked)",
    f"  {MINT}/key{RESET} <NAME>       set a key (e.g. /key GROQ_API_KEY)",
    f"  {MINT}/key-del{RESET} <NAME>   remove a key from the vault",
    f"  {MINT}/provider{RESET} <name>  nvidia | groq | openrouter | deepseek | openai …",
    f"  {MINT}/proxy{RESET}             start/reuse the free-claume proxy",
    f"  {MINT}/proxy-ui{RESET}         open the luxurious proxy dashboard in browser",
    f"  {MINT}/skills{RESET}            list installed skills",
    f"  {MINT}/skill{RESET} <owner/repo>  download a skill from GitHub",
    f"  {MINT}/mcp{RESET}               list configured MCP servers",
    f"  {MINT}/mcp-add{RESET} <name> <command...>  register an MCP server",
    f"  {MINT}/mcp-del{RESET} <name>    remove an MCP server",
    f"  {MINT}/md{RESET} <name>         create a new instruction (.md) file",
    f"  {MINT}/md-load{RESET}           load instructions from a .md file this turn",
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
    if not args:
        state = "on" if agent.auto_mode else "off"
        print(f"{GREY}auto mode is {MINT}{state}{RESET} {GREY}(/auto on|off){RESET}")
        return
    agent.auto_mode = args[0].lower() in ("on", "1", "true")
    config.Config().set("auto_mode", agent.auto_mode)
    state = "on — claume will auto-approve caution-level actions" if agent.auto_mode else "off — confirmations restored"
    print(f"{GREEN}✔ auto mode {state}{RESET}")
    if agent.auto_mode:
        print(f"{GOLD}  (destructive commands still ask — always.){RESET}")


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
    state = config.load_proxy_state()
    if state:
        print(f"{GREEN}✔ proxy already running at {state['base_url']}{RESET}")
        return
    print(f"{GREY}starting free-claume proxy…{RESET}")
    try:
        proxy.start_server()
        state = config.load_proxy_state()
        print(f"{GREEN}✔ free-claume proxy → {state['base_url']}{RESET}")
        print(f"{GREY}  provider is 'nvidia' → the agent talks to this proxy{RESET}")
    except Exception as exc:
        print(f"{RED}✗ proxy failed: {exc}{RESET}")


def cmd_proxy_ui() -> None:
    """Serve the dashboard and open it."""
    from .proxy_ui import serve_and_open

    serve_and_open()


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
        print(f"{GREY}no MCP servers configured — /mcp-add name command args…{RESET}")
        return
    print(f"{GREEN}MCP servers{RESET}")
    for name, spec in sorted(servers.items()):
        print(f"  {MINT}•{RESET} {name}: {GREY}{spec}{RESET}")


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
    from . import llm

    row("proxy", proxy.is_running() or config.load_proxy_state() is not None,
        config.load_proxy_state()["base_url"] if config.load_proxy_state() else "not started")
    sdir = config.skills_dir()
    row("skills", sdir.exists(), str(sdir))
    row("vault", config.claume_dir().exists(), str(config.claume_dir()))
    print(f"{'─' * 56}")
    print(f"{GREY}tip: run /proxy if the proxy row shows ✗{RESET}")


def cmd_update() -> None:
    """Self-update: pull latest from GitHub (or pip reinstall later)."""
    repo = "https://github.com/kayefande-droid/claume-code"
    print(f"{GREY}self-update: checking {repo}{RESET}")
    try:
        app_dir = Path(__file__).resolve().parent.parent
        if (app_dir / ".git").exists():
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
        ("meta/llama-3.3-70b-instruct", "best all-round coder; fast on NVIDIA's infra"),
        ("meta/llama-3.1-405b-instruct", "deepest reasoning; slower, use effort=deep"),
        ("qwen/qwen2.5-coder-32b-instruct", "specialized for code edits & diffs"),
        ("deepseek-ai/deepseek-r1", "chain-of-thought monster for hard bugs"),
    ]
    for model, why in recs:
        print(f"  {MINT}{model:<38}{RESET} {GREY}{why}{RESET}")
    print(f"{GREY}set with: /model <name>{RESET}")


def cmd_git(agent: "Agent") -> None:
    out, _ = registry.execute(agent.workspace, "git_status", {})
    print(out)


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
