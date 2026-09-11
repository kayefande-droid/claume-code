"""Proxy + config + vault tests (no network required)."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from claume import config, keyvault, proxy


class TestConfig(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="claume-cfg-")
        self._orig_home = config.home_dir
        # Redirect claume dir into temp
        config.home_dir = lambda: Path(self.tmp)

    def tearDown(self):
        config.home_dir = self._orig_home

    def test_defaults_and_set(self):
        cfg = config.Config()
        self.assertEqual(cfg.get("proxy_port"), 8000)
        cfg.set("model", "test/model")
        cfg2 = config.Config()
        self.assertEqual(cfg2.model, "test/model")


class TestKeyvault(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="claume-vault-")
        self._orig = config.claume_dir
        config.claume_dir = lambda: Path(self.tmp) / ".claume"

    def tearDown(self):
        config.claume_dir = self._orig

    def test_roundtrip(self):
        keyvault.set_key("TEST_KEY", "nvapi-secret-value-123")
        self.assertEqual(keyvault.get_key("TEST_KEY"), "nvapi-secret-value-123")
        masked = keyvault.list_keys()
        self.assertIn("TEST_KEY", masked)
        self.assertNotIn("nvapi-secret-value-123", str(masked))
        self.assertTrue(keyvault.delete_key("TEST_KEY"))
        self.assertIsNone(keyvault.get_key("TEST_KEY"))


class TestProxyKeys(unittest.TestCase):
    def test_collect_empty(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            # point vault at empty temp dir
            with mock.patch.object(config, "claume_dir", lambda: Path(tempfile.mkdtemp()) / ".claume"):
                with mock.patch.object(keyvault, "claume_dir", config.claume_dir, create=True):
                    keys = proxy.collect_keys()
        # may be empty; must not crash
        self.assertIsInstance(keys, list)


if __name__ == "__main__":
    unittest.main()
