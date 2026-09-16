"""Slash command handlers for the claume REPL."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from . import config, keyvault, proxy
from .tools import registry
from .ui import ACCENT, BLUE, BOLD, DIM, GOLD, GREEN, GREY, ITALIC, MINT, MUTED, RED, RESET, SILVER, box
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
    f"  {MINT}/effort{RESET} <level>   fast | balanced | deep | ultra (step budgets scale too)",
    f"  {MINT}/auto{RESET} [on|off]    toggle auto mode (alias of /mode auto|manual)",
    f"  {MINT}/mode{RESET} [name]      manual | accept | plan | auto (Shift+Tab cycles)",
    f"  {MINT}/theme{RESET} [name]     color theme: nvidia-green, claude-orange, cyber-blue, synthwave, matrix, sunset, mono",
    f"  {MINT}/expand{RESET} [on|off]  show full tool output (default: 14 lines)",
    f"  {MINT}/copy{RESET} [text]      copy the last answer (or given text) to clipboard",
    f"  {MINT}/copymode{RESET}         click mode: mouse-click a ‘+N more lines’ hint to expand it · drag to copy",
    f"  {MINT}/ask{RESET} <question>    side question — answered mid-task without hindering it",
    f"  {MINT}/skip{RESET}              interrupt the running task (queue stays live)",
    f"  {MINT}/queue{RESET}             explain the live task queue",
    f"  {MINT}/mascot{RESET}           show the claume pixel bot (eyes follow your mouse)",
    f"  {MINT}/voice{RESET} [on|off]   AI voice responses (British male/female accents)",
    f"  {MINT}/voice-accent{RESET} <a> male-british | female-british | male | female",
    f"  {MINT}/say{RESET} <text>       make claume speak text now",
    f"  {MINT}/hear{RESET}             one voice command (needs: pip install SpeechRecognition pyaudio)",
    f"  {MINT}/projects{RESET}         list everything claume built (~/.claume/projects)",
    f"  {MINT}/project{RESET} <name>   show/create a project folder there",
    f"  {MINT}/repo{RESET}             show the upstream GitHub repo + git remote status",
    f"  {MINT}/session{RESET} [id]     show session info / start a specific one",
    f"  {MINT}/sessions{RESET}         list sessions with project name + time",
    f"  {MINT}/rename{RESET} <id|-> <project> [name]  rename current or given session",
    f"  {MINT}/resume{RESET}           resume a past session (interactive picker)",
    f"  {MINT}/continue{RESET}         resume the most recent session",
    f"  {MINT}/agents{RESET} <t1>; <t2>  run parallel subagents and merge reports",
    f"  {MINT}/design{RESET} <prompt>  run the MCP design pipeline (Link System)",
    f"  {MINT}/image{RESET} <path>    attach an image (png/jpg/webp) to your next task",
    f"  {MINT}/ide{RESET}            IDE integration status · /ide open <path> [line] · /ide reveal <path>",
    f"  {MINT}/social{RESET}         Telegram channel: setup · post · post-image · post-video",
    f"  {MINT}/email{RESET}          send mail + read inbox (verification links) — free app-password setup",
    f"  {MINT}/payout{RESET}         monetization ledger + MTN MoMo payout intents (confirmation-gated)",
    f"  {MINT}/webdesign{RESET} <prompt>  build a website/UI now — studio brief + real fonts/assets",
    f"  {MINT}/mcp-preset{RESET} <name>  install a server preset (design)",
    f"  {MINT}/keys{RESET}             list vaulted API keys (masked)",
    f"  {MINT}/key{RESET} <NAME>       set a key (e.g. /key GROQ_API_KEY)",
    f"  {MINT}/key-del{RESET} <NAME>   remove a key from the vault",
    f"  {MINT}/provider{RESET} <name>  nvidia | groq | openrouter | deepseek | openai …",
    f"  {MINT}/proxy{RESET}            start/reuse the free-claume proxy",
    f"  {MINT}/proxy-ui{RESET}         open the luxurious proxy dashboard in browser",
    f"  {MINT}/skills{RESET}           list skills with active/inactive status",
    f"  {MINT}/plugins{RESET}          list plugins — integrations & machinery (vs skills)",
    f"  {MINT}/plugin-on|off{RESET} <name>  activate/deactivate a plugin (graphify, jarvis)",
    f"  {MINT}/jarvis{RESET}           launch the jarvis desktop voice assistant (or /jarvis cli)",
    f"  {MINT}/graphify{RESET} [path]  build a knowledge graph from a folder (plugin)",
    f"  {MINT}/memory{RESET} [list]     persistent memory: /memory save <name> <fact> · read · forget",
    f"  {MINT}/look{RESET} [question]   claume SEES your screen: screenshot + vision analysis of errors",
    f"  {MINT}/bridge{RESET} [port]     offline phone bridge: QR link over LAN/Bluetooth PAN, no internet",
    f"  {MINT}/skill{RESET} <owner/repo>  install a skill from GitHub (e.g. ui-ux-pro-max)",
    f"  {MINT}/skill-rm{RESET} <name>  remove an installed skill",
    f"  {MINT}/skill-on{RESET} <name>  activate a skill (its .md guides every task)",
    f"  {MINT}/skill-off{RESET} <name> deactivate a skill",
    f"  {MINT}/skill-all{RESET} [on|off]  activate every skill at once (or none)",
    f"  {MINT}/skill-use{RESET} <name> adopt one skill for the next turn only",
    f"  {MINT}/skill-run{RESET} <skill> <script> [args]  run a bundled skill script",
    f"  {MINT}/mcp{RESET}              list servers with enabled/disabled + active/inactive",
    f"  {MINT}/mcp-add{RESET} <name> <command...>  register an MCP server",
    f"  {MINT}/mcp-del{RESET} <name>   remove an MCP server",
    f"  {MINT}/mcp-on{RESET} <name>    enable a server (auto-starts on use)",
    f"  {MINT}/mcp-off{RESET} <name>   disable a server (stays configured, never spawns)",
    f"  {MINT}/mcp-key{RESET} <name> <ENV_VAR>  vault the key a server needs",
    f"  {MINT}/mcp-test{RESET} [name]  live handshake probe → ACTIVE/INACTIVE",
    f"  {MINT}/md{RESET} <name>        create a new instruction (.md) file",
    f"  {MINT}/git{RESET}              git status",
    f"  {MINT}/config{RESET}           show config",
    f"  {MINT}/doctor{RESET}           environment health check",
    f"  {MINT}/update{RESET}           self-update from GitHub",
    f"  {MINT}/reinstall{RESET}        repair/reinstall claume in place (keeps config+vault)",
    f"  {MINT}/recommend{RESET}        model recommendations for your machine",
    f"  {MINT}/exit{RESET}             quit",
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


def cmd_effort(args: List[str], agent: Optional["Agent"] = None) -> None:
    cfg = config.Config()
    if not args or args[0] not in ("fast", "balanced", "deep", "ultra"):
        print(f"{GREY}effort = {MINT}{cfg.effort}{RESET} {GREY}(choose: fast | balanced | deep | ultra){RESET}")
        print(f"{GREY}  budgets — fast: 12 steps · balanced: 24 · deep: 48 · ultra: 90 (+auto-continues){RESET}")
        return
    cfg.set("effort", args[0])
    if agent is not None and hasattr(agent, "on_effort_changed"):
        agent.on_effort_changed()
    budgets = {"fast": (12, 16), "balanced": (24, 40), "deep": (48, 80), "ultra": (90, 160)}
    steps, tools = budgets[args[0]]
    print(f"{GREEN}✔ effort = {args[0]}{RESET} {GREY}(≤{steps} steps, ≤{tools} tool calls per turn, auto-continues){RESET}")


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
# Voice
# ---------------------------------------------------------------------------
def cmd_voice(args: List[str], ui: Any) -> None:
    from . import voice

    cfg = config.Config()
    if not args:
        state = "on" if voice.enabled() else "off"
        print(f"{GREY}voice = {MINT}{state}{RESET} {GREY}· accent = {voice.accent()}{RESET}")
        print(f"{GREY}  /voice on|off · /voice-accent male-british|female-british|male|female · /voice voices{RESET}")
        return
    sub = args[0].lower()
    if sub in ("on", "off"):
        cfg.set("voice_enabled", sub == "on")
        if sub == "on":
            ok = voice.speak("Hello, I am claume. Voice is online.", block=False)
            print(f"{GREEN}✔ voice on{RESET} " + (f"{GREY}(speaking test ok){RESET}" if ok else f"{GOLD}⚠ no TTS engine found — install pyttsx3 or check Windows voices{RESET}"))
        else:
            print(f"{GREEN}✔ voice off{RESET}")
    elif sub == "voices":
        names = voice.list_voices()
        if not names:
            print(f"{RED}✗ no TTS voices found{RESET}")
            return
        print(f"{GREEN}installed voices{RESET}")
        for n in names:
            british = " ★ british" if any(f in n.lower() for f in ("george", "hazel", "sonia", "en-gb", "libby", "ryan")) else ""
            print(f"  {MINT}•{RESET} {n}{GREY}{british}{RESET}")
        print(f"{GREY}  British voices: Windows Settings → Time & Language → Speech → Add voices (George/Hazel){RESET}")
    else:
        print(f"{RED}usage: /voice on|off|voices{RESET}")


def cmd_voice_accent(args: List[str]) -> None:
    from . import voice

    if not args or args[0] not in ("male-british", "female-british", "male", "female"):
        print(f"{GREY}accent = {MINT}{voice.accent()}{RESET}")
        print(f"{GREY}  choose: male-british | female-british | male | female{RESET}")
        return
    config.Config().set("voice_accent", args[0])
    print(f"{GREEN}✔ accent = {args[0]}{RESET}")
    voice.speak("This is my new voice.", block=False)


def cmd_say(args: List[str]) -> None:
    from . import voice

    text = " ".join(args)
    if not text:
        print(f"{RED}usage: /say <text>{RESET}")
        return
    ok = voice.speak(text, block=True)
    if not ok:
        print(f"{RED}✗ voice is off or unavailable — /voice on first{RESET}")


def cmd_hear(agent: "Agent") -> None:
    """One-shot voice command: listen → run as if typed."""
    from . import voice

    text = voice.hear_command()
    if not text:
        return
    if text.startswith("/"):
        handle_command(text, agent)
    else:
        _run_prompt(text, agent)


def _run_prompt(text: str, agent: "Agent") -> None:
    """Shared prompt pipeline (typed or heard)."""
    from . import ui as uimod
    from .ui import BOLD, RESET

    agent.compact_if_needed()
    final = agent.run_turn(text)

    if final and final != "(no final answer produced)" and final != "(interrupted by user)":
        print(f"\n{uimod.ACCENT}❯{RESET} {BOLD}{final}{RESET}\n")
        agent.ui.last_final = final
        if config.Config().get("auto_copy", True):
            try:
                uimod.copy_to_clipboard(final)
                print(f"{uimod.MUTED}  ⧉ copied to clipboard — /copy to re-copy · /expand for full tool output{RESET}")
            except Exception:
                pass
        from . import voice

        voice.speak(final, block=False)
    else:
        print()


# ---------------------------------------------------------------------------
# Copy mode
# ---------------------------------------------------------------------------
def cmd_copymode(ui: Any) -> None:
    """Click mode: real mouse clicks on '+N more lines' hints expand that
    tool's full output inline; drag-select pulls text into the clipboard."""
    from .ui import copy_mode

    copy_mode(ui)


