import importlib.util
import os
from pathlib import Path
import tempfile
import sys
import unittest
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
spec = importlib.util.spec_from_file_location(
    "h3max_start", Path(__file__).resolve().parents[1] / "scripts/start.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class StartTests(unittest.TestCase):
    def test_bad_options_fail_before_downloading(self):
        for value in ('{"cpu": true}', '[12]', '["--port", "9999"]', '["--output-directory=/tmp"]'):
            with self.subTest(value=value), mock.patch.dict(os.environ, {"H3MAX_COMFY_ARGS": value}):
                with mock.patch.object(module.subprocess, "run") as run, self.assertRaises(ValueError):
                    module.main()
                run.assert_not_called()

    def test_cpu_and_memory_flags_are_forwarded_as_arguments(self):
        with mock.patch.dict(os.environ, {"H3MAX_COMFY_ARGS": '["--cpu", "--lowvram"]'}):
            self.assertEqual(module.extra_arguments(), ["--cpu", "--lowvram"])

    def test_restart_preserves_user_workflow_and_image_model_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder).resolve()
            comfy, package, root = directory / "comfy", directory / "package", directory / "volume"
            (comfy / "models").mkdir(parents=True)
            (comfy / "models/placeholder").write_text("from image")
            (package / "workflows").mkdir(parents=True)
            (package / "workflows/test.json").write_text("original")
            # Windows without Developer Mode cannot create directory symlinks.
            probe = directory / "link-probe"
            try:
                probe.symlink_to(comfy, target_is_directory=True)
                probe.unlink()
            except OSError as exc:
                self.skipTest(f"Directory symlinks unavailable: {exc}")
            env = {"H3MAX_ROOT": str(root), "H3MAX_DOWNLOAD_MODELS": "0", "H3MAX_COMFY_ARGS": "[]"}
            with mock.patch.object(module, "COMFY", comfy), mock.patch.object(module, "PACKAGE", package):
                with mock.patch.dict(os.environ, env), mock.patch.object(module.os, "chdir"), mock.patch.object(module.os, "execv") as execute:
                    module.main()
                    user_workflow = root / "user/default/workflows/H3_MAX/test.json"
                    user_workflow.write_text("user edit")
                    module.main()
                    self.assertEqual(user_workflow.read_text(), "user edit")
                    self.assertEqual((comfy / "models").resolve(), root / "models")
                    self.assertEqual((comfy / "models.from-image/placeholder").read_text(), "from image")
                    self.assertIn(str(root / "output"), execute.call_args.args[1])


if __name__ == "__main__":
    unittest.main()
