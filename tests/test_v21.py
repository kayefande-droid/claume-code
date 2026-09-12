"""Tests for claume v2.1: voice config, skills manager, named sessions,
MCP enable/disable, effort budgets, anti-loop guard, thinking panel.

All hermetic: no network, no spawned servers, throwaway config dir.
"""
import io
import json
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


class TestVoiceConfig(_IsolatedConfigMixin, unittest.TestCase):
    def test_defaults(self):
        from claume import voice

        self.assertFalse(voice.enabled())
        self.assertEqual(voice.accent(), "male-british")

    def test_enable_and_accent(self):
        from claume import voice

        cfg = config.Config()
        cfg.set("voice_enabled", True)
        cfg.set("voice_accent", "female-british")
        self.assertTrue(voice.enabled())
        self.assertEqual(voice.accent(), "female-british")

    def test_voice_pick_prefers_british_gender(self):
        from claume.voice import _pick_voice_from_names

        names = ["Microsoft David Desktop", "Microsoft Zira Desktop", "Microsoft George", "Microsoft Hazel"]
        self.assertEqual(_pick_voice_from_names(names, "male-british"), "Microsoft George")
        self.assertEqual(_pick_voice_from_names(names, "female-british"), "Microsoft Hazel")
        # non-british fallback picks by gender only
        self.assertEqual(_pick_voice_from_names(names[:2], "female-british"), "Microsoft Zira Desktop")
        # unknown voices: first name wins as last resort
        self.assertEqual(_pick_voice_from_names(["Weird Voice"], "male-british"), "Weird Voice")

    def test_speak_disabled_is_noop(self):
        from claume import voice

        self.assertFalse(voice.speak("hello"))

    def test_speak_cleans_markdown(self):
        from claume.voice import _clean_for_speech

        cleaned = _clean_for_speech("```python\ncode()\n``` and **bold** [link](http://x)")
        self.assertNotIn("```", cleaned)
        self.assertIn("bold", cleaned)


class TestSkillsManager(_IsolatedConfigMixin, unittest.TestCase):
    def _make_skill(self, name="demo-skill", with_scripts=False):
        root = config.skills_dir() / name
        root.mkdir(parents=True, exist_ok=True)
        (root / "SKILL.md").write_text(
            "# Demo Skill\n\nUse pixel-perfect design. Always test.\n", encoding="utf-8"
        )
        if with_scripts:
            (root / "scripts").mkdir(exist_ok=True)
            (root / "scripts" / "helper.py").write_text("print('hi')\n", encoding="utf-8")
        return root

    def test_index_and_list(self):
        from claume import skills as sk

        self._make_skill(with_scripts=True)
        items = sk.list_skills()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["name"], "demo-skill")
        self.assertFalse(items[0]["active"])
        self.assertGreaterEqual(items[0]["docs"], 1)
        self.assertGreaterEqual(items[0]["scripts"], 1)

    def test_activate_and_inject(self):
        from claume import skills as sk

        self._make_skill()
        self.assertTrue(sk.set_active("demo-skill", True))
        block = sk.active_instructions()
        self.assertIn("Active skills", block)
        self.assertIn("Demo Skill", block)
        # inactive → not injected
        sk.set_active("demo-skill", False)
        self.assertEqual(sk.active_instructions(), "")

    def test_skill_all(self):
        from claume import skills as sk

        self._make_skill("a")
        self._make_skill("b")
        self.assertEqual(sk.set_all_active(True), 2)
        items = sk.list_skills()
        self.assertTrue(all(s["active"] for s in items))
        self.assertEqual(sk.set_all_active(False), 2)
        self.assertFalse(any(s["active"] for s in sk.list_skills()))

    def test_single_skill_instructions(self):
        from claume import skills as sk

        self._make_skill()
        text = sk.skill_instructions("demo-skill")
        self.assertIn("Demo Skill", text)
        self.assertEqual(sk.skill_instructions("missing"), "")

    def test_run_script(self):
        from claume import skills as sk

        self._make_skill("scr", with_scripts=True)
        out, is_err = sk.run_script("scr", "helper.py", [])
        self.assertFalse(is_err)
        self.assertIn("hi", out)

    def test_run_script_missing(self):
        from claume import skills as sk

        self._make_skill("noscripts")
        out, is_err = sk.run_script("noscripts", "nope.py", [])
        self.assertTrue(is_err)

    def test_remove(self):
        from claume import skills as sk

        self._make_skill()
        self.assertTrue(sk.remove_skill("demo-skill"))
        self.assertFalse(sk.remove_skill("demo-skill"))


class TestNamedSessions(_IsolatedConfigMixin, unittest.TestCase):
    def test_project_defaults_to_cwd_name(self):
        sid = sessions.start_new()
        data = sessions.load_session(sid)
        self.assertTrue(data["project"])

    def test_explicit_project(self):
        sid = sessions.start_new(project="my-app")
        data = sessions.load_session(sid)
        self.assertEqual(data["project"], "my-app")

    def test_rename(self):
        sid = sessions.start_new(project="old")
        self.assertTrue(sessions.rename_session(sid, project="newproj", name="My Cool Name"))
        data = sessions.load_session(sid)
        self.assertEqual(data["project"], "newproj")
        self.assertEqual(data["name"], "My Cool Name")

    def test_list_includes_project_and_when(self):
        sid = sessions.start_new(project="listme")
        entries = sessions.list_sessions()
        entry = next(e for e in entries if e["id"] == sid)
        self.assertEqual(entry["project"], "listme")
        self.assertIn("when", entry)

    def test_rename_missing(self):
        self.assertFalse(sessions.rename_session("ghost", project="x"))