# ---------------------------------------------------------------------------
# Live-input helpers: side questions + task queue visibility
# ---------------------------------------------------------------------------
def cmd_ask(args: List[str], agent: "Agent") -> None:
    """Answer a side question WITHOUT touching the task conversation.

    Uses a separate mini-LLM call so the running task's history, step
    budget and observations are untouched — a true parallel ask, like
    Freebuff's side-chat while an agent works.
    """
    from . import llm
    from .ui import BLUE, ITALIC, MUTED

    q = " ".join(args)
    if not q:
        print(f"{RED}usage: /ask <question>{RESET}")
        return

    print(f"{BLUE}❓ {q}{RESET}")
    messages = [
        {
            "role": "system",
            "content": (
                "You are claume. Answer the user's side question in at most "
                "6 short lines. You are mid-task on something else — do NOT "
                "attempt any actions, just answer. Plain text, no JSON envelope."
            ),
        },
        {"role": "user", "content": q},
    ]
    try:
        answer = llm.stream_chat(messages, effort="fast", on_token=None)
        for ln in answer.strip().splitlines()[:10]:
            print(f"{MUTED}│{RESET} {ITALIC}{ln[:140]}{RESET}")
        print(f"{GREY}  (side answer — the running task was not affected){RESET}")
    except llm.LLMError as exc:
        print(f"{RED}✗ side question failed: {exc}{RESET}")


def cmd_queue(args: List[str], agent: "Agent") -> None:
    print(f"{GREY}queue lives in the REPL — type a task any time, even while another runs.{RESET}")
    print(f"{GREY}  plain text while busy → queued · /ask <q> → side question · /skip → stop current{RESET}")


# ---------------------------------------------------------------------------
# Skills
# ---------------------------------------------------------------------------
def cmd_skills() -> None:
    from . import skills as skillsmod

    items = skillsmod.list_skills()
    if not items:
        print(f"{GREY}no skills installed — try: {MINT}/skill nextlevelbuilder/ui-ux-pro-max-skill{RESET}")
        return
    active_count = sum(1 for s in items if s["active"])
    print(f"{GREEN}skills{RESET} {GREY}({active_count} active / {len(items)} installed){RESET}")
    for s in items:
        status = f"{GREEN}● active{RESET}" if s["active"] else f"{GREY}○ inactive{RESET}"
        print(f"  {status} {MINT}{s['name']}{RESET} {GREY}· {s['docs']} docs · {s['scripts']} scripts{RESET}")
        if s["desc"]:
            print(f"      {GREY}{s['desc']}{RESET}")
    print(f"{GREY}  /skill-on <name> · /skill-off <name> · /skill-all on · /skill-run <skill> <script>{RESET}")


