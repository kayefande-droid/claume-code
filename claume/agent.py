"""ReAct agent loop for claume-code.

Each user turn:
  1. Build message history + system prompt (with tool schemas + context).
  2. Ask the LLM (via the free-claume proxy or another provider).
  3. Parse the strict JSON envelope (thought / action / final).
  4. Execute the action (with confirmation for risky tools).
  5. Feed the observation back and repeat until 'final' or step cap.

v2 changes:
  * step counter resets every turn (fixes permanent "step limit reached")
  * auto-continue: when the cap is hit mid-task the turn keeps going
    with a continuation prompt instead of dying
  * plan mode enforces read-only tools
  * spawn_subagents tool for parallel multi-task agents
  * session autosave hook
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import config, llm, parser, prompts, security, subagents
from .tools import registry

ConfirmFn = Callable[[str, str], bool]  # (title, detail) -> bool

READ_ONLY_TOOLS = {
    "read_file", "list_directory", "tree_view", "search_text",
    "git_status", "web_search", "fetch_url", "background_output",
    "spawn_subagents",
}


class Agent:
    def __init__(
        self,
        workspace: Path,
        ui: Any,
        confirm_fn: ConfirmFn,
        mode: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> None:
        self.workspace = workspace
        self.ui = ui
        self.confirm_fn = confirm_fn
        self.cfg = config.Config()
        self.mode = self.cfg.mode if mode is None else mode
        self.history: List[Dict[str, str]] = []
        self.step = 0
        self.max_steps = int(self.cfg.get("max_steps", 24))
        self._tool_calls = 0
        self._tool_cap = int(self.cfg.get("max_tool_calls_per_turn", 40))
        self._secret_cache: List[str] = []
        self._fail_streak = 0
        self.session_id = session_id
        self._continues_used = 0
        self._subagent_log: List[str] = []

    # ------------------------------------------------------------------
    # Context
    # ------------------------------------------------------------------
    def _context_block(self) -> str:
        extra = f"- Permission mode: {self.mode}"
        return prompts.build_context_block(
            str(self.workspace), os.name, self.cfg.model, extra=extra
        )

    def _secrets(self) -> List[str]:
        """Collect secret values present locally so we can redact output."""
        if not self._secret_cache:
            from . import keyvault

            vault = self.cfg.get("key_vault", {})
            for name in vault.keys() if isinstance(vault, dict) else []:
                val = keyvault.get_key(name)
                if val:
                    self._secret_cache.append(val)
            for env_name in ("NVIDIA_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY"):
                val = os.environ.get(env_name)
                if val:
                    self._secret_cache.append(val)
        return self._secret_cache

    # ------------------------------------------------------------------
    # One full user turn (multi-step ReAct with auto-continue)
    # ------------------------------------------------------------------
    def run_turn(self, user_text: str) -> str:
        self.history.append({"role": "user", "content": user_text})
        final_text = ""
        self._tool_calls = 0
        self._continues_used = 0
        max_continues = int(self.cfg.get("max_auto_continues", 5))
        auto_continue = bool(self.cfg.get("auto_continue", True))

        system_prompt = prompts.build_system_prompt(
            registry.schemas(), self._context_block(), mode=self.mode
        )

        # --- plan mode: force read-only research -----------------------
        if self.mode == "plan":
            self.history.append(
                {"role": "user", "content": prompts.build_plan_instruction()}
            )

        while True:
            # --- cap checks -------------------------------------------
            if self.step >= self.max_steps or self._tool_calls >= self._tool_cap:
                if auto_continue and self._continues_used < max_continues:
                    self._continues_used += 1
                    self.ui.render_info(
                        f"reached {self.max_steps}-step checkpoint — continuing "
                        f"({self._continues_used}/{max_continues})…"
                    )
                    self.history.append(
                        {
                            "role": "user",
                            "content": (
                                "SYSTEM: you reached the checkpoint. Do NOT restart. "
                                "Continue the task from where you left off. If you "
                                "are nearly done, wrap up and produce 'final'."
                            ),
                        }
                    )
                    # Refill budgets and DON'T count this cycle against the
                    # step cap — otherwise the fresh continue prompt would
                    # immediately hit the cap again without a model call.
                    self._tool_calls = 0
                    self.step = 0
                    continue
                self.ui.render_warning(
                    "stopping here — auto-continue budget used up. "
                    "Say 'continue' to keep going (progress is preserved)."
                )
                break

            self.step += 1
            messages = [{"role": "system", "content": system_prompt}] + self.history

            # --- ask the model -----------------------------------------
            ui_buffer: List[str] = []
            try:
                reply = llm.stream_chat(
                    messages,
                    on_token=lambda t: self._on_token(t, ui_buffer),
                )
            except llm.LLMError as exc:
                self.ui.render_error(str(exc))
                return "(LLM error — turn aborted)"

            self._flush_stream_buffer(ui_buffer)
            reply = security.redact_secrets(reply, self._secrets())

            # --- parse the envelope ------------------------------------
            turn = parser.parse_turn(reply)
            if turn.error:
                self._fail_streak += 1
                self.history.append({"role": "assistant", "content": reply[:4000]})
                self.history.append(
                    {
                        "role": "user",
                        "content": (
                            "SYSTEM: your last reply was not a valid JSON envelope "
                            f"({turn.error}). Reply again with ONLY the JSON object "
                            "in the schema I gave you."
                        ),
                    }
                )
                if self._fail_streak >= 4:
                    self.ui.render_error(
                        "model keeps producing invalid output — turn paused. "
                        "Try /effort deep or /model."
                    )
                    break
                continue

            self._fail_streak = 0

            if turn.thought:
                self.ui.render_thought(turn.thought)

            if turn.final is not None:
                self.history.append({"role": "assistant", "content": reply[:4000]})
                final_text = turn.final
                break

            if turn.action:
                # --- plan-mode gate -----------------------------------
                if self.mode == "plan" and turn.action.tool not in READ_ONLY_TOOLS:
                    result = (
                        f"error: plan mode blocks '{turn.action.tool}' — read-only "
                        "tools only. Produce your plan as 'final'."
                    )
                    is_err = True
                else:
                    self._tool_calls += 1
                    result, is_err = self._execute_with_confirm(turn.action)
                self.ui.render_action(turn.action.tool, turn.action.args, result, is_err)

                self.history.append({"role": "assistant", "content": reply[:4000]})
                self.history.append(
                    {
                        "role": "user",
                        "content": f"OBSERVATION ({turn.action.tool}):\n{result}",
                    }
                )

        # --- autosave ---------------------------------------------------
        if self.session_id:
            self._autosave()

        return final_text or "(no final answer produced)"

    # ------------------------------------------------------------------
    # Streaming display
    # ------------------------------------------------------------------
    def _on_token(self, token: str, buffer: List[str]) -> None:
        if self.cfg.get("stream", True):
            self.ui.stream_token(token, buffer)

    def _flush_stream_buffer(self, buffer: List[str]) -> None:
        self.ui.end_stream(buffer)

    # ------------------------------------------------------------------
    # Tool execution + confirmations
    # ------------------------------------------------------------------
    def _execute_with_confirm(self, action: parser.Action) -> Tuple[str, bool]:
        tool = registry.get(action.tool)
        if not tool:
            return f"error: unknown tool '{action.tool}'", True

        # mode rules
        if self.mode == "plan" and action.tool not in READ_ONLY_TOOLS:
            return "error: plan mode blocks this tool", True

        if action.tool == "spawn_subagents":
            return self._run_subagents(action.args)

        needs = tool.dangerous or (tool.needs_confirm and tool.needs_confirm(action.args))
        if needs:
            verdict = security.classify_command(str(action.args.get("command", "")))
            is_destructive = tool.dangerous or verdict.level == "destructive"
            detail = str(action.args.get("command") or action.args.get("path") or action.args)

            if is_destructive:
                # Destructive actions ask in EVERY mode, no exceptions.
                self.ui.render_warning(f"DESTRUCTIVE: {detail}")
                ok = self.confirm_fn(action.tool, detail)
                if not ok:
                    return "user declined this action", False
            elif self.mode == "auto":
                pass  # auto mode: caution-level actions run without asking
            elif self.mode == "accept" and action.tool in ("write_file", "patch_file", "make_directory"):
                pass  # accept-edits: file edits run free
            else:
                ok = self.confirm_fn(action.tool, detail)
                if not ok:
                    return "user declined this action", False

        result, is_err = registry.execute(self.workspace, action.tool, action.args)
        result = security.redact_secrets(result, self._secrets())
        return result, is_err

    # ------------------------------------------------------------------
    # Subagents tool
    # ------------------------------------------------------------------
    def _run_subagents(self, args: Dict[str, Any]) -> Tuple[str, bool]:
        raw = args.get("tasks")
        if not isinstance(raw, list) or not raw:
            return "error: spawn_subagents requires tasks: [{name, task}, ...]", True
        tasks = []
        for i, item in enumerate(raw[:6]):
            if not isinstance(item, dict) or not item.get("task"):
                continue
            tasks.append(
                {
                    "name": str(item.get("name", f"agent-{i + 1}")),
                    "task": str(item["task"]),
                }
            )
        if not tasks:
            return "error: no valid tasks given", True
        self.ui.render_info(
            f"spawning {len(tasks)} subagent(s) ({'parallel' if self.cfg.get('subagent_parallel', True) else 'serial'})…"
        )
        results = subagents.run_swarm(self.workspace, tasks, ui=self.ui)
        merged = subagents.combine_results(results, self.workspace)
        lines = []
        for r in results:
            status = "✗ " + (r.error or "no summary") if r.error else (r.summary[:120] if r.summary else "(no summary)")
            lines.append(f"{r.name}: {r.steps} steps, {r.tool_calls} calls — {status}")
        return "\n".join(lines) + "\n\nMERGED REPORT:\n" + merged, False

    # ------------------------------------------------------------------
    # Session autosave
    # ------------------------------------------------------------------
    def _autosave(self) -> None:
        try:
            from . import sessions

            sessions.save_session(
                self.session_id,
                self.history,
                meta={"workspace": str(self.workspace), "mode": self.mode},
            )
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Compaction
    # ------------------------------------------------------------------
    def compact_if_needed(self) -> bool:
        """Summarize old observations when history gets huge."""
        limit = int(self.cfg.get("context_tokens_soft_limit", 96_000))
        approx_tokens = sum(len(m["content"]) // 4 for m in self.history)
        if approx_tokens < limit:
            return False
        keep = 8
        if len(self.history) <= keep:
            return False
        old = self.history[:-keep]
        summary_lines = []
        for m in old:
            if m["role"] == "user" and m["content"].startswith("OBSERVATION"):
                summary_lines.append(m["content"][:300])
        digest = "\n".join(summary_lines[-12:]) or "(empty)"
        self.history = self.history[-keep:]
        self.history.insert(
            0,
            {
                "role": "user",
                "content": f"SYSTEM: earlier observations were compacted. Digest:\n{digest}",
            },
        )
        self.ui.render_warning("context compacted (old observations summarized)")
        return True

    def reset(self) -> None:
        self.history.clear()
        self.step = 0

    def set_mode(self, mode: str) -> None:
        if mode in ("manual", "accept", "plan", "auto"):
            self.mode = mode
            self.cfg.set("mode", mode)
