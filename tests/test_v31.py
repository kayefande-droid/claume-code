"""Tests for claume v3.1: memory, plugins, QR/bridge, jarvis shaping, provider."""
import os
import tempfile
import unittest


class _IsolatedHome(unittest.TestCase):
    """Redirect CLAUUME_HOME to a temp dir for the duration of each test."""

    def setUp(self) -> None:
        self._old = os.environ.get("CLAUUME_HOME")
        os.environ["CLAUUME_HOME"] = tempfile.mkdtemp()

    def tearDown(self) -> None:
        if self._old is None:
            os.environ.pop("CLAUUME_HOME", None)
        else:
            os.environ["CLAUUME_HOME"] = self._old


class TestMemory(_IsolatedHome):
    def test_save_read_forget_roundtrip(self):
        from claume import memory

        status = memory.save_memory("test-pref", "prefers dark UI", "user")
        self.assertIn("saved", status)
        text = memory.read_memory("test-pref")
        self.assertIn("prefers dark UI", text)
        self.assertIn("type: user", text)
        # index line exists
        idx = memory.index_path().read_text(encoding="utf-8")
        self.assertIn("[test-pref]", idx)
        out = memory.forget_memory("test-pref")
        self.assertIn("deleted", out)
        self.assertIn("no memory", memory.read_memory("test-pref"))

    def test_memory_block_lists_index(self):
        from claume import memory

        memory.save_memory("proj-x", "using pygame for the game", "project")
        block = memory.memory_block()
        self.assertIn("proj-x", block)
        self.assertIn("Persistent memory", block)

    def test_feedback_gets_why_scaffold(self):
        from claume import memory

        memory.save_memory("no-force-push", "never force push", "feedback")
        text = memory.read_memory("no-force-push")
        self.assertIn("**Why:**", text)


class TestPlugins(_IsolatedHome):
    def test_plugin_list_and_toggle(self):
        from claume import skills

        names = [p["name"] for p in skills.list_plugins()]
        self.assertIn("graphify", names)
        self.assertIn("jarvis", names)
        self.assertTrue(skills.set_plugin_active("jarvis", True))
        self.assertTrue(skills.plugin_active("jarvis"))
        self.assertTrue(skills.set_plugin_active("jarvis", False))
        self.assertFalse(skills.plugin_active("jarvis"))
        self.assertFalse(skills.set_plugin_active("nope", True))

    def test_bundled_skills_registered(self):
        from claume import skills

        for name in ("taste-skill", "system-prompts-leaks", "agency-agents",
                     "claudex-loop", "design-md-chrome", "awesome-claude-design",
                     "design-motion-principles"):
            self.assertIn(name, skills.BUNDLED_SKILLS)


class TestQR(_IsolatedHome):
    URL = "http://192.168.43.10:8765"

    def test_matrix_structure(self):
        from claume import screen

        m = screen.qr_matrix(self.URL)
        n = len(m)
        self.assertEqual(n, 25)  # version 2
        # finder corners dark
        self.assertTrue(m[0][0] and m[0][n - 7] and m[n - 7][0])
        # separators light
        self.assertFalse(m[7][7])
        # timing alternates
        self.assertEqual(m[6][8], m[6][10] == (8 % 2 == 0))
        # dark module
        self.assertTrue(m[n - 8][8])

    def test_png_bytes(self):
        from claume import screen

        png = screen.qr_png(self.URL, scale=4)
        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))

    def test_cv2_roundtrip_if_available(self):
        try:
            import cv2  # noqa: F401
        except ImportError:
            self.skipTest("opencv not installed")
        import cv2
        import tempfile as tf

        from claume import screen

        png = screen.qr_png(self.URL, scale=8)
        p = tf.mkstemp(suffix=".png")[1]
        open(p, "wb").write(png)
        got = cv2.QRCodeDetector().detectAndDecode(cv2.imread(p))[0]
        self.assertEqual(got, self.URL)


class TestJarvisShaping(unittest.TestCase):
    def test_spoken_shape_strips_markdown(self):
        from claume.jarvis import _spoken_shape

        raw = "Here:\n```python\nprint('x')\n```\n- point one\n| a | b |\n**bold**"
        out = _spoken_shape(raw)
        self.assertNotIn("```", out)
        self.assertNotIn("|", out)
        self.assertNotIn("**", out)
        self.assertNotIn("- point", out)

    def test_voice_prompt_identity(self):
        from claume.jarvis import voice_system_prompt

        p = voice_system_prompt()
        self.assertIn("jarvis", p)
        self.assertIn("fifty words", p)

    def test_strip_wake(self):
        from claume.jarvis import _strip_wake

        self.assertEqual(_strip_wake("jarvis what time is it", "jarvis"), "what time is it")
        self.assertEqual(_strip_wake("hey jarvis", "jarvis"), "")
        # text BEFORE the wake word is dropped when something follows it
        self.assertEqual(_strip_wake("tell jarvis to run tests", "jarvis"), "to run tests")
        # no wake word → unchanged
        self.assertEqual(_strip_wake("run the tests", "jarvis"), "run the tests")


class TestProvider(_IsolatedHome):
    def test_tokenin_provider_registered(self):
        from claume import llm

        self.assertEqual(llm.PROVIDER_ENDPOINTS["tokenin"], "https://tokenin.my.id/v1")
        self.assertEqual(llm.PROVIDER_KEY_ENV["tokenin"], "TOKENIN_API_KEY")
        self.assertIn("myt/glm-5.3-free", llm.TOKENIN_MODELS)

    def test_default_provider_is_tokenin(self):
        from claume import config

        cfg = config.Config()
        self.assertEqual(cfg.get("provider"), "tokenin")

    def test_bootstrap_seeds_key_once(self):
        from claume import bootstrap, keyvault

        seeded = bootstrap.seed_builtin_keys()
        self.assertEqual(seeded, ["TOKENIN_API_KEY"])
        # simulate the user setting their own key, then re-seed: preserved
        keyvault.set_key("TOKENIN_API_KEY", "user-own-key")
        self.assertEqual(bootstrap.seed_builtin_keys(), [])
        self.assertEqual(keyvault.get_key("TOKENIN_API_KEY"), "user-own-key")


class TestScreenCapture(_IsolatedHome):
    def test_capture_runs(self):
        from claume import screen

        shot = screen.capture()
        # On Windows GDI or mss, capture should produce bytes; on headless
        # CI it may fail gracefully — only assert no crash + sane shape.
        self.assertIsInstance(shot, dict)
        self.assertIn("engine", shot)

    def test_local_ip_shape(self):
        from claume import screen

        ip = screen.local_ip()
        parts = ip.split(".")
        self.assertEqual(len(parts), 4)


if __name__ == "__main__":
    unittest.main()
