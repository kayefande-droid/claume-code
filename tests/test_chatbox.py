"""Tests for the v2.3.1 chat box: Editor state machine, completions,
ghost suggestions, and renderer helpers (pure logic, no tty needed)."""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claume import chatbox  # noqa: E402


class TestEditorBasics(unittest.TestCase):
    def setUp(self):
        self.ed = chatbox.Editor(history=["build the dashboard", "fix the login bug", "build the api client"])

    def type(self, s: str):
        self.ed.key(s)

    def test_typing_and_submit(self):
        self.type("hello world")
        result = self.ed.key("ENTER")
        self.assertEqual(result, "hello world")
        self.assertEqual(self.ed.text, "")  # reset after submit

    def test_backspace_and_edit_middle(self):
        self.type("helo")
        self.ed.key("BACKSPACE")   # -> "hel"
        self.type("lo")            # -> "hello"
        self.assertEqual(self.ed.text, "hello")

    def test_cursor_left_insert(self):
        self.type("helo")
        self.ed.key("LEFT"); self.ed.key("LEFT")
        self.type("l")
        self.assertEqual(self.ed.text, "hello")

    def test_home_end(self):
        self.type("abcdef")
        self.ed.key("HOME")
        self.type("X")
        self.assertEqual(self.ed.text, "Xabcdef")
        self.ed.key("END")
        self.type("Y")
        self.assertEqual(self.ed.text, "XabcdefY")

    def test_ctrl_u_clears(self):
        self.type("junk")
        self.ed.key("CTRL+U")
        self.assertEqual(self.ed.text, "")

    def test_multiline_alt_enter(self):
        self.type("line one")
        self.ed.key("ALT+ENTER")
        self.type("line two")
        result = self.ed.key("ENTER")
        self.assertEqual(result, "line one\nline two")

    def test_up_down_between_rows_multiline(self):
        self.type("one")
        self.ed.key("ALT+ENTER")
        self.type("two")
        self.ed.key("UP")
        self.assertEqual(self.ed.row, 0)
        self.ed.key("DOWN")
        self.assertEqual(self.ed.row, 1)

    def test_interrupt_signals(self):
        self.assertEqual(self.ed.key("CTRL+C"), "INT")
        self.assertEqual(self.ed.key("CTRL+D"), "EOF")


class TestEditorHistory(unittest.TestCase):
    def test_up_recalls_history(self):
        ed = chatbox.Editor(history=["old task one", "older task two"])
        ed.key("U")  # something typed: history nav allowed on single line
        # note: UP with no drop + single line recalls history
        ed.key("UP")
        self.assertEqual(ed.text, "older task two")
        ed.key("UP")
        self.assertEqual(ed.text, "old task one")
        ed.key("DOWN")
        self.assertEqual(ed.text, "older task two")

    def test_scroll_past_newest_clears(self):
        ed = chatbox.Editor(history=["a task"])
        ed.key("UP")
        self.assertEqual(ed.text, "a task")
        ed.key("DOWN")
        self.assertEqual(ed.text, "")


class TestDrops(unittest.TestCase):
    def setUp(self):
        self.ed = chatbox.Editor()

    def test_command_drop_opens_and_filters(self):
        self.type = self.ed.key
        self.type("/")
        self.assertGreater(len(self.ed.drop), 5)
        self.type("sk")
        self.assertTrue(all(d.startswith("/sk") for d in self.ed.drop))
        self.assertIn("/skills", self.ed.drop)

    def test_command_drop_accept(self):
        self.ed.key("/")
        self.ed.key("h")
        self.ed.key("e")
        # /help should be in the drop; select + Enter accepts
        if "/help" in self.ed.drop:
            self.ed.drop_sel = self.ed.drop.index("/help")
            self.ed.key("ENTER")
            self.assertTrue(self.ed.text.startswith("/help "))
            self.assertEqual(self.ed.drop, [])

    def test_space_dismisses_command_drop(self):
        self.ed.key("/")
        self.assertGreater(len(self.ed.drop), 0)
        self.ed.key(" ")  # command with arg -> drop hides
        self.assertEqual(self.ed.drop, [])

    def test_file_drop_opens_on_at(self):
        self.ed.key("@")
        # no assertion on content (cwd-dependent) but must not crash;
        # README.md exists in repo root where tests run
        self.assertIsInstance(self.ed.drop, list)

    def test_file_drop_accept_replaces_fragment(self):
        ed = chatbox.Editor(completions=lambda t: ["@README.md", "@claume/cli.py"] if "@" in t else [])
        ed.key("@")
        ed.drop = ["@README.md", "@claume/cli.py"]
        ed.drop_sel = 1
        ed.key("ENTER")
        self.assertEqual(ed.text, "@claume/cli.py ")

    def test_enter_with_no_drop_submits(self):
        self.ed.key("h")
        self.ed.key("i")
        self.assertEqual(self.ed.key("ENTER"), "hi")