def cmd_skill(args: List[str]) -> None:
    from . import skills as skillsmod

    if not args or "/" not in args[0]:
        print(f"{RED}usage: /skill owner/repo  (e.g. /skill nextlevelbuilder/ui-ux-pro-max-skill){RESET}")
        return
    print(f"{GREY}cloning {args[0]}…{RESET}")
    ok, msg = skillsmod.install_from_github(args[0])
    print(f"{GREEN}✔ {msg}{RESET}" if ok else f"{RED}✗ {msg}{RESET}")
    if ok:
        name = args[0].rstrip("/").split("/")[-1]
        print(f"{GREY}  activate it: {MINT}/skill-on {name}{RESET} {GREY}· preview: {MINT}/skill-use {name}{RESET}")


# ---------------------------------------------------------------------------
# Plugins (machinery — see skills/PLUGINS.md; distinct from skills)
# ---------------------------------------------------------------------------
def cmd_plugins() -> None:
    from . import skills as skillsmod

    items = skillsmod.list_plugins()
    print(f"{GREEN}plugins{RESET} {GREY}({sum(1 for p in items if p['active'])} active / {len(items)} installed){RESET}"
          f" {GREY}— integrations & commands, not instructions (see /skills){RESET}")
    for p in items:
        status = f"{GREEN}● active{RESET}" if p["active"] else f"{GREY}○ inactive{RESET}"
        print(f"  {status} {MINT}{p['name']}{RESET} {GREY}· {p['command']}{RESET}")
        if p["description"]:
            print(f"      {GREY}{p['description']}{RESET}")
    print(f"{GREY}  /plugin-on <name> · /plugin-off <name> · docs: skills/PLUGINS.md{RESET}")


def cmd_plugin_on_off(args: List[str], active: bool) -> None:
    from . import skills as skillsmod

    if not args:
        print(f"{RED}usage: /plugin-{'on' if active else 'off'} <name>{RESET}")
        return
    ok = skillsmod.set_plugin_active(args[0], active)
    if ok:
        print(f"{GREEN}✔ plugin '{args[0]}' {'activated' if active else 'deactivated'}{RESET}")
        if args[0] == "graphify" and active:
            print(f"{GREY}  run it: {MINT}/graphify <path>{RESET} {GREY}(installs graphifyy on first use){RESET}")
        if args[0] == "jarvis" and active:
            print(f"{GREY}  launch: {MINT}/jarvis{RESET} {GREY}(desktop window) · {MINT}/jarvis cli{RESET} (in-terminal){RESET}")
    else:
        print(f"{RED}✗ unknown plugin '{args[0]}' — /plugins lists them{RESET}")


# ---------------------------------------------------------------------------
# Jarvis — desktop voice assistant plugin
# ---------------------------------------------------------------------------
def cmd_jarvis(args: List[str]) -> None:
    from . import skills as skillsmod

    skillsmod.set_plugin_active("jarvis", True)  # launching = activating
    if args and args[0] == "cli":
        from .jarvis import Jarvis

        j = Jarvis()
        caps = __import__("claume.jarvis", fromlist=["capability_report"]).capability_report()
        print(f"{GREEN}● jarvis{RESET} {GREY}— wake: {caps['wake_word']} · stt: {caps['stt']}{RESET}")
        print(f"{GREY}  say '{j.keyword}' then speak · 'exit' quits · answers use your claume provider/key{RESET}")
        j.run_forever()
        return
    if args and args[0] == "icon":
        # regenerate the desktop app icon
        import subprocess as sp

        script = Path(__file__).resolve().parent / "assets" / "make_jarvis_icon.py"
        r = sp.run([sys.executable, str(script)], capture_output=True, text=True)
        print(f"{GREEN}✔ {r.stdout.strip() or 'icon regenerated'}{RESET}")
        return
    try:
        from .jarvis_app import JarvisApp
    except Exception as exc:
        print(f"{RED}✗ jarvis window unavailable: {exc}{RESET} {GREY}— try /jarvis cli{RESET}")
        return
    print(f"{GREEN}● jarvis{RESET} {GREY}launching the desktop assistant (wake word '{config.Config().get('jarvis_wake_word', 'jarvis')}')…{RESET}")
    try:
        app = JarvisApp()
    except Exception as exc:
        print(f"{RED}✗ could not open the window: {exc}{RESET} {GREY}— try /jarvis cli{RESET}")
        return
    # Run the tkinter mainloop off-thread so the claume REPL stays live;
    # the window closes with ✕ or Esc.
    threading.Thread(target=app.run, daemon=True).start()
    print(f"{GREY}  the REPL stays live — keep typing; ✕/Esc closes the assistant{RESET}")


# ---------------------------------------------------------------------------
# Screen vision — /look · /bridge (offline phone bridge with QR)
# ---------------------------------------------------------------------------
def cmd_look(args: List[str]) -> None:
    from . import screen as screenmod

    question = " ".join(args)
    print(f"{GREY}capturing your screen…{RESET}")
    shot = screenmod.capture()
    if not shot.get("path"):
        print(f"{RED}✗ screen capture failed on this machine{RESET}")
        return
    print(f"{GREEN}✔ screenshot {shot['path']} {GREY}({shot.get('engine')}, {shot.get('bytes', 0) // 1024} KB){RESET}")
    print(f"{GREY}analyzing with vision ({config.Config().model})…{RESET}")
    analysis, err = screenmod.look_and_analyze(question)
    if err:
        print(f"{RED}✗ {analysis}{RESET}")
    else:
        print(f"{ACCENT}◆ claume sees:{RESET}\n{analysis}\n")


def cmd_bridge(args: List[str]) -> None:
    from . import screen as screenmod

    port = int(args[0]) if args and args[0].isdigit() else 8765
    out = screenmod.phone_bridge(port=port)
    print(f"{GREEN}● phone bridge{RESET} {GREY}live at{RESET} {MINT}{out['url']}{RESET}")
    print(f"{GREY}  works over LAN or Bluetooth PAN — phone needs NO internet{RESET}")
    if out.get("qr_path"):
        print(f"{ACCENT}  QR: {out['qr_path']}{RESET} {GREY}— open it, scan with your phone camera{RESET}")
        try:
            import os as _os

            _os.startfile(out["qr_path"])  # pop the QR image on screen
        except Exception:
            pass
    if out.get("screenshot"):
        print(f"{GREY}  live screen: {out['screenshot']}{RESET}")
    print(f"{GREY}  phone controls: refresh screen · diagnose (vision fix suggestions){RESET}")


