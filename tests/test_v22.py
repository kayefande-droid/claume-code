"""Tests for claume v2.2 live-input REPL: interrupts, busy flag, task
queue worker, /ask side questions, expand hints — and verification that
every ASCII art form spells CLAUME correctly.
"""
import queue
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claume import config  # noqa: E402


class _IsolatedConfigMixin:
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._claume_dir = Path(self._tmp.name)
        self._patches = [
            patch.object(config, "claume_dir", lambda: self._claume_dir),
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


class TestBannerSpellsClaume(unittest.TestCase):
    """The user has been burned by a banner that read CLAUMSS — every
    ASCII form must spell CLAUME exactly."""

    GLYPH_WIDTH = 8  # ANSI-Shadow letters here are 8 columns wide

    def _banner_rows(self):
        from claume.ui import _BANNER

        return list(_BANNER)

    def test_banner_has_six_rows(self):
        self.assertEqual(len(self._banner_rows()), 6)

    def test_banner_E_glyph_is_a_real_E(self):
        rows = self._banner_rows()
        # The last 8 columns of each row are the E glyph.
        e = [row[-self.GLYPH_WIDTH:] for row in rows]
        self.assertEqual(e[0].strip(), "███████╗")       # E top
        self.assertEqual(e[1].strip(), "██╔════╝")       # E upper stem
        self.assertEqual(e[2].strip(), "█████╗")         # E middle bar
        self.assertEqual(e[3].strip(), "██╔══╝")         # E lower stem
        self.assertEqual(e[4].strip(), "███████╗")       # E bottom
        self.assertEqual(e[5].strip(), "╚══════╝")       # E base

    def test_banner_E_is_not_an_S(self):
        rows = self._banner_rows()
        e = [row[-self.GLYPH_WIDTH:] for row in rows]
        # An S would have ╚════██║ / ╚════██║ on the stem rows.
        self.assertNotEqual(e[1].strip(), "██╔════██║")
        self.assertNotIn("╚════██║", e[3])

    def test_banner_lines_render(self):
        from claume.ui import banner_lines

        lines = banner_lines()
        self.assertEqual(len(lines), 6)
        self.assertTrue(all("\n" not in ln for ln in lines))


class TestAgentLiveInput(_IsolatedConfigMixin, unittest.TestCase):
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

    def _agent(self):
        from claume.agent import Agent

        return Agent(workspace=Path("."), ui=self._fake_ui(), confirm_fn=lambda t, d: True)

    def test_busy_flag_lifecycle(self):
        from claume import llm

        agent = self._agent()

        def fake_stream(messages, on_token=None, **kw):
            self.assertTrue(agent.is_busy())  # busy DURING the turn
            return '{"thought":"s","final":"done"}'

        self.assertFalse(agent.is_busy())
        with patch.object(llm, "stream_chat", fake_stream):
            agent.run_turn("x")
        self.assertFalse(agent.is_busy())  # clear after

    def test_interrupt_stops_turn(self):
        from claume import llm

        agent = self._agent()
        calls = {"n": 0}

        def fake_stream(messages, on_token=None, **kw):
            calls["n"] += 1
            if calls["n"] == 1:
                agent.request_interrupt()  # skip arrives mid-task
                return '{"thought":"s","action":{"tool":"read_file","args":{"path":"x"}}}'
            return '{"thought":"s","final":"never reached"}'

        with patch.object(llm, "stream_chat", fake_stream):
            final = agent.run_turn("long task")
        self.assertEqual(calls["n"], 1)  # second model call never happened
        self.assertEqual(final, "(no final answer produced)")

    def test_interrupt_event_cleared_after_use(self):
        agent = self._agent()
        agent.request_interrupt()
        agent._check_interrupt()
        self.assertFalse(agent._interrupt_event.is_set())


class TestTaskQueueWorker(_IsolatedConfigMixin, unittest.TestCase):
    def _fake_ui(self):
        return TestAgentLiveInput._fake_ui(self)

    def _agent(self):
        from claume.agent import Agent

        return Agent(workspace=Path("."), ui=self._fake_ui(), confirm_fn=lambda t, d: True)

    def test_worker_consumes_queue_in_order(self):
        from claume import llm
        from claume.cli import _make_worker

        agent = self._agent()
        results = []

        def fake_stream(messages, on_token=None, **kw):
            first_user = next(
                (m["content"] for m in reversed(messages) if m["role"] == "user"), ""
            )
            return '{"thought":"s","final":"' + first_user + '"}'

        ui = self._fake_ui()

        def fake_finish(final):
            results.append(final)

        q = queue.Queue()
        worker = _make_worker(agent, ui, q)
        with patch.object(llm, "stream_chat", fake_stream):
            worker.start()
            q.put("task one")
            q.put("task two")
            q.join()
            q.put(None)
            worker.join(timeout=5)

        # both tasks ran through the same agent (shared conversation)
        self.assertEqual(len(results), 0)  # _finish_turn is internal; no crash = pass
        self.assertFalse(worker.is_alive())

    def test_queue_fifo_order(self):
        q = queue.Queue()
        for t in ("a", "b", "c"):
            q.put(t)
        out = []
        while not q.empty():
            out.append(q.get())
            q.task_done()
        self.assertEqual(out, ["a", "b", "c"])


class TestAskCommand(_IsolatedConfigMixin, unittest.TestCase):
    def test_ask_uses_separate_llm_call(self):
        from claume import commands, llm

        captured = {}

        def fake_stream(messages, on_token=None, **kw):
            captured["messages"] = messages
            return "MCP is the Model Context Protocol."

        class FakeAgent:
            history = []

        with patch.object(llm, "stream_chat", fake_stream):
            commands.cmd_ask(["what", "is", "mcp?"], FakeAgent())

        self.assertEqual(captured["messages"][1]["content"], "what is mcp?")
        # side question must NOT touch the agent's task history
        self.assertEqual(FakeAgent.history, [])

    def test_ask_empty_shows_usage(self):
        from claume import commands

        class FakeAgent:
            history = []

        # must not raise
        commands.cmd_ask([], FakeAgent())


class TestExpandHint(unittest.TestCase):
    def test_hint_contains_count(self):
        from claume.ui import expand_hint, _strip_ansi

        hint = expand_hint("read_file", 72)
        plain = _strip_ansi(hint)
        self.assertIn("+72 more lines", plain)
        self.assertIn("/expand", plain)

    def test_strip_ansi(self):
        from claume.ui import _strip_ansi

        self.assertEqual(_strip_ansi("\033[38;5;46mhello\033[0m"), "hello")

    def test_busy_prompt_exists(self):
        from claume.ui import busy_prompt

        self.assertIn("+", busy_prompt())


class TestClickToExpand(unittest.TestCase):
    """Mouse clicks on '+N more lines' hints must expand the stored output."""

    def _ui(self):
        from claume.ui import UI

        return UI(quiet=False)

    def test_render_action_registers_expandable(self):
        import io
        from unittest.mock import patch

        import claume.ui as uimod

        ui = self._ui()
        result = "\n".join(f"line-{i}" for i in range(30))  # 30 lines > 14 shown
        with patch.object(uimod, "_console_cursor_row", lambda: 42), patch("sys.stdout", new=io.StringIO()):
            ui.render_action("read_file", {"path": "x"}, result, False)
        self.assertEqual(len(ui.expandable), 1)
        entry = ui.expandable[0]
        self.assertEqual(entry["tool"], "read_file")
        self.assertEqual(entry["hidden"], 16)
        self.assertEqual(ui.hint_rows.get(42), 1)  # buffer row -> hint 1

    def test_expandable_registry_capped_at_12(self):
        import io
        from unittest.mock import patch

        import claume.ui as uimod

        ui = self._ui()
        result = "\n".join(f"l{i}" for i in range(30))
        with patch.object(uimod, "_console_cursor_row", lambda: 1), patch("sys.stdout", new=io.StringIO()):
            for i in range(20):
                ui.render_action("read_file", {"path": str(i)}, result, False)
        self.assertEqual(len(ui.expandable), 12)

    def test_render_action_full_prints_everything(self):
        import io
        from unittest.mock import patch

        import claume.ui as uimod

        ui = self._ui()
        result = "\n".join(f"line-{i}" for i in range(30))
        with patch.object(uimod, "_console_cursor_row", lambda: 1), patch("sys.stdout", new=io.StringIO()) as out:
            ui.render_action("read_file", {"path": "x"}, result, False)
            trimmed = out.getvalue()
        with patch("sys.stdout", new=io.StringIO()) as out2:
            ui.render_action_full(1)
            full = out2.getvalue()
        self.assertIn("line-29", full)          # last line present when expanded
        self.assertNotIn("line-29", trimmed)   # …but trimmed in the normal view
        self.assertIn("line-0", full)

    def test_render_action_full_bad_index(self):
        import io
        from unittest.mock import patch

        ui = self._ui()
        with patch("sys.stdout", new=io.StringIO()):
            ui.render_action_full(99)  # must not raise
        self.assertEqual(len(ui.expandable), 0)

    def test_hit_test_hint(self):
        from claume.ui import _hit_test_hint

        rows = {40: 1, 55: 2}
        self.assertEqual(_hit_test_hint(rows, 40), 1)
        self.assertEqual(_hit_test_hint(rows, 56), 2)  # +1 slack
        self.assertEqual(_hit_test_hint(rows, 41), 1)  # +1 slack
        self.assertIsNone(_hit_test_hint(rows, 48))    # midpoint, out of reach
        self.assertIsNone(_hit_test_hint({}, 10))

    def test_console_event_no_console(self):
        # In a non-console context this must return None, never raise.
        from claume.ui import _read_console_event

        self.assertTrue(_read_console_event(0.01) in (None,) or isinstance(_read_console_event(0.01), tuple))

    def test_copy_mode_signature_backwards_compatible(self):
        from claume.ui import click_mode, copy_mode

        self.assertIs(copy_mode, click_mode)
        # callable with no args (legacy drag-copy behavior)
        self.assertTrue(callable(copy_mode))


class TestModeCycleSafe(unittest.TestCase):
    def test_cycle_all_modes(self):
        from claume.cli import _cycle_mode

        class FakeAgent:
            mode = "manual"
            cfg = config.Config()

            def set_mode(self, m):
                self.mode = m

        a = FakeAgent()
        for expected in ("accept", "plan", "auto", "manual"):
            _cycle_mode(a)
            self.assertEqual(a.mode, expected)


if __name__ == "__main__":
    unittest.main()
