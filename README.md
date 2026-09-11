# claume-code

```
 ██████╗██╗      █████╗ ██╗   ██╗███╗   ███╗███████╗
██╔════╝██║     ██╔══██╗██║   ██║████╗ ████║██╔════╝
██║     ██║     ███████║██║   ██║██╔████╔██║███████╗
██║     ██║     ██╔══██║██║   ██║██║╚██╔╝██║╚════██║
╚█████╗ ███████╗██║  ██║╚██████╔╝██║ ╚═╝ ██║███████║
 ╚════╝ ╚══════╝╚═╝  ╚═╝ ╚═════╝ ╚═╝     ╚═╝╚══════╝
```

**claume-code** is a pixel-animated **desktop CLI coding agent** (not a web app) that
builds full projects from natural-language prompts — inspired by Claude Code and
Freebuff, powered **free** by NVIDIA NIM through the built-in **free-claume proxy**.

> 🎬 Pixel banner animations · 🧠 ReAct agentic loop · 🛠 17 built-in tools
> 🌐 free-claume proxy (OpenAI-compatible) · 🔐 local key vault ("live space")
> 🧩 MCP server support · 📚 skills from GitHub · ⚡ auto mode + effort levels
> 🌍 multi-language (Python/JS/TS/Go/Rust/Java/C#/C++…) · 🔁 self-update

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
❯ /proxy-ui        ← luxurious browser dashboard for the proxy
❯ /auto on         ← fewer confirmations (destructive still asks)
❯ /effort deep     ← harder thinking for tricky bugs
```

### Slash commands

| Command | What it does |
|---|---|
| `/help` | all commands |
| `/new` | fresh conversation |
| `/model <name>` | pick model (e.g. `meta/llama-3.3-70b-instruct`) |
| `/recommend` | recommended free models |
| `/effort fast\|balanced\|deep` | thinking budget (tokens + temperature) |
| `/auto on\|off` | auto mode: fewer confirmations |
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
`fetch_url` · plus MCP servers you register.

**Safety:** every command is classified `safe / caution / destructive`
(`claume/security.py`). Caution → asked. Destructive (`rm -rf`, `git push --force`,
`format`, `del /s`…) → **always asked**, even in auto mode. Secrets are scrubbed
from everything shown to the model.

## Architecture

```
claume-code/
├── install.ps1 / uninstall.ps1     PowerShell installer (→ %USERPROFILE%\.claume)
├── run-claume.ps1                  run from source
├── pyproject.toml                  pip packaging (claume console script)
├── claume/
│   ├── cli.py          REPL: banner, first-run, slash dispatch
│   ├── agent.py        ReAct loop: think → act → observe → repeat
│   ├── parser.py       forgiving JSON envelope parser
│   ├── prompts.py      system prompts + context builder
│   ├── llm.py          OpenAI-compatible client + provider map ("live space")
│   ├── proxy.py        free-claume proxy (OpenAI → NVIDIA NIM, streaming,
│   │                   retries, multi-key rotation, first-run key prompt)
│   ├── proxy_ui.py     luxury browser dashboard
│   ├── commands.py     /slash command handlers
│   ├── security.py     command classifier (safe/caution/destructive) + redaction
│   ├── keyvault.py     obfuscated local key store
│   ├── config.py       %USERPROFILE%\.claume\config.json
│   └── ui.py           pixel banner, animations, colors, confirmations
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
| Rate limited | add more keys: `/key NVIDIA_API_KEY_2` (auto-rotates) |
| Weird characters | use Windows Terminal (better glyph support) |

## Tests

```powershell
cd claume-code
python -m unittest discover -s tests -v   # 18 tests, all pass
```

---

MIT © TRacKay — built with [Freebuff](https://freebuff.com) 🤖