# ---------------------------------------------------------------------------
# Graphify plugin — knowledge-graph pipeline
# ---------------------------------------------------------------------------
def cmd_graphify(args: List[str], agent: "Agent") -> None:
    from . import skills as skillsmod

    skillsmod.set_plugin_active("graphify", True)
    path = args[0] if args else "."
    flags = args[1:] if args else []
    if not Path(path).exists():
        print(f"{RED}✗ path not found: {path}{RESET}")
        return
    print(f"{GREEN}● graphify{RESET} {GREY}— building the knowledge graph for {path}{RESET}")
    print(f"{GREY}  first run installs the graphifyy package automatically{RESET}")
    skill = "graphify"
    doc = f"Execute the graphify SKILL.md pipeline (skills/graphify/SKILL.md) on '{path}'"
    if flags:
        doc += f" with flags: {' '.join(flags)}"
    agent.history.append({"role": "user", "content": doc})
    print(f"{GREY}  queued — claume will follow the /graphify steps (detect → extract → cluster → HTML + JSON + report){RESET}")


# ---------------------------------------------------------------------------
# Memory — Fable-style persistent recall (/memory)
# ---------------------------------------------------------------------------
def cmd_memory(args: List[str]) -> None:
    from . import memory as mem

    if not args or args[0] == "list":
        mems = mem.list_memories()
        if not mems:
            print(f"{GREY}memory is empty — claume saves durable facts automatically; "
                  f"add one with {MINT}/memory save <name> <text>{RESET}")
            return
        print(f"{GREEN}memory{RESET} {GREY}({len(mems)} — index loaded into every task){RESET}")
        for m in mems:
            print(f"  {MINT}{m['name']}{RESET} {GREY}· {m['type']}{RESET} — {m['description']}")
        return
    if args[0] == "save" and len(args) >= 3:
        print(f"{GREEN}✔ {mem.save_memory(args[1], ' '.join(args[2:]))}{RESET}")
        return
    if args[0] == "read" and len(args) >= 2:
        print(mem.read_memory(args[1]))
        return
    if args[0] == "forget" and len(args) >= 2:
        print(f"{GREEN}✔ {mem.forget_memory(args[1])}{RESET}")
        return
    print(f"{GREY}usage: /memory [list] · /memory save <name> <fact> · /memory read <name> · /memory forget <name>{RESET}")


def cmd_skill_rm(args: List[str]) -> None:
    from . import skills as skillsmod

    if not args:
        print(f"{RED}usage: /skill-rm <name>{RESET}")
        return
    ok = skillsmod.remove_skill(args[0])
    if ok:
        # also drop from active map
        cfg = config.Config()
        m = cfg.get("skills_active", {}) or {}
        m.pop(args[0], None)
        cfg.set("skills_active", m)
        print(f"{GREEN}✔ removed {args[0]}{RESET}")
    else:
        print(f"{RED}✗ '{args[0]}' not installed{RESET}")


def cmd_skill_on_off(args: List[str], active: bool) -> None:
    from . import skills as skillsmod

    if not args:
        print(f"{RED}usage: /skill-{'on' if active else 'off'} <name>{RESET}")
        return
    ok = skillsmod.set_active(args[0], active)
    if ok:
        print(f"{GREEN}✔ {args[0]} {'active — its instructions now guide every task' if active else 'inactive'}{RESET}")
    else:
        print(f"{RED}✗ '{args[0]}' not installed — /skills to list{RESET}")


def cmd_skill_all(args: List[str]) -> None:
    from . import skills as skillsmod

    active = (args[0].lower() in ("on", "1", "true")) if args else True
    n = skillsmod.set_all_active(active)
    print(f"{GREEN}✔ {n} skill(s) {'activated' if active else 'deactivated'}{RESET}")


def cmd_skill_use(args: List[str], agent: "Agent") -> None:
    """Adopt one skill's instructions for the NEXT user turn only."""
    from . import skills as skillsmod

    if not args:
        print(f"{RED}usage: /skill-use <name>{RESET}")
        return
    text = skillsmod.skill_instructions(args[0])
    if not text:
        print(f"{RED}✗ no instructions found for '{args[0]}' — /skills to list{RESET}")
        return
    agent.history.append(
        {
            "role": "user",
            "content": (
                f"SKILL INSTRUCTIONS — '{args[0]}' (apply to the next task, "
                f"then normal behavior):\n\n{text}\n\n(acknowledge silently and wait for the task)"
            ),
        }
    )
    print(f"{GREEN}✔ skill '{args[0]}' loaded into the next turn{RESET}")


def cmd_skill_run(args: List[str]) -> None:
    from . import skills as skillsmod

    if len(args) < 2:
        print(f"{RED}usage: /skill-run <skill> <script> [args…]{RESET}")
        return
    out, is_err = skillsmod.run_script(args[0], args[1], args[2:])
    for line in out.splitlines()[:30]:
        print(f"  {GREY}│{RESET} {SILVER}{line[:140]}{RESET}" if not is_err else f"  {RED}│{RESET} {line[:140]}{RESET}")


# ---------------------------------------------------------------------------
# MCP
# ---------------------------------------------------------------------------
def cmd_mcp() -> None:
    from . import mcp as mcpmod

    servers = mcpmod.full_server_map()
    if not servers:
        print(f"{GREY}no MCP servers configured{RESET}")
        print(f"{GREY}  quick start: {MINT}/mcp-preset design{GREY} (21st.dev + reactbits + motion + shadcnspace){RESET}")
        print(f"{GREY}  or: /mcp-add name command args…{RESET}")
        return
    print(f"{GREEN}MCP servers{RESET} {GREY}({len(servers)}){RESET}")
    for name, spec in sorted(servers.items()):
        if not isinstance(spec, dict):
            print(f"  {MINT}•{RESET} {name}: {GREY}{spec}{RESET}")
            continue
        enabled = spec.get("enabled", True)
        needs = spec.get("needs_key", "")
        keyline = f" · needs key {needs}" if needs else ""
        if not enabled:
            print(f"  {GREY}○ {name}{RESET} {GREY}disabled · {spec.get('command', '')}{keyline}{RESET}")
        else:
            desc = spec.get("description", "")
            print(f"  {MINT}•{RESET} {name} {GREEN}enabled{RESET} {GREY}· {spec.get('command', '')}{keyline}{RESET}")
            if desc:
                print(f"      {GREY}{desc[:90]}{RESET}")
    # Live tool probe (may spawn servers — keep it best effort)
    try:
        tools = mcpmod.list_all_tools()
        active = {k: v for k, v in tools.items() if v and not v[0].startswith(("<error", "<disabled"))}
        disabled = {k: v for k, v in tools.items() if v and v[0] == "<disabled>"}
        errored = {k: v for k, v in tools.items() if v and v[0].startswith("<error")}
        if active:
            print(f"{GREEN}active servers{RESET}")
            for name, tnames in active.items():
                shown = ", ".join(tnames[:8])
                extra = f" … +{len(tnames) - 8}" if len(tnames) > 8 else ""
                print(f"  {GREEN}●{RESET} {MINT}{name}{RESET} {GREY}({len(tnames)} tools){RESET}: {shown}{extra}")
        for name, tnames in errored.items():
            print(f"  {RED}✗ {name}{RESET} {GREY}{tnames[0][:100]}{RESET}")
        for name in disabled:
            print(f"  {GREY}○ {name} disabled{RESET}")
    except Exception as exc:
        print(f"{GREY}  (tool probe unavailable: {exc}){RESET}")


