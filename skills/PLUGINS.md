# claume PLUGINS — integrations & machinery

> **A plugin is MACHINERY, not knowledge.** Plugins are integrations that
> give claume new *capabilities*: slash commands, background processes,
> optional pip dependencies, OS-level hooks (voice, graphs, desktop apps).
> They change what claume can DO. For instruction packs that change how
> claume THINKS, see [SKILLS.md](SKILLS.md).
>
> | | SKILL | PLUGIN |
> |---|---|---|
> | What it is | markdown instructions + scripts | command + process + optional deps |
> | Adds | guidance injected into thinking | slash commands, daemons, app windows |
> | Activation | injected every turn when active | runs when you call its command |
> | Example | taste-skill (design taste) | jarvis (`/jarvis` voice assistant) |

Manage: `/plugins` · `/plugin-on <name>` · `/plugin-off <name>`

## Bundled plugins (v3)

### graphify — knowledge-graph pipeline
| | |
|---|---|
| Command | `/graphify <path>` (delegates to the bundled graphify skill doc) |
| Does | any corpus → entity/relationship extraction → community clustering → interactive HTML + GraphRAG-ready JSON + GRAPH_REPORT.md; query/BFS/explain modes; Obsidian vault export |
| Needs | `pip install graphifyy` (auto-offered on first run) |
| Source | skill doc: `skills/graphify/SKILL.md` |

### jarvis — desktop voice assistant
| | |
|---|---|
| Command | `/jarvis` (launch the desktop window) · `/jarvis cli` (in-terminal loop) |
| Does | wake-word listening ("jarvis"), speech-to-text, LLM replies through **your claume provider/key**, spoken answers, human-like animated UI with idle/listening/thinking/speaking states |
| Needs | stdlib-first. Optional: `pip install SpeechRecognition pyaudio` (mic input), `pip install openwakeword` (true neural wake word). Without them: push-to-talk + TTS still work |
| Source | `claume/jarvis.py` + `claume/jarvis_app.py` (window) — see below |

### free-claume proxy — built-in (always on)
The local OpenAI-compatible proxy (`claume proxy`, `/proxy`) with key
rotation and model fallback chains. Counted here for completeness: it is
the machinery claume's free-model providers ride on. The **tokenin**
provider (v3 default) is configured out of the box with a community key —
override with `/key TOKENIN_API_KEY <yours>`.

## Plugin vs MCP server vs skill — when to use what

- **Skill** — you want claume to *behave* differently (taste, workflow, docs).
- **Plugin** — you want a new *feature/command* with process machinery.
- **MCP server** (`/mcp-add …`) — you want claume to *call external tools*
  over the Model Context Protocol (bridged as `mcp_<server>_<tool>`).
