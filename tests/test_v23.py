"""Tests for claume v2.3: webstudio, activity log, MCP npm resolution,
proxy model filtering + admin dashboard, session activity display."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claume import activity, config, mcp, prompts, sessions, webstudio  # noqa: E402


class TestWebStudio(unittest.TestCase):
    def test_design_task_detection(self):
        self.assertTrue(webstudio.is_design_task("build a portfolio website for me"))
        self.assertTrue(webstudio.is_design_task("make a landing page with a hero"))
        self.assertTrue(webstudio.is_design_task("fix the dashboard UI"))
        self.assertFalse(webstudio.is_design_task("fix the failing pytest in tests/"))
        self.assertFalse(webstudio.is_design_task(""))
        self.assertFalse(webstudio.is_design_task(None))

    def test_studio_brief_content(self):
        text, err = webstudio.studio_brief("claume website")
        self.assertFalse(err)
        for token in ("Fraunces", "Space Grotesk", "JetBrains Mono", "#76b900",
                      "explode-view", "webstudio_pull_font", "claume website"):
            self.assertIn(token, text)

    def test_pull_font_downloads_woff2_locally(self):
        """Live test: Google Fonts CSS is rewritten with local woff2 files."""
        if not os.environ.get("CLAUME_LIVE_FONTS"):
            self.skipTest("live font download (set CLAUME_LIVE_FONTS=1)")
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            out, err = webstudio.pull_font(ws, "Fraunces", "300;400")
            self.assertFalse(err, out)
            css = ws / "assets" / "fonts" / "fraunces.css"
            self.assertTrue(css.exists())
            text = css.read_text(encoding="utf-8")
            self.assertNotIn("fonts.gstatic.com", text)
            self.assertGreaterEqual(len(list((ws / "assets" / "fonts").glob("*.woff2"))), 1)

    def test_pull_font_rejects_empty(self):
        with tempfile.TemporaryDirectory() as td:
            out, err = webstudio.pull_font(Path(td), "")
            self.assertTrue(err)

    def test_pull_asset_rejects_non_http(self):
        with tempfile.TemporaryDirectory() as td:
            out, err = webstudio.pull_asset(Path(td), "ftp://nope/x.png")
            self.assertTrue(err)

    def test_pull_asset_downloads(self):
        """Live test: real asset download."""
        if not os.environ.get("CLAUME_LIVE_FONTS"):
            self.skipTest("live asset download (set CLAUME_LIVE_FONTS=1)")
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            out, err = webstudio.pull_asset(
                ws, "https://uncss-js.github.io/Primer/img/octicons.svg", "test.svg"
            )
            self.assertFalse(err, out)
            self.assertTrue((ws / "assets" / "test.svg").exists())


class TestDesignBlockInjection(unittest.TestCase):
    def test_design_block_injected_for_design_tasks(self):
        block = prompts.build_design_block("build me a portfolio website")
        self.assertIn("claume studio", block.lower() + block)
        self.assertIn("Fraunces", block)

    def test_design_block_empty_for_coding_tasks(self):
        self.assertEqual(prompts.build_design_block("fix the parser bug"), "")


class TestActivityLog(unittest.TestCase):
    def test_record_and_summary(self):
        with tempfile.TemporaryDirectory() as td:
            old = config.sessions_dir
            sdir = Path(td) / "sessions"
            sdir.mkdir(parents=True)
            config.sessions_dir = lambda: sdir
            try:
                activity.record("s1", "file", tool="write_file", target="app/main.py", ok=True)
                activity.record("s1", "file", tool="patch_file", target="app/main.py", ok=True)
                activity.record("s1", "command", tool="execute_command", target="pytest -q", ok=True)
                activity.record("s1", "mcp", tool="mcp_uidiscovery-21st_search", ok=True)
                activity.record("s1", "web", tool="web_search", target="tailwind docs", ok=True)
                s = activity.summary("s1")
                self.assertIn("1 file(s): main.py", s)
                self.assertIn("1 command(s)", s)
                self.assertIn("MCP", s)
                self.assertIn("1 web call(s)", s)
                stats = activity.stats("s1")
                self.assertEqual(stats.get("file"), 2)
            finally:
                config.sessions_dir = old

    def test_summary_empty(self):
        with tempfile.TemporaryDirectory() as td:
            old = config.sessions_dir
            config.sessions_dir = lambda: Path(td)
            try:
                self.assertEqual(activity.summary("missing"), "")
            finally:
                config.sessions_dir = old


class TestMcpNpmResolution(unittest.TestCase):
    def test_spec_package_name(self):
        self.assertEqual(mcp._spec_package_name("@21st-dev/magic"), "@21st-dev/magic")
        self.assertEqual(mcp._spec_package_name("@21st-dev/magic@1.2.3"), "@21st-dev/magic")
        self.assertEqual(mcp._spec_package_name("clerk@latest"), "clerk")
        self.assertEqual(mcp._spec_package_name("shadcnspace-mcp"), "shadcnspace-mcp")

    def test_non_npx_spec_passthrough(self):
        cmd, args = mcp.ensure_npm_server(
            "x", {"command": "node", "args": ["/abs/path/server.js"]}
        )
        self.assertEqual((cmd, args), ("node", ["/abs/path/server.js"]))

    def test_find_npm_bin_for_installed_package(self):
        """Live test: package was installed into ~/.claume/mcp/npm by the
        smoke run; when present, npx spec resolves to a node script."""
        if not (mcp._npm_root() / "node_modules").exists():
            self.skipTest("no npm-installed MCP packages")
        script = mcp._find_npm_bin("shadcnspace-mcp")
        if script is None:
            self.skipTest("shadcnspace-mcp not installed")
        self.assertTrue(script.exists())
        self.assertEqual(script.suffix, ".js")


class TestModelFiltering(unittest.TestCase):
    def test_filter_removes_non_chat_and_dead(self):
        models = [
            {"id": "meta/llama-3.3-70b-instruct"},  # DEAD_MODELS
            {"id": "nvidia/nv-embed-v1"},           # embedding
            {"id": "baai/bge-m3"},                  # reranker-ish
            {"id": "openai/gpt-oss-120b"},
        ]
        out = mcp_mod_filter(models)
        ids = [m["id"] for m in out]
        self.assertNotIn("nvidia/nv-embed-v1", ids)
        self.assertNotIn("meta/llama-3.3-70b-instruct", ids)
        self.assertIn("openai/gpt-oss-120b", ids)


def mcp_mod_filter(models):
    from claume import proxy

    # sample stays above len(keep) so no network probes fire.
    return proxy._filter_chat_models(models, api_key="nvapi-test", sample=60)


class TestProxyDefaults(unittest.TestCase):
    def test_default_pool_not_in_dead_models(self):
        from claume import proxy

        for model in proxy.DEFAULT_MODEL_POOL:
            self.assertNotIn(model, config.DEAD_MODELS)

    def test_admin_html_is_studio_dashboard(self):
        from claume.proxy_ui import ADMIN_HTML

        for token in ("claume", "studio", "explode", "Fraunces", "admin/data"):
            self.assertIn(token, ADMIN_HTML)
        self.assertGreater(len(ADMIN_HTML), 15_000)

    def test_probe_chat_model_returns_tuple_shape(self):
        from claume import proxy

        ok, detail = proxy.probe_chat_model("nvapi-invalid-key", "openai/gpt-oss-120b", timeout=15)
        self.assertIsInstance(ok, bool)
        self.assertIsInstance(detail, str)


class TestSessionsActivityField(unittest.TestCase):
    def test_list_sessions_has_activity_key(self):
        with tempfile.TemporaryDirectory() as td:
            old = config.sessions_dir
            sdir = Path(td) / "sessions"
            sdir.mkdir(parents=True)
            config.sessions_dir = lambda: sdir
            try:
                sid = sessions.start_new(project="demo")
                sessions.save_session(sid, [{"role": "user", "content": "hello world"}])
                entries = sessions.list_sessions(limit=5)
                self.assertTrue(entries)
                self.assertIn("activity", entries[0])
            finally:
                config.sessions_dir = old


class TestBundledSkillsSeeding(unittest.TestCase):
    def test_seed_bundled_skills_activates(self):
        """Seed into a temp skills dir; bundled skill must END UP active
        (fresh install -> seeded+activated; already-active config -> no-op)."""
        with tempfile.TemporaryDirectory() as td:
            old = config.skills_dir
            cfg = config.Config()
            old_active = cfg.get("skills_active", {}) or {}
            config.skills_dir = lambda: Path(td) / "skills"
            try:
                from claume import skills as skillsmod

                skillsmod.seed_bundled_skills()
                # The contract: after startup seeding, the bundled skill is active.
                active = config.Config().get("skills_active", {}) or {}
                if (Path(__file__).resolve().parent.parent / "skills" / "ui-ux-pro-max-skill").exists():
                    self.assertTrue(active.get("ui-ux-pro-max-skill", False))
            finally:
                config.skills_dir = old
                cfg.set("skills_active", old_active)


if __name__ == "__main__":
    unittest.main()
