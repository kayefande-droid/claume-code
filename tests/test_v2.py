"""Tests for claume v2 features: sessions, modes, themes, subagents, agent loop."""
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claume import config, prompts, sessions  # noqa: E402


class TestSessions(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._patcher = patch.object(config, "sessions_dir", return_value=Path(self._tmp.name))
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        self._tmp.cleanup()

    def test_roundtrip(self):
        sid = sessions.start_new()
        history = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        sessions.save_session(sid, history, meta={"mode": "auto"})
        data = sessions.load_session(sid)
        self.assertIsNotNone(data)
        self.assertEqual(len(data["messages"]), 2)
        self.assertEqual(data["meta"]["mode"], "auto")

    def test_list_and_latest(self):
        sid = sessions.start_new()
        sessions.save_session(sid, [{"role": "user", "content": "find me"}])
        entries = sessions.list_sessions()
        self.assertTrue(any(e["id"] == sid for e in entries))
        self.assertEqual(sessions.latest_session_id(), sid)

    def test_sanitize_truncates(self):
        sid = "t-" + sessions.new_session_id()
        huge = "x" * (sessions.MAX_MSG_CONTENT + 5000)
        sessions.save_session(sid, [{"role": "user", "content": huge}])
        data = sessions.load_session(sid)
        self.assertLessEqual(len(data["messages"][0]["content"]), sessions.MAX_MSG_CONTENT)

    def test_load_missing(self):
        self.assertIsNone(sessions.load_session("nope-123"))


class TestModes(unittest.TestCase):
    def test_mode_validation(self):
        cfg = config.Config()
        cfg.set("mode", "bogus")
        self.assertEqual(cfg.mode, "manual")
        cfg.set("mode", "plan")
        self.assertEqual(cfg.mode, "plan")
        cfg.set("mode", "manual")  # restore

    def test_legacy_auto_mode_migration(self):
        cfg = config.Config()
        cfg._data["auto_mode"] = True
        cfg._data["mode"] = "manual"
        cfg.migrate_legacy_flags()
        self.assertEqual(cfg.mode, "auto")
        cfg.set("mode", "manual")  # restore

    def test_mode_prompts(self):
        for mode, marker in [
            ("plan", "PLAN MODE ACTIVE"),
            ("accept", "ACCEPT-EDITS MODE ACTIVE"),
            ("auto", "AUTO MODE ACTIVE"),
            ("manual", "MANUAL MODE ACTIVE"),
        ]:
            sp = prompts.build_system_prompt("tools", "ctx", mode=mode)
            self.assertIn(marker, sp)


class TestThemes(unittest.TestCase):
    def test_all_themes_switch(self):
        from claume import ui as u

        for name in u.THEMES:
            self.assertTrue(u.set_theme(name))
        self.assertFalse(u.set_theme("nope"))
        u.set_theme("nvidia-green")

    def test_banner_spells_claume(self):
        from claume.ui import _BANNER

        # row 1 has the C L A U M E tops: C, L, A, U, M, E
        self.assertIn("███████╗███████╗", _BANNER[0])  # A and E tops


class TestMascot(unittest.TestCase):
    def test_frames_exist(self):
        from claume.ui import MASCOT_FRAMES, MASCOT_MOODS

        self.assertGreaterEqual(len(MASCOT_FRAMES), 3)
        self.assertIn("think", MASCOT_MOODS)

    def test_render_contains_label(self):
        import claume.ui as u

        class FakeOut:
            def isatty(self):
                return True

        orig = u.sys.stdout
        u.sys.stdout = FakeOut()
        try:
            m = u.Mascot(enabled=True)
            out = m.render(mood="think", note="x")
        finally:
            u.sys.stdout = orig
        self.assertIn("claume", out)


class TestClipboard(unittest.TestCase):
    def test_copy_returns_bool(self):
        from claume.ui import copy_to_clipboard

        result = copy_to_clipboard("test string")
        self.assertIsInstance(result, bool)


class TestAgentAutoContinue(unittest.TestCase):
    def _fake_ui(self):
        class FakeUI:
            quiet = True
            expand_output = False

            def __getattr__(self, name):
                raise AttributeError(name)

            def render_thought(self, t):
                pass

            def render_action(self, *a):
                pass

            def render_error(self, m):
                pass

            def render_warning(self, m):
                pass

            def render_info(self, m):
                pass

            def render_success(self, m):
                pass

            def stream_token(self, *a):
                pass

            def end_stream(self, b):
                b.clear()

            def confirm(self, t, d):
                return True

        return FakeUI()

    def test_step_cap_does_not_kill_task(self):
        from claume.agent import Agent
        from claume import llm

        def fake_stream(messages, on_token=None, **kw):
            last = messages[-1]["content"]
            if "checkpoint" in last:
                return '{"thought":"wrap","final":"done via continue"}'
            return '{"thought":"s","action":{"tool":"read_file","args":{"path":"x"}}}'

        agent = Agent(
            workspace=Path("."), ui=self._fake_ui(), confirm_fn=lambda t, d: True
        )
        agent.max_steps = 2
        agent.history = []
        with patch.object(llm, "stream_chat", fake_stream):
            final = agent.run_turn("long task")
        self.assertEqual(final, "done via continue")

    def test_step_resets_between_turns(self):
        from claume.agent import Agent
        from claume import llm

        def fake_stream(messages, on_token=None, **kw):
            return '{"thought":"s","final":"quick answer"}'

        agent = Agent(
            workspace=Path("."), ui=self._fake_ui(), confirm_fn=lambda t, d: True
        )
        agent.max_steps = 3
        agent.history = []
        with patch.object(llm, "stream_chat", fake_stream):
            agent.run_turn("first")
            agent.step = 50  # simulate a stuck counter from an old bug
            agent.history.clear()
            final = agent.run_turn("second")
        self.assertEqual(final, "quick answer")

    def test_plan_mode_blocks_writes(self):
        from claume.agent import Agent
        from claume.parser import Action

        agent = Agent(
            workspace=Path("."), ui=self._fake_ui(), confirm_fn=lambda t, d: True
        )
        agent.mode = "plan"
        result, is_err = agent._execute_with_confirm(
            Action(tool="write_file", args={"path": "x", "content": "y"})
        )
        self.assertTrue(is_err)
        self.assertIn("plan mode", result.lower())


class TestSubagents(unittest.TestCase):
    def test_swarm_runs_and_merges(self):
        from claume import subagents

        def fake_stream(messages, on_token=None, **kw):
            first = messages[-1]["content"]
            if "alpha task" in first:
                return '{"thought":"a","final":"alpha done"}'
            return '{"thought":"b","final":"beta done"}'

        results = None
        with patch.object(subagents.llm, "stream_chat", fake_stream):
            results = subagents.run_swarm(
                Path("."), [{"name": "a1", "task": "alpha task"}, {"name": "b1", "task": "beta task"}], ui=None
            )
            merged = subagents.combine_results(results, Path("."))
        summaries = [r.summary for r in results]
        self.assertIn("alpha done", summaries)
        self.assertIn("beta done", summaries)
        self.assertTrue(merged)

    def test_result_dataclass(self):
        from claume.subagents import SubagentResult

        r = SubagentResult(name="x", task="y", error="boom")
        self.assertEqual(r.error, "boom")


class TestMCPPipeline(unittest.TestCase):
    def test_pipeline_degrades_gracefully(self):
        from claume import mcp

        with tempfile.TemporaryDirectory() as tmp:
            report, is_err = mcp.design_pipeline("a fancy hero", Path(tmp))
        self.assertFalse(is_err)
        self.assertIn("LINK SYSTEM", report)
        self.assertIn("BUILD DIRECTIVES", report)

    def test_disabled_server_raises(self):
        from claume import mcp

        srv = mcp.MCPServer("t", {"command": "x", "enabled": False})
        with self.assertRaises(mcp.MCPError):
            srv._rpc("m")


class TestLLMFallbackChain(unittest.TestCase):
    def test_chain_builds_from_config(self):
        from claume import llm

        cfg = config.Config()
        cfg.set("model_fallbacks", ["m/b", "m/c"])
        captured = {}

        class FakeResp:
            def readline(self):
                return b""

        def fake_urlopen(req, timeout=0, context=None):
            body = json.loads(req.data.decode())
            captured["models"] = captured.get("models", [])
            captured["models"].append(body["model"])
            raise __import__("urllib").error.HTTPError(
                req.full_url, 410, "Gone", {}, io.BytesIO(b"{}")
            )

        with patch.object(llm.urllib.request, "urlopen", fake_urlopen):
            with self.assertRaises(llm.LLMError):
                llm.stream_chat([{"role": "user", "content": "hi"}])
        cfg.set("model_fallbacks", [])  # restore
        # primary + 2 fallbacks should all have been attempted
        self.assertEqual(len(captured["models"]), 3)


if __name__ == "__main__":
    unittest.main()
