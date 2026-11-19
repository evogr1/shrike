import os
import unittest

from shrike.config import load_config, load_secrets
from shrike.errors import ConfigError
from tests.fakes import tmpdir, write_config

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class ConfigTest(unittest.TestCase):
    def test_example_config_loads(self):
        cfg = load_config(os.path.join(ROOT, "config.example.toml"))
        self.assertEqual([s.name for s in cfg.sites], ["evogr", "solodac"])
        self.assertEqual(cfg.phase, 0)

    def test_bad_property_names_the_key(self):
        t = tmpdir()
        p = write_config(t)
        with open(p) as f:
            s = f.read().replace("sc-domain:ex.com", "ex.com")
        with open(p, "w") as f:
            f.write(s)
        with self.assertRaises(ConfigError) as cm:
            load_config(p)
        self.assertIn("sites[0].property", str(cm.exception))

    def test_bad_type_names_the_key(self):
        t = tmpdir()
        p = write_config(t, extra="keep_daily = \"thirty\"")
        with self.assertRaises(ConfigError) as cm:
            load_config(p)
        self.assertIn("backup.keep_daily", str(cm.exception))


class SecretsTest(unittest.TestCase):
    def setUp(self):
        self.t = tmpdir()
        self.key = os.path.join(self.t, "sa.json")
        with open(self.key, "w") as f:
            f.write("{}")
        os.chmod(self.key, 0o600)
        self.env = {"SHRIKE_SERVICE_ACCOUNT_FILE": self.key, "SHRIKE_TRELLO_KEY": "k", "SHRIKE_TRELLO_TOKEN": "t"}

    def test_ok(self):
        self.assertEqual(load_secrets("jobs", self.env).trello_key, "k")

    def test_key_file_mode_644_refused(self):
        os.chmod(self.key, 0o644)
        with self.assertRaises(ConfigError) as cm:
            load_secrets("jobs", self.env)
        self.assertIn("chmod 600", cm.exception.fix_step)

    def test_trello_required_in_phase0(self):
        env = dict(self.env, SHRIKE_TRELLO_TOKEN="")
        with self.assertRaises(ConfigError):
            load_secrets("jobs", env)

    def test_alert_needs_only_trello(self):
        self.assertTrue(load_secrets("alert", {"SHRIKE_TRELLO_KEY": "k", "SHRIKE_TRELLO_TOKEN": "t"}))

    def test_render_units_needs_nothing(self):
        self.assertTrue(load_secrets("render-units", {}) is not None)

    def test_server_secret_lengths(self):
        with self.assertRaises(ConfigError):
            load_secrets("server", {"SHRIKE_API_KEY": "short"})
        with self.assertRaises(ConfigError):
            load_secrets("server", {"SHRIKE_API_KEY": "x" * 24, "SHRIKE_MCP_SECRET": "short"})
        self.assertTrue(load_secrets("server", {"SHRIKE_API_KEY": "x" * 24}))


if __name__ == "__main__":
    unittest.main()
