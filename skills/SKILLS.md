# claume SKILLS — instruction packs

> **A skill is KNOWLEDGE, not machinery.** Skills are markdown instruction
> packs (plus optional bundled scripts) that get *adopted into claume's
> thinking* — they change how claume approaches every task. They never add
> commands or processes. That's what [PLUGINS.md](PLUGINS.md) is for.
>
> | | SKILL | PLUGIN |
> |---|---|---|
> | What it is | instructions + reference docs | integration: commands, deps, processes |
> | Adds | guidance, taste, workflows | slash commands, daemons, pip deps |
> | Injection | into the system prompt every turn | invoked on demand |
> | Example | ui-ux-pro-max (design workflow) | graphify (`/graphify` pipeline) |

Manage: `/skills` · `/skill <owner/repo>` · `/skill-on|off|use|run|rm <name>` · `/skill-all on|off`

## Bundled skills (ship with v3 — seeded + activated on first run)

| Skill | Source | What it teaches claume |
|---|---|---|
| **ui-ux-pro-max-skill** | [nextlevelbuilder/ui-ux-pro-max-skill](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill) | Flagship design workflow: 4-step search-first process over 145 docs + CSV ranking engine (styles, palettes, typography, motion, stacks) |
| **taste-skill** | [Leonxlnx/taste-skill](https://github.com/Leonxlnx/taste-skill) | Aesthetic taste research — sub-skills: brandkit, brutalist, minimalist, redesign, stitch, image-to-code; ships runnable scripts |
| **awesome-claude-design** | [VoltAgent/awesome-claude-design](https://github.com/VoltAgent/awesome-claude-design) | Curated design-technique reference: layout systems, color theory, typography pairing, component craft |
| **design-md-chrome** | [bergside/design-md-chrome](https://github.com/bergside/design-md-chrome) | DESIGN.md authoring framework — design-system-as-markdown (tokens, chrome, components) for consistent UI builds |
| **design-motion-principles** | [kylezantos/design-motion-principles](https://github.com/kylezantos/design-motion-principles) | Motion & animation principles: timing, easing, choreography — Framer-grade interaction design |
| **claudex-loop** | [chaseai-yt/claudex-loop](https://github.com/chaseai-yt/claudex-loop) | Loop discipline: requirements → plan review → build → independent inspection; bounded iteration with model routing |
| **agency-agents** | [msitarzewski/agency-agents](https://github.com/msitarzewski/agency-agents) | 100+ role-specific agent sheets (backend architect, code reviewer, data-viz, desktop-app engineer, …) adoptable per task |
| **system-prompts-leaks** | [asgeirtj/system_prompts_leaks](https://github.com/asgeirtj/system_prompts_leaks) | Source archive of Claude/Fable 5 system prompts — the techniques claume v3 transposes into its own thinking (see below) |
| **graphify** *(skill doc for the plugin)* | bundled | The `/graphify` knowledge-graph pipeline instructions (plugin machinery in PLUGINS.md) |
| **21st-\*** (7 skills) | bundled | 21st.dev integration guides: UI explore/build/review, registry, design-sync, CLI use |

## Pre-installed legacy skills

- **godmode-skill** — aggressive mode instruction set (CLAUDE.md format)

## Install your own

```
/skill <owner/repo>        # any GitHub repo with SKILL.md / README.md
/skills                    # list with ● active / ○ inactive
/skill-on <name>           # inject into every task
/skill-use <name>          # one-shot: next task only
/skill-run <name> <script> # run a bundled script (py/sh/ps1)
```

Skills live in `~/.claume/skills/<name>` with a `skill-manifest.json`.
Active skills' docs (capped per-skill) are concatenated into the system
prompt under "Active skills" each turn — that is the whole mechanism, and
it is why skills and plugins must not be confused.