class TestMCPEnableDisable(_IsolatedConfigMixin, unittest.TestCase):
    def test_set_enabled_roundtrip(self):
        from claume import mcp as mcpmod

        cfg = config.Config()
        cfg.set("mcp_servers", {"srv": {"command": "x", "enabled": True}})
        self.assertTrue(mcpmod.set_enabled("srv", False))
        # fresh Config: set_enabled writes through to disk
        self.assertFalse(config.Config().get("mcp_servers.srv.enabled"))
        self.assertTrue(mcpmod.set_enabled("srv", True))
        self.assertTrue(config.Config().get("mcp_servers.srv.enabled"))

    def test_set_enabled_missing(self):
        from claume import mcp as mcpmod

        self.assertFalse(mcpmod.set_enabled("ghost", True))

    def test_disabled_servers_excluded_from_active_map(self):
        from claume import mcp as mcpmod

        cfg = config.Config()
        cfg.set("mcp_servers", {
            "on1": {"command": "x", "enabled": True},
            "off1": {"command": "y", "enabled": False},
        })
        active = mcpmod._servers_from_config()
        self.assertIn("on1", active)
        self.assertNotIn("off1", active)

    def test_list_all_tools_marks_disabled(self):
        from claume import mcp as mcpmod

        cfg = config.Config()
        cfg.set("mcp_servers", {"off1": {"command": "y", "enabled": False}})
        tools = mcpmod.list_all_tools()
        self.assertEqual(tools["off1"], ["<disabled>"])


class TestEffortBudgets(unittest.TestCase):
    def test_budget_table(self):
        from claume.agent import EFFORT_BUDGETS

        self.assertEqual(EFFORT_BUDGETS["fast"][0], 12)
        self.assertEqual(EFFORT_BUDGETS["balanced"][0], 24)
        self.assertEqual(EFFORT_BUDGETS["deep"][0], 48)
        self.assertEqual(EFFORT_BUDGETS["ultra"][0], 90)

    def test_agent_applies_budget(self):
        from claume.agent import Agent

        class FakeUI:
            quiet = True

            def __getattr__(self, name):
                raise AttributeError(name)

        agent = Agent(workspace=Path("."), ui=FakeUI(), confirm_fn=lambda t, d: True)
        self.assertEqual(agent.max_steps, 24)  # balanced default

    def test_effort_property_validates(self):
        cfg = config.Config()
        cfg.set("effort", "bogus")
        self.assertEqual(cfg.effort, "balanced")


class TestAntiLoopGuard(_IsolatedConfigMixin, unittest.TestCase):
    def _fake_ui(self):
        class FakeUI:
            quiet = True

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

    def test_repeated_failing_action_breaks(self):
        from claume.agent import Agent
        from claume import llm

        calls = {"n": 0}

        def fake_stream(messages, on_token=None, **kw):
            calls["n"] += 1
            return '{"thought":"s","action":{"tool":"read_file","args":{"path":"missing.txt"}}}'

        agent = Agent(workspace=Path("."), ui=self._fake_ui(), confirm_fn=lambda t, d: True)
        agent.max_steps = 30
        with patch.object(llm, "stream_chat", fake_stream):
            agent.run_turn("try to read a missing file forever")
        # without the guard this would loop to max_steps; with it, much fewer
        self.assertLess(calls["n"], 15)


class TestMCPStatusInContext(_IsolatedConfigMixin, unittest.TestCase):
    def test_mcp_status_lists_servers(self):
        status = prompts.build_mcp_status({
            "uidiscovery-21st": {"command": "npx", "enabled": True, "description": "21st.dev blocks"},
            "off": {"enabled": False},
        })
        self.assertIn("uidiscovery-21st", status)
        self.assertIn("disabled", status)
        self.assertIn("claume", status)

    def test_mcp_status_empty_when_no_servers(self):
        self.assertEqual(prompts.build_mcp_status({}), "")

    def test_context_includes_mcp_status(self):
        block = prompts.build_context_block("cwd", "nt", "model", mcp_status="- MCP servers: x")
        self.assertIn("MCP servers", block)

    def test_identity_never_claude(self):
        from claume import prompts as p

        sp = p.build_system_prompt("tools", "ctx", mode="manual")
        self.assertIn("You are claume-code", sp)
        self.assertIn("NOT Claude", sp)
        self.assertIn("never claude", sp)


class TestThinkingPanel(unittest.TestCase):
    def test_lifecycle(self):
        from claume.ui import ThinkingPanel

        panel = ThinkingPanel()
        panel.begin("weighing options")
        panel.tick(0)
        panel.set_words("final thought")
        panel.end()
        # after end, begin works again (no-op in non-tty, must not raise)
        panel.begin("again")
        panel.end()

    def test_noop_when_never_begun(self):
        from claume.ui import ThinkingPanel

        panel = ThinkingPanel()
        panel.tick(0)  # must not raise
        panel.end()

    def test_skills_block_in_system_prompt(self):
        from claume import prompts as p

        sp = p.build_system_prompt("tools", "ctx", mode="manual", skills_block="## Active skills")
        self.assertIn("## Active skills", sp)


if __name__ == "__main__":
    unittest.main()
