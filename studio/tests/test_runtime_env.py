import os
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from runtime_env import configure_environment


class RuntimeEnvironmentTests(unittest.TestCase):
    def test_explicit_cache_and_performance_overrides_are_preserved(self):
        original = {"HF_HOME": "/custom/hf", "HF_XET_CACHE": "/custom/xet",
                    "HF_XET_HIGH_PERFORMANCE": "0", "HF_HUB_DOWNLOAD_TIMEOUT": "240"}
        with mock.patch.dict(os.environ, original, clear=True):
            configure_environment(Path("/workspace/h3max"))
            for key, value in original.items():
                self.assertEqual(os.environ[key], value)
            self.assertEqual(os.environ["HF_HUB_CACHE"], "/custom/hf/hub")
            self.assertNotIn("HF_TOKEN", os.environ)

    def test_bad_timeout_is_actionable_before_importing_or_downloading(self):
        for value in ("0", "-2", "invalid"):
            with self.subTest(value=value), mock.patch.dict(
                    os.environ, {"HF_HUB_DOWNLOAD_TIMEOUT": value}, clear=True):
                with self.assertRaisesRegex(ValueError, "HF_HUB_DOWNLOAD_TIMEOUT"):
                    configure_environment(Path("/workspace/h3max"))


if __name__ == "__main__":
    unittest.main()