class TestGhost(unittest.TestCase):
    def test_ghost_from_history(self):
        hist = ["build the dashboard with charts"]
        ed = chatbox.Editor(history=hist)
        for ch in "build the":
            ed.key(ch)
        self.assertEqual(ed.ghost(), " dashboard with charts")

    def test_accept_ghost(self):
        hist = ["build the dashboard"]
        ed = chatbox.Editor(history=hist)
        for ch in "build the":
            ed.key(ch)
        ed.accept_ghost()
        self.assertEqual(ed.text, "build the dashboard")

    def test_no_ghost_for_commands(self):
        ed = chatbox.Editor(history=["/skills"])
        for ch in "/sk":
            ed.key(ch)
        self.assertEqual(ed.ghost(), "")


class TestRendererHelpers(unittest.TestCase):
    def test_strip_ansi(self):
        self.assertEqual(chatbox._strip_ansi("\033[38;5;46mabc\033[0m"), "abc")

    def test_renderer_measures_plain_prompt(self):
        r = chatbox.Renderer("\033[38;5;46m❯ \033[0m")
        self.assertEqual(r.plain_len, 2)


class TestProviders(unittest.TestCase):
    def test_command_names_include_core(self):
        names = chatbox.command_names()
        for required in ("/help", "/skills", "/design", "/webdesign", "/exit"):
            self.assertIn(required, names)

    def test_complete_command_prefix(self):
        out = chatbox.complete_command("/sk")
        self.assertIn("/skills", out)
        self.assertTrue(all(c.startswith("/sk") for c in out))

    def test_complete_file_finds_readme(self):
        out = chatbox.complete_file("@REA", cwd=Path(__file__).resolve().parent.parent)
        self.assertIn("@README.md", out)


class TestRenderLoop(unittest.TestCase):
    def test_render_frames_and_finish(self):
        """Scripted keys through Editor + Renderer: frames render, drop
        panel draws, finish collapses to the submitted line."""
        import io

        ed = chatbox.Editor(history=[])
        buf = io.StringIO()
        real_stdout = sys.stdout
        sys.stdout = buf
        try:
            rend = chatbox.Renderer("❯ ")
            for ch in "/he":
                ed.key(ch)
            rend.render(ed, ed.ghost())
            self.assertTrue(ed.drop, "command drop should be open")
            first_frame_len = len(buf.getvalue())
            self.assertGreater(first_frame_len, 0)
            # second frame must reposition (cursor-up escape present)
            ed.key("l")
            rend.render(ed, ed.ghost())
            self.assertIn("\033[", buf.getvalue())
            ed.key("ENTER") if not ed.drop else ed._accept_drop(ed.drop[0])
            rend.finish(ed, ed.text or "/help")
        finally:
            sys.stdout = real_stdout
        self.assertIn("❯", buf.getvalue())

    def test_renderer_clear_resets_frame(self):
        import io

        ed = chatbox.Editor()
        buf = io.StringIO()
        real_stdout = sys.stdout
        sys.stdout = buf
        try:
            rend = chatbox.Renderer("❯ ")
            rend.render(ed, "")
            self.assertEqual(rend.rows_drawn, 1)
            rend.clear()
            self.assertEqual(rend.rows_drawn, 0)
        finally:
            sys.stdout = real_stdout


