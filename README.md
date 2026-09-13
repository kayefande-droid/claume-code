# claume-code

```
 ██████╗██╗      █████╗ ██╗   ██╗███╗   ███╗███████╗
██╔════╝██║     ██╔══██╗██║   ██║████╗ ████║██╔════╝
██║     ██║     ███████║██║   ██║██╔████╔██║█████╗
██║     ██║     ██╔══██║██║   ██║██║╚██╔╝██║██╔══╝
╚█████╗ ███████╗██║  ██║╚██████╔╝██║ ╚═╝ ██║███████╗
 ╚════╝ ╚══════╝╚═╝  ╚═╝ ╚═════╝ ╚═╝     ╚═╝╚══════╝
```

**claume-code v2.3** is a pixel-animated **desktop CLI coding agent** (not a web app)
that builds full projects from natural-language prompts — inspired by Claude Code and
Freebuff, powered **free** by NVIDIA NIM through the built-in **free-claume proxy**.
claume always identifies as **claume** — never Claude, never ChatGPT.

> 🎬 Pixel banner + **mouse-tracking bot mascot** · 🧠 extended-thinking ReAct loop with
> **animated ✻ thinking shimmer** · 🛠 21 built-in tools · 🌐 free-claume proxy
> (OpenAI-compatible) · 🖥 **claume studio** admin dashboard at `/admin` (explode-view,
> live key health, model chain, design system) · 🔐 local key vault
> · 🧩 MCP client with **auto-install into ~/.claume/mcp** + **Link System
> design pipeline** · 📚 **skills system** (ui-ux-pro-max ships pre-activated)
> · 🎨 **webstudio: pulls real Google Fonts + assets into your builds**
> · 🎙 **AI voice out + voice commands** (British male/female accents)
> · 💬 **Freebuff-style input box** · ⧉ **click-and-pull copy mode**
> · 🎭 **4 permission modes** (manual / accept / plan / auto, Shift+Tab)
> · 💾 **named persistent sessions with activity log** (see exactly what claume did)
> · 🤖 parallel subagents · 🎨 7 color themes · 🚀 **effort levels incl. ultra**
> · 🔁 self-update + **/reinstall** + **update checker in /admin**

Default model: **`nvidia/nemotron-3-super-120b-a12b`** (FCC-style), with an
ordered **fallback chain** — if a model is retired (410) or rate-limited, the
proxy transparently retries the next one and your turn survives.

---

## Why it's free

