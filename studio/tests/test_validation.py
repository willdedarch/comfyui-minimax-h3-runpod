import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import validate


class ValidationTests(unittest.TestCase):
    def test_all_eight_api_exports_match_editable_workflows(self):
        for path in sorted((ROOT / "workflows").glob("*.json")):
            with self.subTest(workflow=path.name):
                validate.check_graph(path)
                validate.check_api(ROOT / "api_prompts" / path.name, path)

    def test_api_parameter_drift_is_rejected(self):
        workflow = ROOT / "workflows/01_H3_MAX_TEXTO.json"
        api = json.loads((ROOT / "api_prompts" / workflow.name).read_text(encoding="utf-8"))
        next(node for node in api.values() if node["class_type"] == "BasicScheduler")["inputs"]["steps"] = 999
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / workflow.name
            path.write_text(json.dumps(api), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "differs"):
                validate.check_api(path, workflow)

    def test_negative_output_slot_is_rejected(self):
        graph = json.loads((ROOT / "workflows/01_H3_MAX_TEXTO.json").read_text(encoding="utf-8"))
        graph["links"][0][2] = -1
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            path.write_text(json.dumps(graph), encoding="utf-8")
            with self.assertRaisesRegex(AssertionError, "invalid output slot"):
                validate.check_graph(path)

    def test_second_pass_lora_does_not_stack_over_first_pass(self):
        for number in ("05", "06", "07", "08"):
            path = next((ROOT / "api_prompts").glob(number + "*.json"))
            api = json.loads(path.read_text(encoding="utf-8"))
            presets = [n for n in api.values() if n["class_type"] == "H3MAXMotionPreset"]
            self.assertEqual(len(presets), 2)
            for preset in presets:
                self.assertEqual(api[preset["inputs"]["model"][0]]["class_type"], "UNETLoader")
            self.assertAlmostEqual(presets[1]["inputs"]["motion_multiplier"] * .9, .25)
            for n in api.values():
                if n["class_type"] == "H3InjectSchedule":
                    self.assertEqual((n["inputs"]["inject"], n["inputs"]["preset"]), (.48, "custom"))


if __name__ == "__main__":
    unittest.main()