def cmd_mcp_add(args: List[str]) -> None:
    if len(args) < 2:
        print(f"{RED}usage: /mcp-add <name> <command> [args...]{RESET}")
        return
    name, command = args[0], " ".join(args[1:])
    cfg = config.Config()
    servers = cfg.get("mcp_servers", {})
    from .mcp import _npm_cache_dir

    print(f"{GREY}  npm downloads for MCP servers install under {MINT}{_npm_cache_dir()}{RESET}")
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


def cmd_mcp_on_off(args: List[str], enabled: bool) -> None:
    from . import mcp as mcpmod

    if not args:
        print(f"{RED}usage: /mcp-{'on' if enabled else 'off'} <name>{RESET}")
        return
    ok = mcpmod.set_enabled(args[0], enabled)
    if ok:
        if enabled:
            print(f"{GREEN}✔ {args[0]} enabled — tools bridge on first use{RESET}")
        else:
            print(f"{GREEN}✔ {args[0]} disabled — configured but never spawned{RESET}")
    else:
        print(f"{RED}✗ '{args[0]}' not configured — /mcp to list{RESET}")


def cmd_mcp_key(args: List[str]) -> None:
    """/mcp-key <server> — vault the key the server needs (or set needs_key)."""
    if not args:
        print(f"{RED}usage: /mcp-key <server> [ENV_VAR_NAME]{RESET}")
        return
    server = args[0]
    cfg = config.Config()
    servers = cfg.get("mcp_servers", {})
    if server not in servers:
        print(f"{RED}✗ '{server}' not configured — /mcp to list{RESET}")
        return
    spec = servers[server]
    env_name = args[1].upper() if len(args) > 1 else (spec.get("needs_key") if isinstance(spec, dict) else None)
    if not env_name:
        # Common defaults for known servers
        guessed = {
            "uidiscovery-21st": "TWENTY_FIRST_API_KEY",
            "21st": "TWENTY_FIRST_API_KEY",
        }.get(server, f"{server.upper().replace('-', '_')}_API_KEY")
        print(f"{GREY}which env var does {server} need? [default: {guessed}]{RESET}")
        try:
            raw = input(f"{GREY}env var name:{RESET} ").strip().upper()
        except (EOFError, KeyboardInterrupt):
            return
        env_name = raw or guessed
    if isinstance(spec, dict):
        spec["needs_key"] = env_name
        servers[server] = spec
        cfg.set("mcp_servers", servers)
    # Now vault the value (hidden input)
    print(f"{GREY}paste the value for {MINT}{env_name}{GREY} (input hidden):{RESET}")
    import getpass

    value = getpass.getpass("  > ")
    if value.strip():
        keyvault.set_key(env_name, value)
        cfg.set(f"key_vault.{env_name}", True)
        print(f"{GREEN}✔ {env_name} vaulted and wired to '{server}' — it is injected at spawn, never stored in config{RESET}")
    else:
        print(f"{GOLD}⚠ needs_key set to {env_name} — vault the value later with /key {env_name}{RESET}")


def cmd_mcp_test(args: List[str]) -> None:
    """Live handshake probe: ACTIVE / INACTIVE per server (or one)."""
    from . import mcp as mcpmod

    servers = mcpmod.full_server_map()
    if args:
        servers = {k: v for k, v in servers.items() if k == args[0]}
        if not servers:
            print(f"{RED}✗ '{args[0]}' not configured{RESET}")
            return
    if not servers:
        print(f"{GREY}no MCP servers configured{RESET}")
        return
    print(f"{GREY}probing (handshake + tools/list)…{RESET}")
    tools = mcpmod.list_all_tools()
    active_count = 0
    for name in sorted(servers):
        tlist = tools.get(name, [])
        if tlist and tlist[0] == "<disabled>":
            print(f"  {GREY}○ {name:<28} DISABLED{RESET}")
        elif tlist and not str(tlist[0]).startswith("<error"):
            active_count += 1
            print(f"  {GREEN}● {name:<28} ACTIVE{RESET} {GREY}{len(tlist)} tools{RESET}")
        else:
            reason = tlist[0][:80] if tlist else "no response"
            print(f"  {RED}✗ {name:<28} INACTIVE{RESET} {GREY}{reason}{RESET}")
    print(f"{GREY}{active_count}/{len(servers)} active · /mcp-on <name> to enable · /mcp-key <name> to add a key{RESET}")
    try:
        mcpmod.shutdown_all()
    except Exception:
        pass


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

    # Live MCP probe: handshakes + tools/list with vaulted keys injected.
    servers_cfg = config.Config().get("mcp_servers", {})
    servers = servers_cfg if isinstance(servers_cfg, dict) else {}
    if servers:
        try:
            from . import mcp as mcpmod

            tools = mcpmod.list_all_tools()
            mcpmod.shutdown_all()
            for name in sorted(servers):
                tlist = tools.get(name, [])
                spec = servers[name] if isinstance(servers[name], dict) else {}
                if tlist and tlist[0] == "<disabled>":
                    row(f"mcp:{name}", False, "disabled (/mcp-on)")
                else:
                    ok = bool(tlist) and not str(tlist[0]).startswith("<error")
                    note = f"{len(tlist)} tools" if ok else str(tlist[0] if tlist else "no tools")[:120]
                    row(f"mcp:{name}", ok, note)
        except Exception as exc:
            row("mcp probe", False, str(exc)[:120])
    else:
        print(f"│ {GREY}no MCP servers configured — /mcp-preset design{RESET}")

    print(f"{GREY}tip: run /proxy if the proxy row shows ✗{RESET}")