The agent talks to a **local proxy** (`free-claume`) that exposes a standard
OpenAI-compatible API at `http://127.0.0.1:8000/v1` and forwards traffic to
**NVIDIA NIM** (`integrate.api.nvidia.com`) using a **free API key** from
[build.nvidia.com](https://build.nvidia.com) — no credit card, ~1,000 free credits
on signup. Several keys can be added (`NVIDIA_API_KEY_2`, `_3`…) and the proxy
**rotates them automatically** on rate limits.

## Install (Windows PowerShell)

**Option A — from this folder (already downloaded):**

```powershell
cd claume-code
powershell -ExecutionPolicy Bypass -File install.ps1
```

**Option B — one-liner (always the LATEST version — pulls the current main branch):**

```powershell
irm https://raw.githubusercontent.com/kayefande-droid/claume-code/main/install.ps1 | iex
```

Both options install the newest code on the repo — the one-liner downloads
`main` fresh every run, and Option A copies the folder you have (run `git pull`
first if your local clone is stale). The installer copies the app to
`%USERPROFILE%\.claume`, creates an isolated venv, installs dependencies
(**stdlib-only — nothing heavy**), stages the bundled ui-ux-pro-max design skill,
and registers the `claume` command on your user PATH. Then open a **new**
PowerShell tab and run:

```powershell
claume
```

> Updating an existing install? Re-run the same command — it is idempotent and
> replaces the app files while **keeping your config, vault, sessions and skills**.
> `/admin` also shows whether a newer version is published (update checker).

First run asks for your free `nvapi-…` key (get it at build.nvidia.com → any model
→ *Get API Key*). It's stored obfuscated in `%USERPROFILE%\.claume\vault.bin`.

## Usage examples

```
claume

❯ build me a snake game in python with pygame, single file
❯ clone https://github.com/pallets/flask and explain its structure
❯ fix the failing test in tests/ and make pytest pass
❯ create a REST API with fastapi + sqlite with tests
❯ build me a luxurious portfolio site with real fonts and assets
❯ /mode plan       ← research first, present a plan, no writes
❯ /agents scan auth ; scan api ; scan db    ← parallel subagents, merged report
❯ /design fluid bento landing hero ← MCP design pipeline (Link System)
❯ /theme synthwave ← switch the whole terminal palette
❯ /continue        ← pick up yesterday's session (shows what it did last time)
❯ /proxy-ui        ← claume studio dashboard: key health, model chain, design system
❯ /effort ultra    ← maximum effort: 90 steps, 160 tool calls, 12 auto-continues
```

### Live-input REPL — type while it works (Freebuff-style)

The prompt never blocks. While a task runs you can keep typing:

```
❯ build the dashboard            ← starts working immediately
│ + queue the API refactor       ← plain text while busy → queued (runs next)
│ + /ask what does mcp mean?     ← side question, answered WITHOUT touching the task
│ + /skip                        ← interrupts the running task; queue stays live
```

* `│ +` is the live prompt shown while a task is running — anything goes in:
  plain text (queued), `/ask` (parallel side question), `/skip` (interrupt).
* ctrl+c while busy = skip the current task (press twice to quit).
* Tool output shows `… +N more lines — /expand` hints; `/expand on` opens them up.

### Permission modes (Shift+Tab cycles, like Claude Code)

| Mode | Behavior |
|---|---|
| `manual` ⏸ | ask before every write/command (safest) |
| `accept` ⏵⏵ | file edits run free; shell still asks |
| `plan` ◇ | read-only research → presents a plan for approval |
| `auto` ⏵⏵⏵ | hands-off; **destructive always asks** |

Switch anytime: Shift+Tab (in-terminal) or `/mode <name>`.

### Slash commands

| Command | What it does |
|---|---|
| `/help` | all commands |
| `/new` | fresh conversation |
| `/model <name>` | pick model (e.g. `openai/gpt-oss-120b`) |
| `/recommend` | recommended free models |
| `/effort fast\|balanced\|deep\|ultra` | thinking budget + step/tool budgets (ultra = 90 steps) |
| `/mode <name>` | manual · accept · plan · auto (Shift+Tab cycles) |
| `/auto on\|off` | legacy alias of `/mode auto\|manual` |
| `/theme [name]` | 7 terminal palettes: nvidia-green, claude-orange, cyber-blue, synthwave, matrix, sunset, mono |
| `/expand on\|off` | show full tool output (default trims to 14 lines) |
| `/copy [text]` | copy last answer (or text) to clipboard — answers auto-copy |
| `/copymode` | **click-and-pull copy**: drag-select text → clipboard (Enter to exit) |
| `/mascot` | the claume pixel bot — **its eyes follow your mouse** |
| `/voice on\|off\|voices` | **AI voice reads final answers aloud** |
| `/voice-accent <a>` | `male-british` · `female-british` · `male` · `female` |
| `/say <text>` | make claume speak text now |
| `/hear` | one **voice command** (needs `pip install SpeechRecognition pyaudio`) |
| `/session [id]` · `/sessions` | session list **grouped by project with timestamps + activity** |
| `/rename <project> [name]` | rename the current session (or `/rename - <id> …`) |
| `/resume` · `/continue` | persistent chat history (`claume --continue` on boot) |
| `/agents t1 ; t2 ; t3` | parallel subagents → merged report |
| `/design <prompt>` | run the MCP Link System design pipeline |
| `/webdesign <prompt>` | build a website/UI now — studio brief + real fonts/assets pulled in |
| `/mcp-preset design` | install the UI stack: 21st.dev + reactbits + motion + shadcnspace |
| `/mcp` | servers with **enabled/disabled + ACTIVE/INACTIVE** status and tool counts |
| `/mcp-on <name>` · `/mcp-off <name>` | enable/disable a server (disabled = never spawns) |
| `/mcp-key <server> [ENV]` | vault the key a server needs (injected at spawn, never in config) |
| `/mcp-test [name]` | live handshake probe → `● ACTIVE` / `✗ INACTIVE` / `○ DISABLED` |
| `/mcp-add` · `/mcp-del` | register/remove servers |
| *(npm servers)* | npx-style servers **auto-install into `~/.claume/mcp/npm`** and launch via `node` — no global downloads |
| `/skill <owner/repo>` | **install a skill from GitHub** (e.g. `nextlevelbuilder/ui-ux-pro-max-skill`) |
| `/skills` | installed skills with ● active / ○ inactive status |
| `/skill-on <name>` · `/skill-off <name>` | activate/deactivate — active skills' .md instructions guide every task |
| `/skill-all on\|off` | activate every skill at once (or none) |
| `/skill-use <name>` | adopt one skill for the next turn only |
| `/skill-run <skill> <script> [args]` | run a bundled skill script |
| `/skill-rm <name>` | remove an installed skill |
| `/proxy` | start/reuse the free-claume proxy |
| `/proxy-ui` | claume studio dashboard in your browser |
| `/keys` · `/key NAME` · `/key-del NAME` | manage the local key vault ("live space") |
| `/provider <name>` | nvidia · groq · openrouter · deepseek · openai · mistral · together · fireworks |
| `/doctor` | health check incl. **live MCP probe** (handshake + tools per server) |
| `/reinstall` | **repair claume in place** — re-pulls source, reinstalls the package, keeps config/vault/skills |
| `/md <name>` | create a new instructions `.md` (like CLAUDE.md) |
| `/git` · `/config` · `/update` | maintenance |
| `/exit` | quit |

### Effort levels (each sets step + tool-call + auto-continue budgets)

| Level | max_tokens | steps | tool calls | use for |
|---|---|---|---|---|
| `fast` | 1 024 | 12 | 16 | quick edits, renames |
| `balanced` | 4 096 | 24 | 40 | normal features |
| `deep` | 8 192 | 48 | 80 | architecture, gnarly bugs |
| `ultra` | 16 384 | 90 | 160 | whole-app builds, huge refactors |

### Voice I/O (British accents)

Voice **output** needs nothing extra on Windows — claume drives SAPI5 through
PowerShell. British voices (`Microsoft George`/`Microsoft Hazel`) are used when
installed; otherwise the best gender match speaks (David/Zira on US-locale
installs). Add British voices via *Windows Settings → Time & Language → Speech →
Add voices*. `pyttsx3` is used automatically when installed.

```
/voice on            ← answers are spoken after each turn
/voice-accent female-british
/voice voices        ← list installed voices (★ british markers)
/say hello world
```

Voice **input** (voice commands) is opt-in because it needs the mic stack:

```
pip install SpeechRecognition pyaudio
/hear                ← speak a command; it runs as if typed
```

### The terminal chat box (v2.3.1)

The idle prompt is a real line editor now — not plain `input()`:

* **`/` command drop** — type `/` and a fuzzy-filtered command panel drops
  down, live as you type; ↑/↓ moves the inverse-video bar, Tab/→ accepts,
  Enter submits.
* **`@` file drop** — type `@` to pull files into your prompt as context
  (`@claume/agent.py fix the loop guard`); the panel filters recursively
  from your workspace.
* **Ghost suggestions** — the likeliest continuation from your history
  renders dimmed after the cursor; → accepts it.
* **History** — ↑/↓ walks the last 200 prompts, persisted in
  `~/.claume/input_history`.
* **Multi-line** — Alt+Enter inserts a newline for long prompts.
* **Edit keys** — Home/End/Left/Right/Backspace/Delete, Ctrl+U clears the
  line, Shift+Tab still cycles permission modes.

While a task runs the box swaps to the live `│ +` prompt (plain input
there — the worker prints concurrently). Non-interactive/quiet sessions
fall back to plain `input()` automatically.

### The terminal experience

* **Input box** — every prompt sits inside a bordered box showing the current
  mode and session project (Freebuff-style), like:

  ```
  ╭──────────────── manual · my-app ────────────────╮
  │ ❯ build the login page
  ╰─────────────────────────────────────────────────╯
  ```

* **Animated thinking** — while the model works you get a shimmering
  `✻ thinking… 4s` line that collapses to a compact thought summary, then
  tool calls render as `✓ tool · target` with dimmed output bars.

* **Mouse-tracking mascot** — the pixel bot's eyes follow your real cursor
  anywhere on screen (`/mascot`, disable with `"mouse_mascot": false` in config).

* **Click-and-pull copy** — `/copymode` watches for drag-selections and lands
  them in the clipboard; final answers also auto-copy (`/copy` to re-copy).

* **Loop protection** — an identical failing action repeated 3× stops the turn
  with a warning instead of burning the step budget (fixes the auto-mode loop);
  ctrl+c mid-stream interrupts cleanly and preserves the conversation.

### Multi-provider "live space"

Any OpenAI-compatible provider works. Vault the key once, switch provider:

```
/key GROQ_API_KEY        ← paste gsk_...
/provider groq
/model llama-3.3-70b-versatile
```

## Skills — adopt instruction packs from GitHub

claume installs any GitHub repo as a **skill**: its markdown (SKILL.md etc.)
becomes instructions the agent *adopts*, and its bundled scripts become runnable.

```
/skill nextlevelbuilder/ui-ux-pro-max-skill   ← install (145 docs, 100+ scripts)
/skills                                        ← ● active / ○ inactive list
/skill-on ui-ux-pro-max-skill                  ← its guidance now applies to EVERY task
/skill-all on                                  ← activate everything
/skill-use ui-ux-pro-max-skill                 ← one-shot: next turn only
/skill-run ui-ux-pro-max-skill search.py "dashboard"   ← run a bundled script
/skill-off ui-ux-pro-max-skill · /skill-rm …   ← deactivate / remove
```

Active skills are injected into the system prompt automatically, so the model
follows the skill's workflow (e.g. ui-ux-pro-max's 4-step design process) without
you repeating it. Skills are clearly separated from MCP tools: a skill is
instructions + scripts; MCP servers provide callable tools named
`mcp_<server>_<tool>`.

