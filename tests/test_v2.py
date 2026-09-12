"""claume v2 feature tests: sessions, modes, themes, subagents, agent loop.

Everything here is HERMETIC: no real config file, no network, no MCP
spawns. The live MCP smoke test lives in TestMCPLiveConnectivity and is
skipped unless CLAUME_LIVE_MCP=1 is set (run tests/mcp_smoke_live.py
for the interactive version with output).
"""
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


class _IsolatedConfigMixin:
    """Point ~/.claume at a throwaway dir for the duration of the test."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._claume_dir = Path(self._tmp.name)

        def _fake_dir():
            return self._claume_dir

        self._patches = [
            patch.object(config, "claume_dir", _fake_dir),
            patch.object(config, "sessions_dir", lambda: self._claume_dir / "sessions"),
            patch.object(config, "config_path", lambda: self._claume_dir / "config.json"),
            patch.object(config, "skills_dir", lambda: self._claume_dir / "skills"),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self._tmp.cleanup()


class TestSessions(_IsolatedConfigMixin, unittest.TestCase):
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


class TestModes(_IsolatedConfigMixin, unittest.TestCase):
    def test_mode_validation(self):
        cfg = config.Config()
        cfg.set("mode", "bogus")
        self.assertEqual(cfg.mode, "manual")
        cfg.set("mode", "plan")
        self.assertEqual(cfg.mode, "plan")

    def test_legacy_auto_mode_migration(self):
        cfg = config.Config()
        cfg._data["auto_mode"] = True
        cfg._data["mode"] = "manual"
        cfg.migrate_legacy_flags()
        self.assertEqual(cfg.mode, "auto")

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

        # 6 rows, and the final glyph is a proper E (ANSI-Shadow):
        # top ███████╗ · mid-left ██╔════╝ · bottom ╚══════╝
        self.assertEqual(len(_BANNER), 6)
        self.assertTrue(_BANNER[0].rstrip().endswith("███████╗"))   # E top
        self.assertTrue(_BANNER[3].rstrip().endswith("██╔══╝"))     # E stem
        self.assertTrue(_BANNER[5].rstrip().endswith("╚══════╝"))   # E bottom
        # the old buggy glyphs (extra S column) must be gone
        self.assertNotIn("╚════██║╚════██║", _BANNER[3])


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


class TestAgentAutoContinue(_IsolatedConfigMixin, unittest.TestCase):
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


class TestSubagents(_IsolatedConfigMixin, unittest.TestCase):
    def test_swarm_runs_and_merges(self):
        from claume import subagents

        def fake_stream(messages, on_token=None, **kw):
            first = messages[-1]["content"]
            if "alpha task" in first:
                return '{"thought":"a","final":"alpha done"}'
            return '{"thought":"b","final":"beta done"}'

        with patch.object(subagents.llm, "stream_chat", fake_stream):
            results = subagents.run_swarm(
                Path("."),
                [{"name": "a1", "task": "alpha task"}, {"name": "b1", "task": "beta task"}],
                ui=None,
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
    """Hermetic MCP tests: no servers spawned, no network."""

    def test_pipeline_degrades_gracefully(self):
        from claume import mcp

        with patch.object(mcp, "_servers_from_config", return_value={}):
            report, is_err = mcp.design_pipeline("a fancy hero", Path("."))
        self.assertFalse(is_err)
        self.assertIn("LINK SYSTEM", report)
        self.assertIn("BUILD DIRECTIVES", report)

    def test_disabled_server_raises(self):
        from claume import mcp

        srv = mcp.MCPServer("t", {"command": "x", "enabled": False})
        with self.assertRaises(mcp.MCPError):
            srv._rpc("m")

    def test_preset_roundtrip(self):
        from claume import mcp

        self.assertIn("design", mcp.PRESETS)
        expected = {"uidiscovery-21st", "microinteractions-reactbits", "animation-motion", "atomic-shadcnspace"}
        self.assertTrue(expected.issubset(set(mcp.DESIGN_STACK)))


class TestMCPVaultKeyInjection(_IsolatedConfigMixin, unittest.TestCase):
    """The key contract: vaulted keys must reach the spawned server env."""

    def test_vault_key_reaches_spawn_env(self):
        from claume import keyvault, mcp

        keyvault.set_key("TEST_MCP_KEY", "test-secret-123456")
        config.Config().set("key_vault.TEST_MCP_KEY", True)

        srv = mcp.MCPServer("vaulted", {"command": "whatever", "needs_key": "TEST_MCP_KEY"})

        # Inspect the env that would be passed to Popen by intercepting it.
        captured = {}

        class FakeProc:
            def __init__(self):
                self.pid = 0
                self.stdin = io.StringIO()
                self.stdout = io.StringIO()
                self.stderr = io.StringIO()

            def poll(self):
                return 0

        def fake_popen(cmd_list, **kwargs):
            captured["env"] = kwargs.get("env", {})
            captured["cmd"] = cmd_list
            return FakeProc()

        with patch.object(mcp.subprocess, "Popen", fake_popen):
            srv._start()

        self.assertEqual(captured["env"].get("TEST_MCP_KEY"), "test-secret-123456")

    def test_placeholder_env_values_are_skipped(self):
        from claume import mcp

        srv = mcp.MCPServer(
            "placeholder",
            {"command": "x", "env": {"API_KEY_21ST": "<paste-your-21st-key>"}},
        )
        captured = {}

        class FakeProc:
            def __init__(self):
                self.pid = 0
                self.stdin = io.StringIO()
                self.stdout = io.StringIO()
                self.stderr = io.StringIO()

            def poll(self):
                return 0

        def fake_popen(cmd_list, **kwargs):
            captured["env"] = kwargs.get("env", {})
            return FakeProc()

        with patch.object(mcp.subprocess, "Popen", fake_popen):
            srv._start()

        self.assertNotIn("API_KEY_21ST", captured["env"])

    def test_auth_error_mentions_key_hint(self):
        from claume import mcp

        srv = mcp.MCPServer(
            "needsauth",
            {"command": "x", "needs_key": "SOME_KEY"},
        )

        def failing_rpc(method, params=None, timeout=0):
            raise mcp.MCPError("Not authenticated - your API key is missing")

        with patch.object(srv, "_rpc", failing_rpc):
            with self.assertRaises(mcp.MCPError) as ctx:
                srv.initialize()
        self.assertIn("/key SOME_KEY", str(ctx.exception))

    def test_generic_handshake_failure_returns_false(self):
        from claume import mcp

        srv = mcp.MCPServer("flaky", {"command": "x"})

        def failing_rpc(method, params=None, timeout=0):
            raise mcp.MCPError("timed out after 75s on initialize")

        with patch.object(srv, "_rpc", failing_rpc):
            self.assertFalse(srv.initialize())


class TestMCPLiveConnectivity(unittest.TestCase):
    """LIVE smoke: connects to all 4 design servers with vaulted keys.

    Opt-in:  CLAUME_LIVE_MCP=1 python -m unittest tests.test_v2.TestMCPLiveConnectivity -v
    Or just run:  python tests/mcp_smoke_live.py
    """

    EXPECTED_SERVERS = {
        "atomic-shadcnspace",
        "uidiscovery-21st",
        "animation-motion",
        "microinteractions-reactbits",
    }

    def setUp(self):
        if not os.environ.get("CLAUME_LIVE_MCP"):
            self.skipTest("live MCP test — set CLAUME_LIVE_MCP=1 (or run tests/mcp_smoke_live.py)")

    def test_all_four_design_servers_connect(self):
        from claume import mcp

        tools = mcp.list_all_tools()
        mcp.shutdown_all()

        missing = self.EXPECTED_SERVERS - set(tools)
        self.assertEqual(missing, set(), f"servers not in config: {missing}")

        for name in sorted(self.EXPECTED_SERVERS):
            tlist = tools.get(name, [])
            self.assertTrue(tlist, f"{name}: no tools listed")
            self.assertFalse(
                str(tlist[0]).startswith("<error"),
                f"{name}: {tlist[0][:160]}",
            )
            print(f"  OK {name}: {len(tlist)} tools")

    def test_link_pipeline_all_stages_pass(self):
        from claume import mcp

        report, is_err = mcp.design_pipeline("dashboard hero", Path("."))
        mcp.shutdown_all()
        self.assertFalse(is_err)
        self.assertIn("✓ atomic-shadcnspace", report)
        self.assertIn("✓ uidiscovery-21st", report)
        self.assertIn("✓ animation-motion", report)
        self.assertIn("✓ microinteractions-reactbits", report)


class TestLLMFallbackChain(_IsolatedConfigMixin, unittest.TestCase):
    def test_chain_builds_from_config(self):
        from claume import llm

        cfg = config.Config()
        cfg.set("model_fallbacks", ["m/b", "m/c"])
        captured = {}

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
        # primary + 2 fallbacks should all have been attempted
        self.assertEqual(len(captured["models"]), 3)


if __name__ == "__main__":
    unittest.main()
