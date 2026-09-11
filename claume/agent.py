"""ReAct agent loop for claume-code.

Each user turn:
  1. Build message history + system prompt (with tool schemas + context).
  2. Ask the LLM (via the free-claume proxy or another provider).
  3. Parse the strict JSON envelope (thought / action / final).
  4. Execute the action (with confirmation for risky tools).
  5. Feed the observation back and repeat until 'final' or step cap.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import config, llm, parser, prompts, security
from .tools import registry

ConfirmFn = Callable[[str, str], bool]  # (title, detail) -> bool


class Agent:
    def __init__(
        self,
        workspace: Path,
        ui: Any,
        confirm_fn: ConfirmFn,
        auto_mode: Optional[bool] = None,
    ) -> None:
        self.workspace = workspace
        self.ui = ui
        self.confirm_fn = confirm_fn
        self.cfg = config.Config()
        self.auto_mode = self.cfg.auto_mode if auto_mode is None else auto_mode
        self.history: List[Dict[str, str]] = []
        self.step = 0
        self.max_steps = int(self.cfg.get("max_steps", 24))
        self._tool_calls = 0
        self._tool_cap = int(self.cfg.get("max_tool_calls_per_turn", 40))
        self._secret_cache: List[str] = []
        self._fail_streak = 0

    # ------------------------------------------------------------------
    # Context
    # ------------------------------------------------------------------
    def _context_block(self) -> str:
        return prompts.build_context_block(
            str(self.workspace), os.name, self.cfg.model
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
    # One full user turn (multi-step ReAct)
    # ------------------------------------------------------------------
    def run_turn(self, user_text: str) -> str:
        self.history.append({"role": "user", "content": user_text})
        final_text = ""
        self._tool_calls = 0

        system_prompt = prompts.build_system_prompt(
            registry.schemas(), self._context_block()
        )

        while self.step < self.max_steps and self._tool_calls < self._tool_cap:
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
                if self._fail_streak >= 2:
                    # Feed the malformed output back so the model can fix it.
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
                    continue
                continue

            self._fail_streak = 0

            if turn.thought:
                self.ui.render_thought(turn.thought)

            if turn.final is not None:
                self.history.append({"role": "assistant", "content": reply[:4000]})
                final_text = turn.final
                break

            if turn.action:
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

        else:
            if self.step >= self.max_steps:
                self.ui.render_warning("step limit reached — ask me to continue if needed")

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

        needs = tool.dangerous or (tool.needs_confirm and tool.needs_confirm(action.args))
        if needs and not self.auto_mode:
            verdict = security.classify_command(str(action.args.get("command", "")))
            title = action.tool
            detail = str(action.args.get("command") or action.args.get("path") or action.args)
            if verdict.level == "destructive":
                self.ui.render_warning(f"DESTRUCTIVE: {detail}")
            ok = self.confirm_fn(title, detail)
            if not ok:
                return "user declined this action", False

        result, is_err = registry.execute(self.workspace, action.tool, action.args)
        result = security.redact_secrets(result, self._secrets())
        return result, is_err

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