## Built-in tools

`read_file` · `write_file` · `patch_file` (surgical edits) · `list_directory` ·
`tree_view` · `make_directory` · `delete_path` · `search_text` (grep) ·
`execute_command` (foreground + background for dev servers) · `background_output` ·
`background_stop` · `git_clone` · `git_commit` · `git_status` · `web_search` ·
`fetch_url` · `spawn_subagents` (parallel task agents) · plus every tool from
connected MCP servers (bridged automatically as `mcp_<server>_<tool>`).

**Safety:** every command is classified `safe / caution / destructive`
(`claume/security.py`). Caution → asked (except accept/auto mode). Destructive
(`rm -rf`, `git push --force`, `format`, `del /s`…) → **always asked**, even in
auto mode. Secrets are scrubbed from everything shown to the model.

## The Link System (design pipeline)

`/mcp-preset design` installs a UI-focused MCP stack, and `/design <prompt>`
orchestrates it in stages instead of treating servers as islands:

```
[ your prompt ] → 1. atomic-shadcnspace   layout blueprint (grid, tokens)
                → 2. uidiscovery-21st     human-designed component blocks
                → 3. animation-motion     Framer Motion timelines
                → 4. microinteractions-reactbits  fluid canvas background
                → claume builds it — no generic placeholder divs
```