def cmd_reinstall() -> None:
    """In-place repair: re-run the installer logic without losing config."""
    print(f"{GREEN}reinstalling claume (config, vault and skills are kept){RESET}")
    app_dir = Path(__file__).resolve().parent.parent
    is_git_checkout = (app_dir / ".git").exists()

    # 1) Try git pull for git checkouts
    if is_git_checkout:
        try:
            rc = subprocess.call(["git", "pull", "--ff-only"], cwd=app_dir)
            if rc == 0:
                print(f"{GREEN}✔ source updated via git pull{RESET}")
        except Exception as exc:
            print(f"{GOLD}⚠ git pull failed: {exc}{RESET}")

    # 2) Re-install the package into the active environment (pip fallback)
    print(f"{GREY}re-installing package…{RESET}")
    py = sys.executable
    try:
        rc = subprocess.call([py, "-m", "pip", "install", "-e", str(app_dir), "--quiet"])
        if rc != 0:
            rc = subprocess.call([py, "-m", "pip", "install", str(app_dir), "--quiet", "--force-reinstall", "--no-deps"])
    except Exception as exc:
        rc = 1
        print(f"{GOLD}⚠ pip reinstall failed: {exc}{RESET}")
    if rc == 0:
        print(f"{GREEN}✔ package re-installed{RESET}")

    # 3) Verify the console script works
    try:
        out = subprocess.run(
            [py, "-c", "import claume; print(claume.__version__)"],
            capture_output=True, text=True, timeout=30,
        )
        ver = (out.stdout or "").strip()
        if out.returncode == 0 and ver:
            print(f"{GREEN}✔ claume imports cleanly (v{ver}){RESET}")
        else:
            err = (out.stderr or "unknown error").strip()[:200]
            print(f"{RED}✗ import check failed: {err}{RESET}")
    except Exception as exc:
        print(f"{RED}✗ verification failed: {exc}{RESET}")

    # 4) Sanity-check dirs and vault
    config.claume_dir().mkdir(parents=True, exist_ok=True)
    config.skills_dir().mkdir(parents=True, exist_ok=True)
    config.sessions_dir().mkdir(parents=True, exist_ok=True)
    print(f"{GREEN}✔ directories verified: {config.claume_dir()}{RESET}")
    print(f"{GREY}  restart claume to complete the repair · /doctor for a full health check{RESET}")


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
    ui.mascot.show(mood="happy", note="eyes follow your mouse 👀")


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
            label = s["name"] or s["title"]
            print(f"  {MINT}{s['id']}{RESET} {GREY}· {s['project']} · {s['when']} · {s['turns']} turns · {label}{RESET}")


def cmd_sessions(args: List[str], agent: "Agent") -> None:
    """Rich session list: project name + time, grouped by project."""
    from . import sessions

    entries = sessions.list_sessions(limit=20)
    if not entries:
        print(f"{GREY}no saved sessions yet{RESET}")
        return
    print(f"{GREEN}sessions{RESET} {GREY}(newest first · rename with /rename){RESET}")
    by_project: Dict[str, List[dict]] = {}
    for s in entries:
        by_project.setdefault(s["project"], []).append(s)
    for project in sorted(by_project):
        print(f"\n  {MINT}{project}{RESET}")
        for s in by_project[project]:
            cur = " ← current" if s["id"] == agent.session_id else ""
            label = s["name"] or s["title"]
            print(f"    {MINT}{s['id']}{RESET} {GREY}{s['when']} · {s['turns']} turns{RESET} {label}{GREY}{cur}{RESET}")
            if s.get("activity"):
                print(f"      {GREY}↳ did:{RESET} {SILVER}{s['activity']}{RESET}")


def cmd_rename(args: List[str], agent: "Agent") -> None:
    """Usage: /rename <project> [name]  |  /rename - <id> <project> [name]"""
    from . import sessions

    if not args:
        print(f"{RED}usage: /rename <project> [name]   — renames the CURRENT session{RESET}")
        print(f"{GREY}       /rename - <id> <project> [name] — renames a specific session{RESET}")
        return
    if args[0] == "-":
        if len(args) < 3:
            print(f"{RED}usage: /rename - <id> <project> [name]{RESET}")
            return
        sid, project = args[1], args[2]
        name = " ".join(args[3:]) or None
    else:
        if not agent.session_id:
            print(f"{RED}✗ no current session{RESET}")
            return
        sid, project = agent.session_id, args[0]
        name = " ".join(args[1:]) or None
    ok = sessions.rename_session(sid, project=project, name=name or "")
    if ok:
        print(f"{GREEN}✔ session {sid} → project '{project}'" + (f", name '{name}'" if name else "") + f"{RESET}")
    else:
        print(f"{RED}✗ session '{sid}' not found{RESET}")


def cmd_resume(args: List[str], agent: "Agent") -> None:
    from . import sessions

    entries = sessions.list_sessions(limit=12)
    if not entries:
        print(f"{GREY}no saved sessions yet{RESET}")
        return
    print(f"{GREEN}saved sessions{RESET} {GREY}(project · time){RESET}")
    for i, s in enumerate(entries, 1):
        label = s["name"] or s["title"]
        print(f"  {MINT}{i:>2}{RESET}. {s['id']}  {GREY}{s['project']} · {s['when']}{RESET} {label}")
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
    meta_project = data.get("project", "")
    title = " ".join(
        next((m["content"] for m in agent.history if m.get("role") == "user"), "")[:70].split()
    )
    print(f"{GREEN}✔ continued session {sid}{RESET} {GREY}· {meta_project} · {title}{RESET}")


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


# ---------------------------------------------------------------------------
# /image — attach an image file to the NEXT task (vision models)
# ---------------------------------------------------------------------------
def cmd_social(args: List[str], agent: "Agent") -> None:
    """/social — Telegram channel posting (free bot-first platform)."""
    from . import keyvault, reach

    if not args or args[0] in ("status", ""):
        print(f"{ACCENT}📣 social{RESET} {GREY}· {reach.status()}{RESET}")
        print(f"{GREY}  setup:  {MINT}/social setup telegram{RESET} {GREY}→ prompts for bot token + channel id{RESET}")
        print(f"{GREY}  post:   {MINT}/social post <text>{RESET} {GREY}· {MINT}/social post-image <path> <text>{RESET}{GREY} · {MINT}/social post-video <path> <text>{RESET}")
        print(f"{GREY}  free channel guide: t.me → New Channel → add your bot as admin{RESET}")
        return
    sub = args[0]
    if sub == "setup":
        platform = (args[1] if len(args) > 1 else "telegram").lower()
        if platform != "telegram":
            print(f"{GREY}only Telegram is free + bot-first today. Others (X, TikTok, YouTube) need their own developer accounts — configure via /key <NAME> once you have tokens.{RESET}")
            return
        print(f"{ACCENT}Telegram channel setup (free):{RESET}")
        print(f"  1. In Telegram: message {MINT}@BotFather{RESET} → /newbot → save the token")
        print(f"  2. Create a channel (e.g. {MINT}Claume AI{RESET}) → add your bot as ADMIN")
        print(f"  3. Get the channel id: forward a channel post to {MINT}@userinfobot{RESET} or use @RawDataBot")
        try:
            token = input(f"  {GOLD}paste bot token{RESET} ").strip()
            chat = input(f"  {GOLD}paste channel chat id{RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n{GREY}setup cancelled{RESET}")
            return
        if token and chat:
            keyvault.set_key("TELEGRAM_BOT_TOKEN", token)
            keyvault.set_key("TELEGRAM_CHAT_ID", chat)
            print(f"{GREEN}✔ telegram configured — try {MINT}/social post hello world{RESET}")
        else:
            print(f"{GREY}nothing saved{RESET}")
        return
    if sub == "post":
        text = " ".join(args[1:]).strip()
        if not text:
            print(f"{RED}usage: /social post <text>{RESET}")
            return
        msg, err = reach.telegram_post(text)
        (print if not err else lambda m: print(f"{RED}{m}{RESET}"))(msg)
        return
    if sub in ("post-image", "post-video"):
        if len(args) < 3:
            print(f"{RED}usage: /social {sub} <media-path> <caption>{RESET}")
            return
        media = args[1]
        caption = " ".join(args[2:])
        msg, err = (
            reach.telegram_post(caption, image_path=media)
            if sub == "post-image"
            else reach.telegram_post(caption, video_path=media)
        )
        (print if not err else lambda m: print(f"{RED}{m}{RESET}"))(msg)
        return
    print(f"{RED}unknown /social subcommand: {sub}{RESET}")


