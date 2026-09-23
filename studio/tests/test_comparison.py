import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('prepare_comparison', Path(__file__).resolve().parents[1] / 'scripts/prepare_comparison.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ComparisonTests(unittest.TestCase):
    def test_pairs_preserve_scene_seed_and_parameters(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'comparison'
            manifest = module.prepare(output)
            self.assertEqual(len(manifest['runs']), 12)
            self.assertEqual(len(manifest['seedance_cases']), 6)
            self.assertEqual(manifest['gpu_jobs_submitted'], 0)
            for index in range(0, len(manifest['runs']), 2):
                pair = manifest['runs'][index:index + 2]
                prompts = [json.loads((output / run['prompt_file']).read_text(encoding='utf-8')) for run in pair]
                for prompt in prompts:
                    for node in prompt.values():
                        if node['class_type'] == 'H3MAXMotionPreset':
                            self.assertFalse(node['inputs']['people_realism'])
                            self.assertFalse(node['inputs']['camera_motion'])
                            node['inputs']['profile'] = 'normalized'
                        if node['class_type'] == 'SaveVideo':
                            node['inputs']['filename_prefix'] = 'normalized'
                self.assertEqual(prompts[0], prompts[1])
                self.assertTrue(all(value is None for value in pair[0]['physics_scores'].values()))
            with self.assertRaises(FileExistsError):
                module.prepare(output)


if __name__ == '__main__':
    unittest.main()