Each stage feeds its output into the next; missing servers degrade gracefully
(claume builds that part by hand, same quality bar). The pipeline is verified
live by `python tests/mcp_smoke_live.py` — all 4 stages green with real tool
catalogs (10 + 34 + 9 + 5 tools).

## MCP server management

```
/mcp                    ← status board
/mcp-test               ← live probe: ● ACTIVE · ✗ INACTIVE · ○ DISABLED
/mcp-off microinteractions-reactbits      ← keep configured, never spawn
/mcp-on  microinteractions-reactbits      ← re-enable
/mcp-key uidiscovery-21st                 ← vault + wire the API key it needs
```

`/mcp` and `/mcp-test` show each server as **enabled/disabled** (your choice,
persisted in config) and **ACTIVE/INACTIVE** (live handshake + tools/list probe).
The agent's own context includes this board, so asking claume *"check if your
mcp servers are on"* makes it name the active servers and their tool counts.

## Config-driven key flow for MCP servers

MCP servers never get keys hardcoded. Keys live once in the obfuscated vault
(`%USERPROFILE%\.claume\vault.bin`), and a server spec *names* the env var it
needs — claume injects it into the server process automatically at spawn:

```jsonc
// ~/.claume/config.json (mcp_servers)
"uidiscovery-21st": {
  "command": "npx",
  "args": ["-y", "@21st-dev/magic"],
  "enabled": true,                       // ← /mcp-off flips this
  "needs_key": "TWENTY_FIRST_API_KEY"    // ← env var name, NOT the secret
}
```

The flow:

```
/key TWENTY_FIRST_API_KEY      ← paste the secret once (hidden input)
        │
        ▼
vault.bin (XOR+base85, machine-bound)      ← the ONLY place the secret exists
        │  claume/mcp.py resolves needs_key → os.environ of the spawned server
        ▼
21st.dev MCP server authenticates           ← secret never touches config.json,
                                              git, or the model's context
```

Details that matter:

* `/keys` shows masked values only (`21st_s…4268`); `/config` never dumps the vault.
* `security.redact_secrets()` scrubs every vaulted value out of tool output,
  observations, and stream text before the model ever sees it.
* Placeholder env values in a server spec (`"<paste-your-key>"`) are detected
  and skipped — a template config can ship in git safely.
* When a server fails its handshake with an auth error, claume raises
  `'<server>' requires an API key — run /key <NEEDS_KEY> …` so the fix is one
  command away.
* `/doctor` live-probes every configured server (handshake + tools/list with
  keys injected) and prints a ✔ row per server with its tool count.
* `python tests/mcp_smoke_live.py` verifies the whole chain: vault → spawn env
  → handshake → real tool call → 4/4 Link System stages (exit 1 on any failure).

Adding a new keyed MCP server is three steps:

```
/key MY_SERVICE_API_KEY
/mcp-add my-service npx -y some-mcp-server
```

then set `"needs_key": "MY_SERVICE_API_KEY"` on the server entry (or run
`/mcp-key my-service MY_SERVICE_API_KEY`). No secrets in dotfiles, no secrets
in the repo.

### Where MCP servers are installed

Every npm-based MCP server (`npx -y …` specs) is **auto-installed into the
claume folder itself** — `~/.claume/mcp/npm` — and launched directly with
`node`. Nothing is downloaded to global npm, and npx's flaky cold-start
hangs are gone: first use installs the package once (30–60 s), every later
start is instant. `animation-motion` ships the same way.

```
~/.claume/mcp/
├── npm/            ← auto-installed MCP packages + node_modules (v2.3+)
└── motion-dev-mcp/ ← bundled animation server
```

## Web design capability — claume studio

claume builds **human-designed, luxurious** websites and app UIs — its own
site included. Ask for a website and the studio machinery engages
automatically:

* **Real fonts, not suggestions** — `webstudio_pull_font` downloads the
  actual Google Fonts CSS + woff2 files into `assets/fonts/` and rewrites
  the CSS to reference them locally, so the site works offline with real
  typography (Fraunces · Space Grotesk · JetBrains Mono by default).
* **Real assets** — `webstudio_pull_asset` downloads images/logos/textures
  into `assets/` instead of shipping gray placeholder boxes.
* **The studio brief** — claume's own design language (editorial serif over
  geometric sans, NVIDIA-green on near-black, glass-depth cards, explode-view
  heroes, staggered entry motion) is injected into its system prompt for every
  design-shaped task. The same brief is one click in the `/admin` dashboard
  (Generate design brief → paste into claume).
* **The Link System** — `/design <prompt>` runs the 4-stage MCP pipeline
  (shadcnspace layout → 21st.dev components → motion.dev timelines →
  reactbits canvas) and feeds the blueprints straight into the build.

```
❯ build me a luxurious portfolio website with real fonts and assets
  ✓ atomic-shadcnspace::searchBlocks   hero layout blueprints
  ✓ uidiscovery-21st::search           human-designed component blocks
  ✓ animation-motion::search_motion_docs  motion timelines
  ✓ microinteractions-reactbits::get_component_demo  canvas background
  ✓ webstudio_pull_font Fraunces → assets/fonts/ (3 woff2, local CSS)
  ✓ webstudio_pull_asset …
```

## Sessions — named by project, with an activity log

Every session autosaves with its **project name** (defaults to the working
folder) and human timestamps — plus a log of **what claume actually did**
(files written, commands run, MCP tools called, web searches):

```
/sessions
  sessions (newest first · rename with /rename)

  my-app
    20260912-140301-a1b2c3 12 Sep · 14:03 · 24 turns fix the login bug ← current
      ↳ did: 6 file(s): auth.py, login.tsx +1 · 3 command(s) · 2 web call(s)
  experiments
    20260911-091500-d4e5f6 11 Sep · 09:15 · 3 turns try sqlite vs duckdb
      ↳ did: 1 file(s): bench.py
```

`/rename webapp "auth rewrite"` renames the current session;
`/rename - <id> <project> [name]` renames any other. `/resume` and the boot
picker show project · time so you never grab the wrong one.

## Subagents

Big job? Split it. `/agents map the api ; audit the tests ; review the docs`
spawns independent agents — each with its own context, step budget, and tool
access — running **in parallel on threads**, then an LLM merge pass combines
their reports into one summary. The agent itself can spawn them mid-task via
the `spawn_subagents` tool.

## Architecture