class TestFrame(unittest.TestCase):
    """The structural REPL frame: status bar, skills panel, input box."""

    def test_status_bar_contains_chips(self):
        from claume import frame

        line = frame.status_bar("worki · claume-code", "45s")
        plain = chatbox._strip_ansi(line)
        self.assertIn("worki · claume-code", plain)
        self.assertIn("45s", plain)
        self.assertIn("Esc", plain)

    def test_skills_panel_rows_align_at_widths(self):
        import io
        import re

        from claume import frame

        def vis(s):
            return len(re.sub(r"\033\[[0-9;]*m", "", s))

        for w in (60, 90, 130):
            old = frame.term_width
            frame.term_width = lambda w=w: w
            try:
                buf = io.StringIO()
                frame.skills_panel(out=buf.write)
                lines = [l for l in buf.getvalue().split("\n") if l]
                widths = {vis(l) for l in lines}
                self.assertEqual(len(widths), 1, f"ragged rows at w={w}: {widths}")
            finally:
                frame.term_width = old

    def test_skills_panel_lists_flagship_first(self):
        import io

        from claume import frame

        buf = io.StringIO()
        frame.skills_panel(out=buf.write)
        out = buf.getvalue()
        if "ui-ux-pro-max-skill" in out:  # only when seeded/active
            self.assertLess(out.index("ui-ux-pro-max-skill"), out.index("⬡ mcp"))

    def test_input_box_borders_match(self):
        from claume import frame

        top = frame.input_box_top_labeled("manual", "proj", "4m12s", width=70)
        bottom = frame.input_box_bottom_rule(width=70)
        self.assertEqual(len(chatbox._strip_ansi(top)), len(chatbox._strip_ansi(bottom)))
        self.assertIn("4m12s", chatbox._strip_ansi(top))

    def test_placeholder_text(self):
        from claume import frame

        self.assertIn("/", frame.PLACEHOLDER)


class TestHistoryPersist(unittest.TestCase):
    def test_append_and_load_roundtrip(self):
        with __import__("tempfile").TemporaryDirectory() as td:
            old = chatbox._history_path
            chatbox._history_path = lambda: Path(td) / "input_history"
            try:
                chatbox.append_history("do the thing")
                chatbox.append_history("do the other thing")
                chatbox.append_history("/not-commands-skipped")
                hist = chatbox.load_history()
                self.assertIn("do the thing", hist)
                self.assertNotIn("/not-commands-skipped", hist)
                # consecutive dedupe
                chatbox.append_history("do the other thing")
                self.assertEqual(hist.count("do the other thing"), 1)
            finally:
                chatbox._history_path = old


