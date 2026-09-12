# claume-code

```
 ██████╗██╗      █████╗ ██╗   ██╗███╗   ███╗███████╗███████╗
██╔════╝██║     ██╔══██╗██║   ██║████╗ ████║██╔════╝██╔════╝
██║     ██║     ███████║██║   ██║██╔████╔██║███████╗█████╗
██║     ██║     ██╔══██║██║   ██║██║╚██╔╝██║╚════██║╚════██║
╚█████╗ ███████╗██║  ██║╚██████╔╝██║ ╚═╝ ██║███████║███████║
 ╚════╝ ╚══════╝╚═╝  ╚═╝ ╚═════╝ ╚═╝     ╚═╝╚══════╝╚══════╝
```

**claume-code v2** is a pixel-animated **desktop CLI coding agent** (not a web app)
that builds full projects from natural-language prompts — inspired by Claude Code and
Freebuff, powered **free** by NVIDIA NIM through the built-in **free-claume proxy**.

> 🎬 Pixel banner + animated bot mascot · 🧠 extended-thinking ReAct loop
> 🛠 18 built-in tools · 🌐 free-claume proxy (OpenAI-compatible) · 🖥 admin UI at `/admin`
> 🔐 local key vault · 🧩 MCP client + **Link System design pipeline** · 📚 skills from GitHub
> 🎭 **4 permission modes** (manual / accept / plan / auto, Shift+Tab) · 💾 **persistent sessions**
> 🤖 **parallel subagents** · 🎨 **7 color themes** · 📋 clipboard integration · 🔁 self-update

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

**Option B — one-liner (once published to GitHub):**

```powershell
irm https://raw.githubusercontent.com/kayefande-droid/claume-code/main/install.ps1 | iex
```

The installer copies the app to `%USERPROFILE%\.claume`, creates an isolated venv,
installs dependencies (**stdlib-only — nothing heavy**), and registers the `claume`
command on your user PATH. Then open a **new** PowerShell tab and run:

```powershell
claume
```

First run asks for your free `nvapi-…` key (get it at build.nvidia.com → any model
→ *Get API Key*). It's stored obfuscated in `%USERPROFILE%\.claume\vault.bin`.

## Usage examples

```
claume

❯ build me a snake game in python with pygame, single file
❯ clone https://github.com/pallets/flask and explain its structure
❯ fix the failing test in tests/ and make pytest pass
❯ create a REST API with fastapi + sqlite with tests
❯ /mode plan       ← research first, present a plan, no writes
❯ /agents scan auth ; scan api ; scan db    ← parallel subagents, merged report
❯ /design fluid bento landing hero ← MCP design pipeline (Link System)
❯ /theme synthwave ← switch the whole terminal palette
❯ /continue        ← pick up yesterday's session
❯ /proxy-ui        ← admin UI in your browser: paste key, pick model, Apply
❯ /effort deep     ← harder thinking for tricky bugs
```

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
| `/model <name>` | pick model (e.g. `qwen/qwen3-coder-480b-a35b-instruct`) |
| `/recommend` | recommended free models |
| `/effort fast\|balanced\|deep` | thinking budget (tokens + temperature) |
| `/mode <name>` | manual · accept · plan · auto (Shift+Tab cycles) |
| `/auto on\|off` | legacy alias of `/mode auto\|manual` |
| `/theme [name]` | 7 terminal palettes: nvidia-green, claude-orange, cyber-blue, synthwave, matrix, sunset, mono |
| `/expand on\|off` | show full tool output (default trims to 14 lines) |
| `/copy [text]` | copy last answer (or text) to clipboard — answers auto-copy |
| `/mascot` | the claume pixel bot says hi |
| `/session [id]` · `/resume` · `/continue` | persistent chat history (`claume --continue` on boot) |
| `/agents t1 ; t2 ; t3` | parallel subagents → merged report |
| `/design <prompt>` | run the MCP Link System design pipeline |
| `/mcp-preset design` | install the UI stack: 21st.dev + reactbits + motion + shadcnspace |
| `/proxy` | start/reuse the free-claume proxy |
| `/proxy-ui` | luxury dashboard in your browser |
| `/keys` · `/key NAME` · `/key-del NAME` | manage the local key vault ("live space") |
| `/provider <name>` | nvidia · groq · openrouter · deepseek · openai · mistral · together · fireworks |
| `/skills` · `/skill owner/repo` | install skills from GitHub |
| `/mcp` · `/mcp-add name cmd args` · `/mcp-del name` | manage MCP servers |
| `/md <name>` | create a new instructions `.md` (like CLAUDE.md) |
| `/git` · `/config` · `/doctor` · `/update` | maintenance |
| `/exit` | quit |