```
claume-code/
├── install.ps1 / uninstall.ps1     PowerShell installer (→ %USERPROFILE%\.claume)
├── run-claume.ps1                  run from source
├── pyproject.toml                  pip packaging (claume console script)
├── claume/
│   ├── cli.py          REPL: input box, animated thinking shimmer, voice, sessions
│   ├── agent.py        ReAct loop: think → act → observe → auto-continue
│   │                   + anti-loop guard + effort budgets + skills/MCP context
│   ├── parser.py       forgiving JSON envelope parser
│   ├── prompts.py      system prompts + identity (claume, never claude) + mode blocks
│   ├── llm.py          OpenAI-compatible client + provider map + model fallback chain
│   ├── sessions.py     named sessions: project + timestamps + /rename
│   ├── activity.py     per-session activity log (files/commands/MCP seen in /sessions)
│   ├── skills.py       GitHub skill installer + bundled-skill seeding
│   ├── webstudio.py    font/asset pulling + claume-studio design briefs
│   ├── subagents.py    parallel multi-task agents + merge pass
│   ├── mcp.py          MCP stdio JSON-RPC client + npm auto-install (~/.claume/mcp)
│   │                   + enable/disable + Link System
│   ├── voice.py        TTS/STT: British voices, zero required deps
│   ├── proxy.py        free-claume proxy (OpenAI → NVIDIA NIM, streaming,
│   │                   retries, multi-key rotation, first-run key prompt)
│   ├── proxy_ui.py     claume studio dashboard (explode-view, key health, design system)
│   ├── commands.py     /slash command handlers
│   ├── security.py     command classifier (safe/caution/destructive) + redaction
│   ├── keyvault.py     obfuscated local key store
│   ├── config.py       %USERPROFILE%\.claume\config.json
│   └── ui.py           pixel banner, mouse-tracking mascot, themes, input box,
│                       thinking panel, copy mode, clipboard
│   └── tools/
│       ├── registry.py     name → schema → dispatch
│       ├── fs.py           filesystem tools
│       ├── shell.py        shell + background procs + git
│       └── web.py          search + fetch
└── tests/              unit tests (unittest, zero deps)
```

## Running the proxy standalone

The proxy is its own terminal command, linked to your claume install:

```powershell
claume proxy                      # serves http://127.0.0.1:8000/v1 (Ctrl+C to stop)
claume proxy --verbose            # with request logging
```

The claume REPL auto-connects to it while it's running (the status line
shows `live`). If it's not running, the REPL tells you — or just run
`/proxy` inside claume to start it in-process.

It's also plain OpenAI on the wire, so any SDK works:

```powershell
curl http://127.0.0.1:8000/v1/chat/completions -H "Content-Type: application/json" `
  -d '{\"model\":\"openai/gpt-oss-120b\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}]}'
```

Any OpenAI SDK / tool (Aider, Cline, LlamaIndex…) can point at the proxy.

## Self-update & repair

```
❯ /update         ← pull latest code via git
❯ /reinstall      ← repair in place: re-pull source, reinstall package,
                    verify imports — config, vault, skills are kept
```

## Troubleshooting

| Problem | Fix |
|---|---|
| `claume` not found after install | open a **new** PowerShell tab (PATH refresh) |
| `cannot reach LLM endpoint` | run `/proxy`, check `/doctor` |
| `401` from NVIDIA | key invalid — `/key NVIDIA_API_KEY` to re-set |
| MCP server 'requires an API key' | `/mcp-key <server>` walks you through vaulting it |
| MCP server won't connect | `/mcp-test` shows ACTIVE/INACTIVE per server; `/doctor` for detail |
| No British voice found | Windows Settings → Time & Language → Speech → Add voices (George/Hazel) |
| Voice input fails | `pip install SpeechRecognition pyaudio`, then `/hear` |
| `410` model retired | claume auto-migrates EOL models and walks the fallback chain; set fallbacks in `/proxy-ui` |
| Rate limited | add more keys: `/key NVIDIA_API_KEY_2` (auto-rotates) |
| Task hit a checkpoint | it auto-continues (budget scales with `/effort`); say `continue` if it stops |
| Turn stopped with "same action failed 3×" | that's the anti-loop guard — give a different instruction or `/effort deep` |
| Weird characters | use Windows Terminal (better glyph support) |

## Tests

```powershell
cd claume-code
python -m unittest discover -s tests -v
```

---

MIT © TRacKay — built with [Freebuff](https://freebuff.com) 🤖