def cmd_email(args: List[str], agent: "Agent") -> None:
    """/email — SMTP/IMAP: send mail, check inbox for verification links."""
    from . import keyvault, reach

    if not args or args[0] == "status":
        configured = reach._smtp_config() is not None
        print(f"{ACCENT}✉ email{RESET} {GREY}· {'configured' if configured else 'not configured'}{RESET}")
        if not configured:
            print(f"{GREY}  setup:  {MINT}/email setup{RESET} {GREY}— Gmail: enable 2FA, create an app password{RESET}")
            print(f"{GREY}  ({MINT}https://myaccount.google.com/apppasswords{RESET}{GREY}) — free, no cost{RESET}")
        print(f"{GREY}  send:   {MINT}/email send <to> <subject> <body>{RESET}")
        print(f"{GREY}  inbox:  {MINT}/email inbox{RESET} {GREY}— list unread + extract verification links{RESET}")
        return
    sub = args[0]
    if sub == "setup":
        presets = {
            "gmail.com": ("smtp.gmail.com", "imap.gmail.com", "587"),
            "outlook.com": ("smtp-mail.outlook.com", "outlook.office365.com", "587"),
            "yahoo.com": ("smtp.mail.yahoo.com", "imap.mail.yahoo.com", "587"),
        }
        print(f"{ACCENT}email setup{RESET} {GREY}— works with any provider via app password{RESET}")
        try:
            addr = input(f"  {GOLD}email address{RESET} ").strip()
            pw = input(f"  {GOLD}app password (input hidden in transcripts){RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n{GREY}setup cancelled{RESET}")
            return
        domain = addr.split("@")[-1].lower() if "@" in addr else ""
        smtp_h, imap_h, port = presets.get(domain, ("", "", "587"))
        if not smtp_h:
            try:
                smtp_h = input(f"  {GOLD}SMTP host{RESET} ").strip()
                imap_h = input(f"  {GOLD}IMAP host{RESET} ").strip()
            except (EOFError, KeyboardInterrupt):
                return
        if addr and pw:
            keyvault.set_key("SMTP_USER", addr)
            keyvault.set_key("SMTP_PASS", pw)
            keyvault.set_key("SMTP_HOST", smtp_h)
            keyvault.set_key("SMTP_PORT", port)
            keyvault.set_key("IMAP_HOST", imap_h)
            keyvault.set_key("OWNER_EMAIL", addr)
            print(f"{GREEN}✔ email configured ({smtp_h}) — try {MINT}/email inbox{RESET}")
        else:
            print(f"{GREY}nothing saved{RESET}")
        return
    if sub == "send":
        if len(args) < 4:
            print(f"{RED}usage: /email send <to> <subject> <body...>{RESET}")
            return
        to, subject, body = args[1], args[2], " ".join(args[3:])
        msg, err = reach.send_email(to, subject, body)
        (print if not err else lambda m: print(f"{RED}{m}{RESET}"))(msg)
        return
    if sub == "inbox":
        msg, err = reach.check_inbox()
        (print if not err else lambda m: print(f"{RED}{m}{RESET}"))(msg)
        return
    print(f"{RED}unknown /email subcommand: {sub}{RESET}")


