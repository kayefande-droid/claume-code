"""Tests for tools, security, and parser (stdlib unittest, no pytest needed)."""
import shutil
import tempfile
import unittest
from pathlib import Path

from claume import security
from claume.parser import parse_turn
from claume.tools import registry


class TestFsTools(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix="claume-test-"))

    def tearDown(self):
        shutil.rmtree(self.base, ignore_errors=True)

    def test_write_and_read(self):
        res, err = registry.execute(self.base, "write_file", {"path": "a/b.txt", "content": "hello\nworld"})
        self.assertFalse(err)
        res, err = registry.execute(self.base, "read_file", {"path": "a/b.txt"})
        self.assertFalse(err)
        self.assertIn("hello", res)

    def test_patch_exact(self):
        registry.execute(self.base, "write_file", {"path": "x.py", "content": "def main():\n    pass\n"})
        res, err = registry.execute(self.base, "patch_file", {
            "path": "x.py", "old_string": "def main():", "new_string": "def main() -> None:",
        })
        self.assertFalse(err)
        text = (self.base / "x.py").read_text()
        self.assertIn("def main() -> None:", text)

    def test_patch_missing_string_fails(self):
        registry.execute(self.base, "write_file", {"path": "y.py", "content": "abc"})
        res, err = registry.execute(self.base, "patch_file", {
            "path": "y.py", "old_string": "nope", "new_string": "x",
        })
        self.assertTrue(err)

    def test_list_and_tree(self):
        registry.execute(self.base, "make_directory", {"path": "pkg/sub"})
        registry.execute(self.base, "write_file", {"path": "pkg/mod.py", "content": "x = 1"})
        res, err = registry.execute(self.base, "list_directory", {"path": "."})
        self.assertFalse(err)
        self.assertIn("pkg/", res)
        res, err = registry.execute(self.base, "tree_view", {"path": "."})
        self.assertIn("├──", res or res)

    def test_search_text(self):
        registry.execute(self.base, "write_file", {"path": "s.py", "content": "UNIQUE_TOKEN = 42\n"})
        res, err = registry.execute(self.base, "search_text", {"pattern": "UNIQUE_TOKEN"})
        self.assertFalse(err)
        self.assertIn("s.py", res)

    def test_execute_echo(self):
        res, err = registry.execute(self.base, "execute_command", {"command": "echo claume", "timeout": 20})
        self.assertFalse(err)
        self.assertIn("claume", res)


class TestSecurity(unittest.TestCase):
    def test_safe(self):
        self.assertEqual(security.classify_command("ls -la").level, "safe")
        self.assertEqual(security.classify_command("python main.py").level, "safe")

    def test_caution(self):
        self.assertEqual(security.classify_command("npm install express").level, "caution")
        self.assertEqual(security.classify_command("pip install requests").level, "caution")

    def test_destructive(self):
        self.assertEqual(security.classify_command("rm -rf /").level, "destructive")
        self.assertEqual(security.classify_command("git push --force").level, "destructive")
        self.assertEqual(security.classify_command("del /s /q C:\\x").level, "destructive")
        self.assertEqual(security.classify_command("shutdown").level, "destructive")

    def test_redact(self):
        out = security.redact_secrets("key is nvapi-abc123def456 here", ["nvapi-abc123def456"])
        self.assertNotIn("nvapi-abc123def456", out)


class TestParser(unittest.TestCase):
    def test_clean_envelope(self):
        t = parse_turn('{"thought": "read first", "action": {"tool": "read_file", "args": {"path": "a"}}}')
        self.assertEqual(t.thought, "read first")
        self.assertEqual(t.action.tool, "read_file")
        self.assertIsNone(t.final)

    def test_fenced_json(self):
        t = parse_turn('```json\n{"thought": "done", "final": "all set"}\n```')
        self.assertEqual(t.final, "all set")

    def test_prose_wrapped(self):
        t = parse_turn('Here is my plan:\n{"thought": "x", "final": "done!"}\nHope that helps')
        self.assertEqual(t.final, "done!")

    def test_invalid(self):
        t = parse_turn("I will now read the file.")
        self.assertIsNotNone(t.error)

    def test_missing_action(self):
        t = parse_turn('{"thought": "hmm"}')
        self.assertIsNotNone(t.error)


if __name__ == "__main__":
    unittest.main()
