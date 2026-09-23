import importlib.util
import json
import os
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
spec = importlib.util.spec_from_file_location('prepare_template', Path(__file__).resolve().parents[1] / 'scripts/prepare_template.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class TemplateTests(unittest.TestCase):
    def test_rejects_mutable_and_placeholder_images(self):
        for image in ('ghcr.io/owner/h3:latest', 'YOUR_REGISTRY/YOUR_IMAGE', 'ghcr.io/owner/h3@sha256:abcd'):
            with self.subTest(image=image), self.assertRaises(ValueError):
                module.make_template(image)

    def test_preserves_startup_and_does_not_claim_network_volume(self):
        image = 'ghcr.io/owner/h3@sha256:' + 'a' * 64
        payload = module.make_template(image, 'existing-registry-id')
        self.assertEqual(payload['image'], image)
        self.assertEqual(payload['registry'], 'existing-registry-id')
        self.assertNotIn('args', payload)
        self.assertEqual(payload['mounts'], {'persistent': {'path': '/workspace', 'size': 300}})
        self.assertEqual(payload['ports'], ['8188/http'])
        self.assertEqual(payload['allowedCudaVersions'], ['13.0', '13.2'])
        self.assertFalse(payload['public'])

    def test_token_is_blank_even_when_build_process_has_credentials(self):
        with mock.patch.dict(os.environ, {'HF_TOKEN': 'hf_build_test_only'}):
            payload = module.make_template('ghcr.io/owner/h3@sha256:' + 'a' * 64)
        env = payload['env']
        self.assertEqual(env['HF_TOKEN'], '')
        self.assertNotIn('hf_build_test_only', json.dumps(payload))
        for key in ('HF_HOME', 'HF_HUB_CACHE', 'HF_XET_CACHE', 'HF_ASSETS_CACHE'):
            self.assertTrue(env[key].startswith('/workspace/h3max/'))
            self.assertNotIn('$', env[key])
            self.assertNotIn('\\', env[key])
        self.assertEqual(env['HF_XET_HIGH_PERFORMANCE'], '1')
        self.assertNotIn('HF_HUB_ENABLE_HF_TRANSFER', env)


if __name__ == '__main__':
    unittest.main()