def cmd_payout(args: List[str], agent: "Agent") -> None:
    """/payout — ledger + MTN MoMo payout intents (confirmation-gated)."""
    from . import keyvault, reach

    if not args or args[0] in ("status", "ledger"):
        print(f"{ACCENT}💰 payout ledger{RESET}")
        print(f"  {reach.ledger_summary()}")
        momo = keyvault.resolve_key("MOMO_NUMBER") or "+237 678302909"
        print(f"{GREY}  target: MTN MoMo {MINT}{momo}{RESET}")
        print(f"{GREY}  record income:  {MINT}/payout income <amount> <source>{RESET}")
        print(f"{GREY}  request payout: {MINT}/payout request <amount>{RESET} {GREY}— always needs your OK{RESET}")
        return
    sub = args[0]
    if sub == "income":
        if len(args) < 3 or not args[1].replace(".", "").isdigit():
            print(f"{RED}usage: /payout income <amount> <source...>{RESET}")
            return
        reach.ledger_add({"type": "income", "amount": float(args[1]), "source": " ".join(args[2:])})
        print(f"{GREEN}✔ income recorded{RESET} — {reach.ledger_summary().splitlines()[0]}")
        return
    if sub == "request":
        if len(args) < 2 or not args[1].replace(".", "").isdigit():
            print(f"{RED}usage: /payout request <amount>{RESET}")
            return
        amount = float(args[1])
        try:
            ok = input(f"  {GOLD}confirm payout of {amount} XAF to MTN MoMo +237 678302909? [y/N]{RESET} ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            ok = ""
        if ok not in ("y", "yes"):
            print(f"{GREY}payout cancelled — nothing moved{RESET}")
            return
        msg, err = reach.momo_payout_instruction(amount)
        (print if not err else lambda m: print(f"{RED}{m}{RESET}"))(msg)
        return
    print(f"{RED}unknown /payout subcommand: {sub}{RESET}")


def cmd_ide(args: List[str]) -> None:
    """Show hosting-IDE integration status; /ide open <path> [line] jumps."""
    from . import ide as _ide

    info = _ide.detect()
    print(f"{ACCENT}⌘ ide{RESET} {BOLD}{info['name']}{RESET} {GREY}({info['kind']}){RESET}")
    if info.get("cli"):
        print(f"{GREY}  launcher:{RESET} {MINT}{info['cli']}{RESET}")
    print(f"{GREY}  file edits hot-reload in the editor (atomic writes){RESET}")
    if info.get("open_support"):
        print(f"{GREY}  jump-to-code:{RESET} {MINT}/ide open <path> [line]{RESET} {GREY}— opens at line in the IDE{RESET}")
        print(f"{GREY}  reveal:{RESET} {MINT}/ide reveal <path>{RESET} {GREY}— show in the explorer / file manager{RESET}")
    else:
        print(f"{GREY}  no IDE launcher on PATH — files open with the OS default{RESET}")
    if args and args[0] in ("open", "reveal"):
        if len(args) < 2:
            print(f"{RED}usage: /ide {args[0]} <path>[+line]{RESET}")
            return
        path = args[1]
        line = 0
        if len(args) > 2 and args[2].isdigit():
            line = int(args[2])
        if args[0] == "open":
            msg, err = _ide.open_file(path, line)
        else:
            msg, err = _ide.reveal(path)
        (print if not err else lambda m: print(f"{RED}{m}{RESET}"))(msg)


def cmd_image(args: List[str]) -> None:
    from . import chatbox as _cb

    if not args:
        if _cb.last_attachments:
            print(f"{ACCENT}pending attachment(s):{RESET}")
            for a in _cb.last_attachments:
                print(f"  {MINT}{a['name']}{RESET} {GREY}· {a['bytes']}{RESET}")
            print(f"{GREY}they ride along with your next submitted task{RESET}")
        else:
            print(f"{RED}usage: /image <path-to-png/jpg/webp>{RESET} {GREY}· attaches to your next task{RESET}")
        return
    path = " ".join(args).strip().strip('"').strip("'")
    att = _cb.attach_image(path)
    if att is None:
        print(f"{RED}✗ cannot read image: {path}{RESET} {GREY}(png/jpg/jpeg/gif/webp/bmp, ≤12 MB){RESET}")
        return
    _cb.last_attachments.append(att)
    print(f"{GREEN}✔ attached {att['name']}{RESET} {GREY}({att['bytes']}) — submits with your next task{RESET}")


def cmd_webdesign(args: List[str], agent: "Agent", enqueue=None) -> None:
    """Studio build: pipeline + brief injected, then the build auto-queues."""
    from . import mcp, webstudio

    request = " ".join(args)
    if not request:
        print(f"{RED}usage: /webdesign <what to build>  e.g. /webdesign photographer portfolio{RESET}")
        return
    agent.ui.render_info("claude studio: assembling design brief + Link System pipeline…")
    brief, _ = webstudio.studio_brief(request)
    report, _is_err = mcp.design_pipeline(request, agent.workspace)
    payload = (
        f"DESIGN TASK: '{request}'\n\n{brief}\n\n{report[:8000]}\n\n"
        "Build the website/UI now in the workspace. Pull the real fonts with "
        "webstudio_pull_font and real image assets with webstudio_pull_asset, "
        "reference them locally, follow the studio brief exactly, and verify the "
        "result (open/inspect the files). No placeholder divs, no lorem ipsum."
    )
    agent.history.append({"role": "user", "content": payload})
    print(f"{GREEN}✔ studio brief + pipeline output loaded{RESET} {GREY}({request[:60]}){RESET}")
    if enqueue is not None:
        enqueue("build it now — follow the injected design brief exactly")
    else:
        print(f"{GREY}  type {MINT}build it{RESET} {GREY}to start implementation{RESET}")


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
        print(f"{GREY}  need a key? {MINT}/mcp-key <server>{RESET} · check status: {MINT}/mcp-test{RESET}")
    else:
        print(f"{GREY}nothing to add{RESET}")


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------
def handle_command(line: str, agent: "Agent", enqueue=None) -> bool:
    """Handle a /command. Returns True if it was a claume command.

    enqueue (optional) lets commands like /webdesign auto-queue the build
    turn through the REPL's live task queue."""
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
        cmd_effort(args, agent)
    elif name == "plugins":
        cmd_plugins()
    elif name == "plugin-on":
        cmd_plugin_on_off(args, True)
    elif name == "plugin-off":
        cmd_plugin_on_off(args, False)
    elif name == "jarvis":
        cmd_jarvis(args)
    elif name == "graphify":
        cmd_graphify(args, agent)
    elif name == "memory":
        cmd_memory(args)
    elif name == "look":
        cmd_look(args)
    elif name == "bridge":
        cmd_bridge(args)
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
    elif name == "copymode":
        cmd_copymode(agent.ui)
    elif name == "ask":
        cmd_ask(args, agent)
    elif name == "queue":
        cmd_queue(args, agent)
    elif name == "mascot":
        cmd_mascot(agent.ui)
    elif name == "frame":
        from . import frame as _frame

        _frame.status_bar("worki · claume-code", out=print)
        print()
        _frame.skills_panel(out=print)
    elif name == "voice":
        cmd_voice(args, agent.ui)
    elif name == "voice-accent":
        cmd_voice_accent(args)
    elif name == "say":
        cmd_say(args)
    elif name == "hear":
        cmd_hear(agent)
    elif name == "projects":
        cmd_projects(args, agent)
    elif name == "project":
        cmd_project(args, agent)
    elif name == "repo":
        cmd_repo(args, agent)
    elif name == "session":
        cmd_session(args, agent)
    elif name == "sessions":
        cmd_sessions(args, agent)
    elif name == "rename":
        cmd_rename(args, agent)
    elif name == "resume":
        cmd_resume(args, agent)
    elif name == "continue":
        cmd_continue(args, agent)
    elif name == "agents":
        cmd_agents(args, agent)
    elif name == "image":
        cmd_image(args)
    elif name == "ide":
        cmd_ide(args)
    elif name == "social":
        cmd_social(args, agent)
    elif name == "email":
        cmd_email(args, agent)
    elif name == "payout":
        cmd_payout(args, agent)
    elif name == "design":
        cmd_design(args, agent)
    elif name == "webdesign":
        cmd_webdesign(args, agent, enqueue=enqueue)
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
    elif name == "skill-rm":
        cmd_skill_rm(args)
    elif name == "skill-on":
        cmd_skill_on_off(args, True)
    elif name == "skill-off":
        cmd_skill_on_off(args, False)
    elif name == "skill-all":
        cmd_skill_all(args)
    elif name == "skill-use":
        cmd_skill_use(args, agent)
    elif name == "skill-run":
        cmd_skill_run(args)
    elif name == "mcp":
        cmd_mcp()
    elif name == "mcp-add":
        cmd_mcp_add(args)
    elif name == "mcp-del":
        cmd_mcp_del(args)
    elif name == "mcp-on":
        cmd_mcp_on_off(args, True)
    elif name == "mcp-off":
        cmd_mcp_on_off(args, False)
    elif name == "mcp-key":
        cmd_mcp_key(args)
    elif name == "mcp-test":
        cmd_mcp_test(args)
    elif name == "md":
        cmd_md(args, agent.workspace)
    elif name == "config":
        cmd_config()
    elif name == "doctor":
        cmd_doctor()
    elif name == "reinstall":
        cmd_reinstall()
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
