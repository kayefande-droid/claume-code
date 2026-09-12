"""Subagent orchestration for claume-code.

Spawn independent sub-agents that each get their own message history and
step budget, then merge their findings into one combined report for the
parent agent. Like Claude Code's Task tool, but tuned for the free
NVIDIA NIM models behind the free-claume proxy.

Parallel execution: with subagent_parallel=true (default) agents run on
threads; results are combined in spawn order.
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from . import config, llm, parser, prompts, security
from .tools import registry

LOG_LINES = 400


@dataclass
class SubagentResult:
    name: str
    task: str
    summary: str = ""
    steps: int = 0
    tool_calls: int = 0
    error: Optional[str] = None
    duration: float = 0.0
    transcript: List[str] = field(default_factory=list)


class Subagent:
    """A headless mini-agent: same ReAct loop, no UI, capped budget."""

    def __init__(
        self,
        name: str,
        task: str,
        workspace: Path,
        max_steps: int = 14,
        max_tool_calls: int = 24,
        log: Optional[List[str]] = None,
        silent: bool = True,
    ) -> None:
        self.name = name
        self.task = task
        self.workspace = workspace
        self.max_steps = max_steps
        self.max_tool_calls = max_tool_calls
        self.history: List[Dict[str, str]] = []
        self.log = log if log is not None else []
        self.silent = silent
        self._secrets: List[str] = []
        self.result = SubagentResult(name=name, task=task)

    # -- secrets -------------------------------------------------------
    def _collect_secrets(self) -> List[str]:
        if self._secrets:
            return self._secrets
        from . import keyvault

        vault = config.Config().get("key_vault", {})
        for name in vault.keys() if isinstance(vault, dict) else []:
            val = keyvault.get_key(name)
            if val:
                self._secrets.append(val)
        return self._secrets

    # -- the loop ------------------------------------------------------
    def run(self) -> SubagentResult:
        t0 = time.time()
        cfg = config.Config()
        system_prompt = prompts.build_system_prompt(
            registry.schemas(),
            prompts.build_context_block(str(self.workspace), "posix", cfg.model)
            + f"\n- You are subagent '{self.name}'. Work only on your task. "
            "End with a final that reports concrete findings (files touched, results, blockers).",
        )
        self.history.append({"role": "user", "content": self.task})

        steps = 0
        tool_calls = 0
        while steps < self.max_steps and tool_calls < self.max_tool_calls:
            steps += 1
            messages = [{"role": "system", "content": system_prompt}] + self.history
            try:
                reply = llm.stream_chat(messages, effort="fast")
            except llm.LLMError as exc:
                self.result.error = str(exc)
                break

            reply = security.redact_secrets(reply, self._collect_secrets())
            turn = parser.parse_turn(reply)
            if turn.error:
                self.history.append({"role": "assistant", "content": reply[:4000]})
                self.history.append(
                    {
                        "role": "user",
                        "content": "SYSTEM: invalid envelope; reply with ONLY the JSON object.",
                    }
                )
                continue

            if turn.thought:
                self._trace(f"◈ {turn.thought}")

            if turn.final is not None:
                self.result.summary = turn.final
                self.history.append({"role": "assistant", "content": reply[:4000]})
                break

            if turn.action:
                tool_calls += 1
                try:
                    result, is_err = registry.execute(self.workspace, turn.action.tool, turn.action.args)
                except Exception as exc:
                    result, is_err = f"error: {exc}", True
                result = security.redact_secrets(result, self._collect_secrets())
                self._trace(f"{'✗' if is_err else '✓'} {turn.action.tool} → {result[:120]}")
                self.history.append({"role": "assistant", "content": reply[:4000]})
                self.history.append(
                    {"role": "user", "content": f"OBSERVATION ({turn.action.tool}):\n{result[:6000]}"}
                )

        self.result.steps = steps
        self.result.tool_calls = tool_calls
        self.result.duration = time.time() - t0
        if not self.result.summary and not self.result.error:
            self.result.summary = "(subagent produced no final — see transcript)"
        return self.result

    def _trace(self, line: str) -> None:
        self.log.append(line)
        if len(self.log) > LOG_LINES:
            del self.log[:-LOG_LINES]


def _print_progress(name: str, log: List[str], done_flag: Dict[str, bool]) -> None:
    """Render live subagent progress beneath a locked header."""
    from .ui import ACCENT, MUTED, RESET

    header = f"{ACCENT}┌─ subagent {name} "
    print(header + "─" * max(0, 58 - len(name)) + RESET)
    cursor = 0
    while not done_flag.get(name):
        while cursor < len(log):
            line = log[cursor]
            cursor += 1
            print(f"{MUTED}│{RESET} {line[:118]}")
        time.sleep(0.4)
    # drain anything left
    while cursor < len(log):
        print(f"{MUTED}│{RESET} {log[cursor][:118]}")
        cursor += 1
    print(f"{ACCENT}└─ {name} finished{RESET}")


_PROGRESS_LOCK = threading.Lock()


def run_swarm(
    workspace: Path,
    tasks: List[Dict[str, str]],
    ui: Any = None,
) -> List[SubagentResult]:
    """Run several subagents (parallel or serial) and return results in order.

    tasks: [{"name": "explorer", "task": "map the repo"}, ...]
    """
    cfg = config.Config()
    max_steps = int(cfg.get("subagent_max_steps", 14))
    max_tools = int(cfg.get("subagent_max_tool_calls", 24))
    parallel = bool(cfg.get("subagent_parallel", True))

    agents: List[Subagent] = []
    logs: List[List[str]] = []
    for spec in tasks:
        log: List[str] = []
        logs.append(log)
        agents.append(
            Subagent(
                name=str(spec.get("name", f"agent-{len(agents) + 1}"))[:24],
                task=str(spec.get("task", "")),
                workspace=workspace,
                max_steps=max_steps,
                max_tool_calls=max_tools,
                log=log,
            )
        )

    threads: List[threading.Thread] = []
    show_progress = ui is not None and not getattr(ui, "quiet", False)
    done_flag: Dict[str, bool] = {}

    def _runner(agent: Subagent, flag: Dict[str, bool]) -> None:
        try:
            agent.run()
        finally:
            flag[agent.name] = True

    for agent, log in zip(agents, logs):
        if parallel:
            if show_progress:
                t = threading.Thread(
                    target=_print_progress, args=(agent.name, log, done_flag), daemon=True
                )
                t.start()
                threads.append(t)
            th = threading.Thread(target=_runner, args=(agent, done_flag), daemon=True)
            th.start()
            threads.append(th)
        else:
            agent.run()

    if parallel:
        for th in threads:
            if th.is_alive():
                th.join(timeout=600)

    return [a.result for a in agents]


# ---------------------------------------------------------------------------
# Combined summary — one more LLM pass merges all subagent reports
# ---------------------------------------------------------------------------
def combine_results(results: List[SubagentResult], workspace: Path) -> str:
    """Ask the model to merge subagent findings into one report."""
    cfg = config.Config()
    parts = []
    for r in results:
        head = f"## {r.name} ({r.steps} steps, {r.tool_calls} tool calls"
        if r.duration:
            head += f", {r.duration:.1f}s"
        head += ")"
        if r.error:
            body = f"ERROR: {r.error}"
        else:
            body = r.summary or "(no summary)"
        parts.append(f"{head}\n{body}")

    messages = [
        {
            "role": "system",
            "content": (
                "You are claume's merge agent. Several subagents worked in "
                "parallel on parts of one job. Merge their reports into a "
                "single concise summary for the user: what was found/done, "
                "conflicts or duplicates, and recommended next steps. No preamble."
            ),
        },
        {"role": "user", "content": "\n\n".join(parts)[:24_000]},
    ]
    try:
        return llm.stream_chat(messages, effort="balanced")
    except llm.LLMError:
        # Never fail the whole swarm because the merge pass errored.
        return "\n\n".join(f"{r.name}: {r.error or r.summary}" for r in results)