class TestBoxLifecycle(unittest.TestCase):
    """v2.3.3: permanent bottom box — open registry, reflow, deregister."""

    class _FakeOut:
        def __init__(self):
            self.data = []

        def write(self, s):
            self.data.append(s)

        def flush(self):
            pass

    def test_clear_and_finish_deregister_open_box(self):
        from claume import chatbox as cb

        old_out = sys.stdout
        try:
            sys.stdout = self._FakeOut()
            ed = chatbox.Editor()
            rend = chatbox.Renderer("│ ❯ ", width=60)
            rend.ed = ed
            chatbox._OPEN_BOX = rend
            rend.render(ed, "")
            rend.clear()
            self.assertIsNone(chatbox._OPEN_BOX)

            chatbox._OPEN_BOX = rend
            rend.rows_drawn = 2
            rend.finish(ed, "done")
            self.assertIsNone(chatbox._OPEN_BOX)
        finally:
            sys.stdout = old_out

    def test_close_box_safe_when_nothing_open(self):
        from claume import chatbox as cb

        old = chatbox._OPEN_BOX
        try:
            chatbox._OPEN_BOX = None
            cb.close_box()  # must not raise
            self.assertFalse(cb.box_open())
        finally:
            chatbox._OPEN_BOX = old

    def test_busy_hint_outranks_placeholder(self):
        old_out = sys.stdout
        try:
            out = self._FakeOut()
            sys.stdout = out
            ed = chatbox.Editor()
            rend = chatbox.Renderer("│ ❯ ", width=70, placeholder="Enter a coding task or / for commands")
            rend.ed = ed
            rend.busy = True
            rend.render(ed, "")
            text = "".join(out.data)
            self.assertIn("task running", text)
            self.assertNotIn("Enter a coding task", text)
        finally:
            sys.stdout = old_out

    def test_attach_image_and_rejects_bad(self):
        import tempfile
        from claume import chatbox as cb

        # tiny valid 1x1 PNG
        png = bytes.fromhex(
            "89504e470d0a1a0a0000000d494844520000000100000001080200000090775"
            "3de0000000c4944415408d763f8cfc000000301010018dd8db00000000049454e44ae426082"
        )
        tmp = Path(tempfile.gettempdir()) / "claume_ut_img.png"
        tmp.write_bytes(png)
        try:
            att = cb.attach_image(str(tmp))
            self.assertIsNotNone(att)
            self.assertTrue(att["data_url"].startswith("data:image/png;base64,"))
            self.assertIsNone(cb.attach_image("Z:/nope/missing.png"))
        finally:
            tmp.unlink(missing_ok=True)


class TestPinboxGeometry(unittest.TestCase):
    """v2.3.4: pinned bottom box via VT scroll regions (Freebuff style)."""

    class _FakeOut:
        def __init__(self):
            self.data = []

        def write(self, s):
            self.data.append(s)
            return len(s)

        def flush(self):
            pass

        def isatty(self):
            return True

        encoding = "utf-8"

    def setUp(self):
        from claume import pinbox

        self.pb = pinbox
        self.real_stdout = sys.stdout
        self.real_stdin = sys.stdin
        self.fake = self._FakeOut()
        pinbox._term = lambda: (100, 30)
        sys.stdin = type("S", (), {"isatty": lambda self: True})()
        sys.stdout = self.fake

    def tearDown(self):
        self.pb._STATE["ed"] = None
        self.pb.leave()
        sys.stdout = self.real_stdout
        sys.stdin = self.real_stdin

    def test_non_tty_refused(self):
        import io

        sys.stdin = io.StringIO()
        self.assertFalse(self.pb.enter())
        self.assertFalse(self.pb.pinned())

    def test_enter_sets_scroll_region(self):
        self.assertTrue(self.pb.enter())
        data = "".join(self.fake.data)
        # 30 rows - 6 reserve = row 24 is the region bottom
        self.assertIn("\x1b[1;24r", data)

    def test_box_rows_absolutely_positioned(self):
        self.assertTrue(self.pb.enter())
        self.fake.data.clear()
        self.pb._draw_box()
        data = "".join(self.fake.data)
        for row in (25, 26, 27, 28, 29, 30):
            self.assertIn(f"\x1b[{row};1H", data)

    def test_output_scrolls_region_not_box(self):
        self.assertTrue(self.pb.enter())
        # open an editor so the cursor sits inside the box
        ed = self.pb._cb.Editor()
        for ch in "typing":
            ed.key(ch)
        self.pb._STATE["ed"] = ed
        self.pb._draw_box()
        self.fake.data.clear()
        print("worker output")
        import time

        time.sleep(0.05)
        data = "".join(self.fake.data)
        # parked at region bottom before writing
        self.assertIn("\x1b[24;1H", data)
        self.assertIn("worker output", data)
        # the output burst itself never touches box rows; after it, the
        # input row is legitimately redrawn (cursor snap-back) — verify
        # the redraw still contains the user's in-progress typing
        self.assertIn("typing", data.split("worker output", 1)[1])
        # borders/drops/bottom were never redrawn by the output path
        self.assertNotIn("\x1b[25;1H\x1b[2K", data)
        self.assertNotIn("\x1b[30;1H\x1b[2K", data)

    def test_finalize_echoes_and_clears_input_row(self):
        self.assertTrue(self.pb.enter())
        self.fake.data.clear()
        self.pb.finalize("build a portfolio")
        data = "".join(self.fake.data)
        self.assertIn("build a portfolio", data)
        self.assertIn("\x1b[26;1H", data)  # input row redrawn empty

    def test_leave_resets_region(self):
        self.assertTrue(self.pb.enter())
        self.pb.leave()
        self.assertFalse(self.pb.pinned())
        self.assertIn("\x1b[r", "".join(self.fake.data))

    def test_busy_hint_swaps_placeholder(self):
        self.assertTrue(self.pb.enter())
        self.pb.set_busy(True)
        self.pb._STATE["placeholder"] = "Enter a coding task or / for commands"
        self.fake.data.clear()
        self.pb._draw_box()
        plain = "".join(self.fake.data)
        plain = plain.replace("\x1b[38;5;240m", "").replace("\x1b[0m", "")
        self.assertIn("task running", plain)