### Effort levels

| Level | max_tokens | temp | use for |
|---|---|---|---|
| `fast` | 1 024 | 0.4 | quick edits, renames |
| `balanced` | 4 096 | 0.2 | normal features |
| `deep` | 8 192 | 0.1 | architecture, gnarly bugs |

### Multi-provider "live space"

Any OpenAI-compatible provider works. Vault the key once, switch provider:

```
/key GROQ_API_KEY        ← paste gsk_...
/provider groq
/model llama-3.3-70b-versatile
```

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
(claume builds that part by hand, same quality bar).

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
│   ├── cli.py          REPL: banner, mascot, sessions, Shift+Tab modes, slash dispatch
│   ├── agent.py        ReAct loop: think → act → observe → auto-continue
│   ├── parser.py       forgiving JSON envelope parser
│   ├── prompts.py      system prompts + mode blocks + extended thinking
│   ├── llm.py          OpenAI-compatible client + provider map + model fallback chain
│   ├── sessions.py     persistent chat history (~/.claume/sessions)
│   ├── subagents.py    parallel multi-task agents + merge pass
│   ├── mcp.py          MCP stdio JSON-RPC client + Link System design pipeline
│   ├── proxy.py        free-claume proxy (OpenAI → NVIDIA NIM, streaming,
│   │                   retries, multi-key rotation, first-run key prompt)
│   ├── proxy_ui.py     luxury browser dashboard
│   ├── commands.py     /slash command handlers
│   ├── security.py     command classifier (safe/caution/destructive) + redaction
│   ├── keyvault.py     obfuscated local key store
│   ├── config.py       %USERPROFILE%\.claume\config.json
│   └── ui.py           pixel banner, mascot, 7 themes, clipboard, mode chips
│   └── tools/
│       ├── registry.py     name → schema → dispatch
│       ├── fs.py           filesystem tools
│       ├── shell.py        shell + background procs + git
│       └── web.py          search + fetch
└── tests/              18 unit tests (unittest, zero deps)
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
  -d '{\"model\":\"meta/llama-3.3-70b-instruct\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}]}'
```

Any OpenAI SDK / tool (Aider, Cline, LlamaIndex…) can point at the proxy.

## Self-update

```
❯ /update
```

Pulls the latest code via git (or re-run the installer one-liner).

## Troubleshooting

| Problem | Fix |
|---|---|
| `claume` not found after install | open a **new** PowerShell tab (PATH refresh) |
| `cannot reach LLM endpoint` | run `/proxy`, check `/doctor` |
| `401` from NVIDIA | key invalid — `/key NVIDIA_API_KEY` to re-set |
| `410` model retired | claume auto-migrates EOL models and walks the fallback chain; set fallbacks in `/proxy-ui` |
| Rate limited | add more keys: `/key NVIDIA_API_KEY_2` (auto-rotates) |
| Task hit a checkpoint | it auto-continues (up to 5×); say `continue` if it stops — progress is preserved |
| Weird characters | use Windows Terminal (better glyph support) |

## Tests

```powershell
cd claume-code
python -m unittest discover -s tests -v   # 18 tests, all pass
```

---

MIT © TRacKay — built with [Freebuff](https://freebuff.com) 🤖
