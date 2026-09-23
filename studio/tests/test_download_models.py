import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import tempfile
import unittest
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
spec = importlib.util.spec_from_file_location(
    "download_models", Path(__file__).resolve().parents[1] / "scripts/download_models.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.content = b"test model bytes"
        self.model = {
            "destination": "models/diffusion_models/model.safetensors",
            "repository": "owner/model", "file": "model.safetensors",
            "revision": "a" * 40, "groups": ["h3"],
            "size_bytes": len(self.content),
            "sha256_published": hashlib.sha256(self.content).hexdigest(),
        }
        self.target = self.root / self.model["destination"]
        self.hub = SimpleNamespace(hf_hub_download=mock.Mock(side_effect=self.fake_download))
        self.addCleanup(mock.patch.stopall)
        mock.patch.dict(os.environ, {}, clear=True).start()
        mock.patch.dict("sys.modules", {"huggingface_hub": self.hub}).start()
        mock.patch.object(module.shutil, "disk_usage", return_value=SimpleNamespace(free=10**12)).start()

    def fake_download(self, **kwargs):
        target = kwargs["local_dir"] / kwargs["filename"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(self.content)
        return str(target)

    def save_manifest(self):
        (self.root / "models.lock.json").write_text(json.dumps({
            "groups": {"h3": "base"}, "models": [self.model]}))

    def test_group_whitespace_and_empty_selection(self):
        self.save_manifest()
        with mock.patch.object(module, "PACKAGE", self.root):
            self.assertEqual(module.selected_models(" h3, "), [self.model])
            for invalid in ("", " , ", "h33"):
                with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                    module.selected_models(invalid)

    def test_rejects_unsafe_destinations_before_download(self):
        for destination in ("../outside", "/outside", "models/../../outside", "C:/outside", "models\\..\\outside"):
            with self.subTest(destination=destination):
                self.model["destination"] = destination
                self.save_manifest()
                with mock.patch.object(module, "PACKAGE", self.root), self.assertRaises(ValueError):
                    module.selected_models("h3")
        self.hub.hf_hub_download.assert_not_called()

    def test_download_pins_revision_verifies_and_promotes(self):
        module.download_models(self.root, [self.model])
        self.assertEqual(self.target.read_bytes(), self.content)
        self.assertEqual(self.hub.hf_hub_download.call_args.kwargs["revision"], "a" * 40)
        receipt = json.loads((self.root / "model-receipts.json").read_text())
        self.assertEqual(receipt[self.model["destination"]]["sha256"], self.model["sha256_published"])

    def test_bad_download_is_never_promoted(self):
        self.model["sha256_published"] = "0" * 64
        with self.assertRaisesRegex(RuntimeError, "Downloaded model failed"):
            module.download_models(self.root, [self.model])
        self.assertFalse(self.target.exists())

    def test_token_reaches_download_without_entering_logs_or_receipts(self):
        token = "hf_unit_test_only_not_a_real_credential"
        with mock.patch.dict(os.environ, {"HF_TOKEN": token, "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1"}):
            with mock.patch("sys.stdout", new_callable=io.StringIO) as output:
                module.download_models(self.root, [self.model])
        self.assertEqual(self.hub.hf_hub_download.call_args.kwargs["token"], token)
        self.assertNotIn(token, output.getvalue())
        self.assertNotIn(token, (self.root / "model-receipts.json").read_text())
        self.assertFalse((self.root / ".cache/huggingface/token").exists())

    def test_persistent_cache_configured_before_download_without_full_duplicate(self):
        def check_environment(**kwargs):
            self.assertEqual(Path(os.environ["HF_HOME"]), self.root / ".cache/huggingface")
            self.assertEqual(Path(os.environ["HF_XET_CACHE"]), self.root / ".cache/huggingface/xet")
            self.assertEqual(os.environ["HF_XET_HIGH_PERFORMANCE"], "1")
            self.assertEqual(os.environ["HF_XET_CHUNK_CACHE_SIZE_BYTES"], "0")
            self.assertIsNone(kwargs["token"])
            return self.fake_download(**kwargs)
        self.hub.hf_hub_download.side_effect = check_environment
        module.download_models(self.root, [self.model])
        self.assertTrue(self.target.exists())
        self.assertFalse(list((self.root / ".downloads").rglob("*.safetensors")))
        self.assertEqual(len(list(self.root.rglob("*.safetensors"))), 1)

    def test_existing_corrupt_file_is_preserved_and_not_downloaded(self):
        self.target.parent.mkdir(parents=True)
        self.target.write_bytes(b"bad")
        with self.assertRaisesRegex(RuntimeError, "Existing file failed"):
            module.download_models(self.root, [self.model])
        self.assertEqual(self.target.read_bytes(), b"bad")
        self.hub.hf_hub_download.assert_not_called()

    def test_verify_only_checks_hash_even_with_matching_receipt(self):
        module.download_models(self.root, [self.model])
        with mock.patch.object(module, "sha256", return_value="0" * 64), self.assertRaises(RuntimeError):
            module.download_models(self.root, [self.model], verify_only=True)

    def test_truncated_receipt_rehashes_existing_file(self):
        self.target.parent.mkdir(parents=True)
        self.target.write_bytes(self.content)
        (self.root / "model-receipts.json").write_text("{")
        module.download_models(self.root, [self.model], verify_only=True)
        self.hub.hf_hub_download.assert_not_called()
        self.assertIn(self.model["destination"], json.loads((self.root / "model-receipts.json").read_text()))

    def test_volume_lock_rejects_competing_download_and_releases(self):
        with module.download_lock(self.root):
            with self.assertRaisesRegex(RuntimeError, "Another model bootstrap"):
                with module.download_lock(self.root):
                    self.fail("A second writer acquired the download lock")
        with module.download_lock(self.root):
            pass


if __name__ == "__main__":
    unittest.main()