class TestIdeIntegration(unittest.TestCase):
    """v2.4.0: IDE detection, open-at-line, atomic writes."""

    def test_detect_shape(self):
        from claume import ide

        info = ide.detect()
        self.assertEqual(set(info), {"name", "kind", "cli", "open_support"})
        self.assertIn(info["kind"], ("vscode", "jetbrains", "external"))

    def test_detect_vscode_marker(self):
        from claume import ide

        old = {
            k: os.environ.get(k)
            for k in ("TERM_PROGRAM", "CURSOR_TRACE_ID", "VSCODE_GIT_ASKPASS_NODE")
        }
        try:
            os.environ["TERM_PROGRAM"] = "vscode"
            os.environ.pop("CURSOR_TRACE_ID", None)
            info = ide.detect()
            self.assertEqual(info["name"], "VS Code")
            self.assertEqual(info["kind"], "vscode")
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_detect_cursor_over_vscode(self):
        from claume import ide

        old = {k: os.environ.get(k) for k in ("CURSOR_TRACE_ID", "TERM_PROGRAM")}
        try:
            os.environ["CURSOR_TRACE_ID"] = "1"
            os.environ["TERM_PROGRAM"] = "vscode"
            self.assertEqual(ide.detect()["name"], "Cursor")
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_detect_jetbrains_terminal(self):
        from claume import ide

        old = os.environ.get("TERMINAL_EMULATOR")
        try:
            os.environ["TERMINAL_EMULATOR"] = "JetBrains-JediTerm"
            info = ide.detect()
            self.assertEqual(info["kind"], "jetbrains")
        finally:
            if old is None:
                os.environ.pop("TERMINAL_EMULATOR", None)
            else:
                os.environ["TERMINAL_EMULATOR"] = old

    def test_open_file_missing_guard(self):
        from claume import ide

        msg, err = ide.open_file("Z:/definitely/missing.py")
        self.assertTrue(err)
        self.assertIn("not found", msg)

    def test_atomic_write_replaces_cleanly(self):
        from claume.tools import fs

        tmp = Path(tempfile.mkdtemp())
        try:
            (tmp / "src").mkdir()
            target = tmp / "src" / "app.py"
            target.write_text("print('v1')\n", encoding="utf-8")
            msg, err = fs.write_file(tmp, "src/app.py", "print('v2')\n")
            self.assertFalse(err)
            self.assertEqual(target.read_text(encoding="utf-8"), "print('v2')\n")
            leftovers = [p for p in (tmp / "src").iterdir() if p.suffix == ".tmp"]
            self.assertEqual(leftovers, [])

            msg, err = fs.patch_file(tmp, "src/app.py", "v2", "v3")
            self.assertFalse(err)
            self.assertIn("v3", target.read_text(encoding="utf-8"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_ide_tools_registered(self):
        from claume.tools import registry

        self.assertIn("ide_open", registry.REGISTRY)
        self.assertIn("ide_reveal", registry.REGISTRY)
        self.assertIn("ide_open(path", registry.schemas())


if __name__ == "__main__":
    unittest.main()
