"""Salvage-path tests: broken JSON envelopes, truncated streams, HTML drift.

These cover the real-world NIM free-tier failure modes observed while
building sites via /design:
  * model emits a shredded write_file envelope (raw newlines / unescaped
    quotes inside args.content) — parser must reconstruct the call;
  * model streams a complete or truncated HTML document as plain prose —
    agent must recover it into the workspace;
  * reasoning models that return zero visible text — llm layer must fall
    through to the next model in the chain (covered indirectly here via
    the empty-envelope contract).
"""
import tempfile
import unittest
from pathlib import Path

from claume import parser
from claume.agent import Agent


class TestParserSalvage(unittest.TestCase):
    def test_clean_envelope_unaffected(self):
        r = parser.parse_turn(
            '{"thought": "t", "action": {"tool": "write_file", '
            '"args": {"path": "a.html", "content": "<p>hi</p>"}}}'
        )
        self.assertIsNone(r.error)
        self.assertEqual(r.action.args["content"], "<p>hi</p>")

    def test_shredded_write_envelope_reconstructed(self):
        # raw newlines + unescaped quotes inside content: classic LLM break
        broken = (
            '{"thought": "writing", "action": {"tool": "write_file", '
            '"args": {"path": "index.html", "content": "<!DOCTYPE html>\n'
            '<html>\n  <h1 class="hero">Space</h1>\n  <p>line "quoted"</p>\n'
            '</html>"}}'
        )
        r = parser.parse_turn(broken)
        self.assertIsNone(r.error)
        self.assertEqual(r.action.tool, "write_file")
        self.assertEqual(r.action.args["path"], "index.html")
        content = r.action.args["content"]
        self.assertIn('<h1 class="hero">Space</h1>', content)
        self.assertIn('line "quoted"', content)

    def test_escaped_sequences_unescaped(self):
        broken = (
            '{"thought": "t", "action": {"tool": "write_file", "args": '
            '{"path": "x.css", "content": ".a {\\n  color: red;\\n}"}}}'
        )
        r = parser.parse_turn(broken)
        self.assertIsNone(r.error)
        # \n sequences emitted by the model become real newlines
        self.assertEqual(r.action.args["content"], ".a {\n  color: red;\n}")

    def test_non_write_tools_not_salvaged(self):
        broken = '{"action": {"tool": "run_script", "args": {"code": "x=1\ny=2"}}}'
        r = parser.parse_turn(broken)
        self.assertIsNotNone(r.error)
        self.assertIsNone(r.action)

    def test_plain_prose_not_misread(self):
        r = parser.parse_turn("Sure, here is your landing page, enjoy!")
        self.assertIsNotNone(r.error)
        self.assertIsNone(r.action)


class TestHtmlReplySalvage(unittest.TestCase):
    def setUp(self):
        self.ws = Path(tempfile.mkdtemp(prefix="claume_test_salvage_"))
        self.agent = Agent.__new__(Agent)
        self.agent.workspace = self.ws

    def _page(self):
        return "<!DOCTYPE html>\n<html>\n<body>\n" + "<div>x</div>\n" * 120 + "</body>\n</html>"

    def test_complete_doc_saved(self):
        msg = Agent._salvage_html_reply(self.agent, "Here you go:\n" + self._page())
        self.assertIsNotNone(msg)
        f = self.ws / "index.html"
        self.assertTrue(f.exists())
        self.assertTrue(f.read_text(encoding="utf-8").startswith("<!DOCTYPE html>"))

    def test_truncated_doc_closed(self):
        truncated = "<!DOCTYPE html>\n<html>\n<body>\n" + "<div>y</div>\n" * 120
        msg = Agent._salvage_html_reply(self.agent, truncated)
        self.assertIsNotNone(msg)
        f = self.ws / "index.html"
        self.assertTrue(f.read_text(encoding="utf-8").rstrip().endswith("</html>"))

    def test_named_page_detected(self):
        msg = Agent._salvage_html_reply(
            self.agent, "gallery.html:\n" + self._page()
        )
        self.assertIsNotNone(msg)
        self.assertTrue((self.ws / "gallery.html").exists())

    def test_snippets_ignored(self):
        self.assertIsNone(Agent._salvage_html_reply(self.agent, "use <html> tags"))
        self.assertIsNone(Agent._salvage_html_reply(self.agent, "<html><body>tiny</body></html>"))
        self.assertIsNone(Agent._salvage_html_reply(self.agent, "no markup here at all"))


if __name__ == "__main__":
    unittest.main()
