"""ReAct agent loop for claume-code.

Each user turn:
  1. Build message history + system prompt (with tool schemas + context).
  2. Ask the LLM (via the free-claume proxy or another provider).
  3. Parse the strict JSON envelope (thought / action / final).
  4. Execute the action (with confirmation for risky tools).
  5. Feed the observation back and repeat until 'final' or step cap.

v2.1 changes:
  * auto-mode infinite loop fixed: interrupted streams are caught,
    repeated identical failing actions are detected and broken, and the
    fail-streak path aborts cleanly instead of spinning forever
  * animated thinking shimmer + Claude-style thought rendering
  * skills (.md instruction packs) injected into the system prompt
  * MCP server status (enabled/active/tool counts) in the context
  * effort-based step budgets (fast/balanced/deep/ultra)
  * optional voice response of the final answer (/voice on)
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import config, llm, parser, prompts, security
from .tools import registry

ConfirmFn = Callable[[str, str], bool]  # (title, detail) -> bool

READ_ONLY_TOOLS = {
    "read_file", "list_directory", "tree_view", "search_text",
    "git_status", "web_search", "fetch_url", "background_output",
    "spawn_subagents",
}

# Effort → (max_steps, max_tool_calls, max_auto_continues)
EFFORT_BUDGETS = {
    "fast": (12, 16, 2),
    "balanced": (24, 40, 5),
    "deep": (48, 80, 8),
    "ultra": (90, 160, 12),
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
        self._tool_calls = 0
        self._secret_cache: List[str] = []
        self._fail_streak = 0
        self.session_id = session_id
        self._continues_used = 0
        self._subagent_log: List[str] = []
        # Loop guards
        self._last_action_key = ""
        self._last_action_error_count = 0
        # Live-input support: the REPL stays interactive while a task runs.
        self._interrupt_event = threading.Event()
        self._busy = False
        self._current_task_text = ""  # design-brief injection reads this
        self._apply_effort_budget()

    # ------------------------------------------------------------------
    # Live-input: interrupt + busy state (thread-safe)
    # ------------------------------------------------------------------
    def request_interrupt(self) -> None:
        """Ask the running turn to stop at the next step boundary."""
        self._interrupt_event.set()

    def is_busy(self) -> bool:
        return self._busy

    def _check_interrupt(self) -> bool:
        if self._interrupt_event.is_set():
            self._interrupt_event.clear()
            return True
        return False

    # ------------------------------------------------------------------
    # Effort → budgets
    # ------------------------------------------------------------------
    def _apply_effort_budget(self) -> None:
        effort = self.cfg.effort if self.cfg.effort in EFFORT_BUDGETS else "balanced"
        steps, tools, continues = EFFORT_BUDGETS[effort]
        self.max_steps = int(self.cfg.get("max_steps", steps))
        self._tool_cap = int(self.cfg.get("max_tool_calls_per_turn", tools))
        self._max_continues = int(self.cfg.get("max_auto_continues", continues))

    def on_effort_changed(self) -> None:
        """Re-read budgets after /effort."""
        self._apply_effort_budget()

    # ------------------------------------------------------------------
    # Context
    # ------------------------------------------------------------------
    def _context_block(self) -> str:
        extra = f"- Permission mode: {self.mode}"
        mcp_status = ""
        try:
            servers = self.cfg.get("mcp_servers", {})
            if isinstance(servers, dict) and servers:
                from . import mcp as mcpmod

                # Cheap probe: list tools from already-running servers only.
                active: Dict[str, List[str]] = {}
                for name, spec in servers.items():
                    if not (isinstance(spec, dict) and spec.get("enabled", True)):
                        active[name] = []
                        continue
                    srv = mcpmod._processes.get(name)
                    if srv is not None:
                        try:
                            active[name] = [t.get("name", "?") for t in srv.list_tools()]
                        except Exception:
                            active[name] = []
                mcp_status = prompts.build_mcp_status(servers, active)
        except Exception:
            mcp_status = ""
        return prompts.build_context_block(
            str(self.workspace), os.name, self.cfg.model,
            extra=extra, mcp_status=mcp_status,
        )

    def _skills_block(self) -> str:
        try:
            from . import skills as skillsmod

            return skillsmod.active_instructions()
        except Exception:
            return ""

    def _design_block(self) -> str:
        """Studio design brief injected for website/UI tasks."""
        try:
            return prompts.build_design_block(getattr(self, "_current_task_text", ""))
        except Exception:
            return ""

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
    def run_turn(self, user_text: str, attachments: Optional[List[dict]] = None) -> str:
        """One full user turn.

        ``attachments`` is an optional list of
        ``{"name", "data_url", "bytes"}`` image dicts (from
        ``/image <path>``); when present the user message becomes an
        OpenAI-style multimodal content array so vision-capable models
        can see the images.
        """
        if attachments:
            content: list = [{"type": "text", "text": user_text}]
            for att in attachments:
                content.append(
                    {"type": "image_url", "image_url": {"url": att.get("data_url", "")}}
                )
            self.history.append({"role": "user", "content": content})
            names = ", ".join(a.get("name", "image") for a in attachments)
            self.history.append(
                {"role": "user", "content": f"(the user attached image(s): {names} — inspect them and factor them into this task)"}
            )
        else:
            self.history.append({"role": "user", "content": user_text})
        self._current_task_text = user_text
        self._busy = True
        try:
            return self._run_turn_inner()
        finally:
            self._busy = False

    def _run_turn_inner(self) -> str:
        final_text = ""
        self._tool_calls = 0
        self._continues_used = 0
        self._last_action_key = ""
        self._last_action_error_count = 0
        # NOTE: budgets are applied in __init__ / on_effort_changed — not
        # here, so manual overrides (agent.max_steps = N) survive a turn.

        system_prompt = prompts.build_system_prompt(
            registry.schemas(), self._context_block(), mode=self.mode,
            skills_block=self._skills_block(),
            design_block=self._design_block(),
        )

        # --- plan mode: force read-only research -----------------------
        if self.mode == "plan":
            self.history.append(
                {"role": "user", "content": prompts.build_plan_instruction()}
            )

        while True:
            # --- live interrupt (/skip or ctrl+c from the REPL) ---------
            if self._check_interrupt():
                self.ui.render_warning("task interrupted — queue stays live")
                break

            # --- cap checks -------------------------------------------
            if self.step >= self.max_steps or self._tool_calls >= self._tool_cap:
                if self._continues_used < self._max_continues:
                    self._continues_used += 1
                    self.ui.render_info(
                        f"reached {self.max_steps}-step checkpoint — continuing "
                        f"({self._continues_used}/{self._max_continues})…"
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
            except KeyboardInterrupt:
                # ctrl+c mid-stream: stop this turn cleanly, keep history.
                self._flush_stream_buffer(ui_buffer)
                self.history.append({"role": "assistant", "content": "".join(ui_buffer)[:4000] or "(interrupted)"})
                self.history.append({"role": "user", "content": "(user interrupted — stop and wait)"})
                self.ui.render_warning("interrupted — you can type a new instruction")
                if self.session_id:
                    self._autosave()
                return "(interrupted by user)"

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
                # --- anti-loop guard -----------------------------------
                key = f"{turn.action.tool}:{json.dumps(turn.action.args, sort_keys=True)[:400]}"
                if key == self._last_action_key:
                    self._last_action_error_count += 1
                else:
                    self._last_action_key = key
                    self._last_action_error_count = 0

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

                # Same action failing repeatedly → stop the loop. This is
                # the auto-mode runaway fix: an identical action + identical
                # args that errors again can never succeed; break cleanly so
                # the user keeps the conversation and can redirect.
                if is_err and self._last_action_error_count >= 2:
                    self.ui.render_warning(
                        "the same action failed 3× in a row — stopping this turn "
                        "to avoid a loop. Progress is preserved; try a different "
                        "instruction or /effort deep."
                    )
                    break

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
        self._log_activity(action.tool, action.args, result, is_err)
        return result, is_err

    def _log_activity(self, tool: str, args: Dict[str, Any], result: str, is_err: bool) -> None:
        """Record what claume physically did, for /sessions activity display."""
        try:
            from . import activity

            kind = "tool"
            target = ""
            if tool in ("write_file", "patch_file", "delete_path", "make_directory"):
                kind = "file"
                target = str(args.get("path", ""))
            elif tool == "execute_command":
                kind = "command"
                target = str(args.get("command", ""))[:80]
            elif tool.startswith("mcp_"):
                kind = "mcp"
                target = tool
            elif tool in ("git_clone", "git_commit", "git_status"):
                kind = "git"
                target = tool
            elif tool in ("web_search", "fetch_url"):
                kind = "web"
                target = str(args.get("query") or args.get("url", ""))[:80]
            elif tool.startswith("webstudio_"):
                kind = "design"
                target = str(args.get("family") or args.get("url") or args.get("target", ""))[:80]
            elif tool in ("read_file", "list_directory", "tree_view", "search_text"):
                kind = "read"
                target = str(args.get("path") or args.get("pattern", ""))[:80]
            activity.record(
                self.session_id or "", kind, tool=tool, target=target,
                ok=not is_err, detail=result[:120],
            )
        except Exception:
            pass

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
        results = subagents_run_swarm(self.workspace, tasks, ui=self.ui)
        merged = subagents_combine(results, self.workspace)
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
        self._interrupt_event.clear()

    def set_mode(self, mode: str) -> None:
        if mode in ("manual", "accept", "plan", "auto"):
            self.mode = mode
            self.cfg.set("mode", mode)


# Late imports (circular-import safe)
def subagents_run_swarm(workspace: Path, tasks, ui=None):
    from . import subagents

    return subagents.run_swarm(workspace, tasks, ui=ui)


def subagents_combine(results, workspace: Path) -> str:
    from . import subagents

    return subagents.combine_results(results, workspace)
