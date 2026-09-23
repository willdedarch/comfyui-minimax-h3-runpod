"""Regression checks for real pinned API contracts; no Torch/GPU required."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import check_runtime as runtime
import check_image


class NativeLoraContract:
    """Signature at ComfyUI 912fca4 nodes.py:735,768 (the old call must fail)."""
    calls = []

    def load_lora(self, model, clip, lora_name, strength_model, strength_clip):
        self.calls.append((model, clip, lora_name, strength_model, strength_clip))
        return (model + " patched", clip)

    def load_lora_model_only(self, model, lora_name, strength_model):
        return (self.load_lora(model, None, lora_name, strength_model, 0)[0],)


class PresetRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("h3max_test", ROOT / "custom_nodes/ComfyUI-H3MAX/__init__.py")
        cls.nodes = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.nodes)

    def test_natural_uses_model_only_native_signature(self):
        NativeLoraContract.calls.clear()
        fake = types.SimpleNamespace(LoraLoaderModelOnly=NativeLoraContract)
        with patch.dict(sys.modules, {"nodes": fake}):
            result = self.nodes.H3MAXMotionPreset().apply("model", "scene", "natural", 1, False, .65, False, .8)
        self.assertEqual(result, ("model patched", "scene"))
        self.assertEqual(NativeLoraContract.calls, [("model", None, "Motion_Repair.safetensors", .9, 0)])

    def test_base_does_not_load_any_lora(self):
        with patch.dict(sys.modules, {"nodes": types.SimpleNamespace()}):
            self.assertEqual(self.nodes.H3MAXMotionPreset().apply("model", "scene", "base", 1, False, .65, False, .8), ("model", "scene"))

    def test_camera_trigger_stays_first_when_realism_is_also_enabled(self):
        fake = types.SimpleNamespace(LoraLoaderModelOnly=NativeLoraContract)
        with patch.dict(sys.modules, {"nodes": fake}):
            apply = self.nodes.H3MAXMotionPreset().apply
            for prompt in ("scene", "camera motion, scene", "CAMERA MOTION\n\nscene"):
                result = apply("m", prompt, "base", 1, True, .65, True, .8)[1]
                self.assertEqual(result, "camera motion, r34l1sm\n\nscene")
            interior = apply("m", "A scene with camera motion", "base", 1, False, .65, True, .8)[1]
            self.assertTrue(interior.startswith("camera motion\n\n"))

    def test_weapon_trigger_only_when_enabled_and_not_duplicated(self):
        fake = types.SimpleNamespace(LoraLoaderModelOnly=NativeLoraContract)
        with patch.dict(sys.modules, {"nodes": fake}):
            apply = self.nodes.H3MAXMotionPreset().apply
            self.assertEqual(apply("m", "scene", "acao_com_arma", 1, False, .65, False, .8)[1], "BUNNY\n\nscene")
            self.assertEqual(apply("m", "BUNNY scene", "acao_com_arma", 1, False, .65, False, .8)[1], "BUNNY scene")
            self.assertEqual(apply("m", "scene", "acao_com_arma", 0, False, .65, False, .8)[1], "scene")


def video_info():
    # Shape published by the pinned V3 SaveVideo DynamicCombo schema.
    codec = ["COMFY_DYNAMICCOMBO_V3", {"options": [{"key": "auto", "inputs": {}}]}]
    return {
        "CreateVideo": {"input": {"required": {}}, "output": ["VIDEO"]},
        "SaveVideo": {"input": {"required": {
            "video": ["VIDEO"], "filename_prefix": ["STRING"],
            "format": ["COMFY_DYNAMICCOMBO_V3", {"options": [
                {"key": "auto", "inputs": {"required": {"codec": codec}}}]}]},
            "optional": {"codec": codec}}, "output": ["VIDEO"]},
    }


def video_prompt():
    return {"1": {"class_type": "CreateVideo", "inputs": {}},
            "2": {"class_type": "SaveVideo", "inputs": {"video": ["1", 0], "filename_prefix": "test", "format": "auto", "format.codec": "auto"}}}


class RuntimeSchemaTests(unittest.TestCase):
    def test_pinned_save_video_contract_accepts_nested_codec(self):
        runtime.validate_prompt_schema(video_prompt(), video_info())

    def test_legacy_codec_cannot_replace_required_nested_codec(self):
        prompt = video_prompt()
        prompt["2"]["inputs"]["codec"] = prompt["2"]["inputs"].pop("format.codec")
        with self.assertRaisesRegex(RuntimeError, "missing required input format.codec"):
            runtime.validate_prompt_schema(prompt, video_info())

    def test_wrong_output_type_and_slot_fail(self):
        for slot in (0, -1, 5):
            prompt, info = video_prompt(), video_info()
            prompt["2"]["inputs"]["video"][1] = slot
            info["CreateVideo"]["output"] = ["IMAGE"]
            with self.assertRaises(RuntimeError):
                runtime.validate_prompt_schema(prompt, info)

    def test_nodes_only_skips_files_but_not_invalid_sampler(self):
        info = {"UNETLoader": {"input": {"required": {"unet_name": [[]], "weight_dtype": [["default"]]}}, "output": ["MODEL"]}}
        prompt = {"1": {"class_type": "UNETLoader", "inputs": {"unet_name": "missing.safetensors", "weight_dtype": "default"}}}
        runtime.validate_prompt_schema(prompt, info, nodes_only=True)
        with self.assertRaisesRegex(RuntimeError, "unavailable choice"):
            runtime.validate_prompt_schema(prompt, info)
        prompt["1"]["inputs"]["weight_dtype"] = "not-supported"
        with self.assertRaisesRegex(RuntimeError, "weight_dtype"):
            runtime.validate_prompt_schema(prompt, info, nodes_only=True)

    def test_reference_autogrow_contract_has_bounds(self):
        schema = {"optional": {"ref_images": ["COMFY_AUTOGROW_V3", {"template": {
            "prefix": "ref_image_", "min": 0, "max": 9, "input": {"required": {"ref_image": ["IMAGE"]}}}}]}}
        expanded = runtime.expand_inputs(schema, {})
        self.assertEqual(expanded["ref_images.ref_image_0"], (False, ["IMAGE"]))
        self.assertNotIn("ref_images.ref_image_9", expanded)

    def test_smoke_keeps_dilated_length_link(self):
        prompt = json.loads((ROOT / "api_prompts/07_H3_MAX_TEXTO_DEROPE.json").read_text(encoding="utf-8"))
        original = copy.deepcopy(prompt)
        smoke = runtime.smoke_prompt(prompt, profile="base")
        self.assertEqual(prompt, original)
        conditioning = [n for n in smoke.values() if n["class_type"] == "MiniMaxH3ImageToVideo"]
        self.assertEqual(conditioning[0]["inputs"]["length"], 39)
        self.assertIsInstance(conditioning[1]["inputs"]["length"], list)
        self.assertTrue(all(n["inputs"]["profile"] == "base" for n in smoke.values() if n["class_type"] == "H3MAXMotionPreset"))

    def test_image_smoke_requires_actual_input_names(self):
        prompt = {"1": {"class_type": "LoadImage", "inputs": {"image": "placeholder.png"}}}
        with self.assertRaisesRegex(ValueError, "needs 1"):
            runtime.smoke_prompt(prompt)
        self.assertEqual(runtime.smoke_prompt(prompt, ["uploaded.png"])["1"]["inputs"]["image"], "uploaded.png")

    def test_success_needs_saved_file_metadata(self):
        self.assertEqual(list(runtime.saved_files({})), [])
        metadata = {"filename": "clip.mp4", "subfolder": "H3_MAX", "type": "output"}
        self.assertEqual(list(runtime.saved_files({"1": {"images": [metadata]}})), [metadata])


class InstalledPackGateTests(unittest.TestCase):
    def pack_info(self):
        lock = json.loads((ROOT / 'sources.lock.json').read_text(encoding='utf-8'))
        directories = [spec['directory'] for spec in lock['custom_nodes']] + ['ComfyUI-H3MAX']
        return {name: {'python_module': 'custom_nodes.' + name} for name in directories}

    def test_every_installed_pack_is_reported_even_when_unused(self):
        info = self.pack_info()
        report = runtime.validate_pack_registration(info, workflow_types=['ComfyUI-H3MAX'])
        self.assertEqual(len(report), 8)
        self.assertTrue(all(row['registered_node_count'] == 1 for row in report.values()))
        self.assertEqual(report['ComfyUI-H3MAX']['workflow_node_count'], 1)
        self.assertEqual(report['ComfyUI-VideoHelperSuite']['workflow_node_count'], 0)

    def test_unused_pack_import_failure_is_not_hidden_by_workflow_coverage(self):
        info = self.pack_info()
        del info['ComfyUI-VideoHelperSuite']
        with self.assertRaisesRegex(RuntimeError, 'ComfyUI-VideoHelperSuite'):
            runtime.validate_pack_registration(info, workflow_types=['ComfyUI-H3MAX'])

    def test_similar_module_name_cannot_satisfy_missing_pack(self):
        info = self.pack_info()
        info['ComfyUI-KJNodes']['python_module'] += '-different-pack'
        with self.assertRaisesRegex(RuntimeError, 'ComfyUI-KJNodes'):
            runtime.validate_pack_registration(info)

    def test_compiler_gate_imports_and_reads_contract_without_compiling(self):
        compile_brief = unittest.mock.Mock()
        contract = unittest.mock.Mock(return_value={'contract_version': 'test-contract'})
        modules = {'h3ir.compile': types.SimpleNamespace(compile_brief=compile_brief),
                   'h3ir.contract': types.SimpleNamespace(contract=contract)}
        with patch.object(check_image.importlib, 'import_module', side_effect=modules.__getitem__):
            report = check_image.check_local_compiler()
        self.assertTrue(report['compiler_import_verified'])
        self.assertTrue(report['compiler_contract_verified'])
        self.assertFalse(report['director_request_executed'])
        compile_brief.assert_not_called()
        contract.assert_called_once_with()

    def test_compiler_gate_refuses_broken_import_and_missing_contract(self):
        with patch.object(check_image.importlib, 'import_module', side_effect=ImportError('missing dependency')):
            with self.assertRaisesRegex(ImportError, 'missing dependency'):
                check_image.check_local_compiler()
        modules = {'h3ir.compile': types.SimpleNamespace(compile_brief=lambda: None),
                   'h3ir.contract': types.SimpleNamespace(contract=lambda: {})}
        with patch.object(check_image.importlib, 'import_module', side_effect=modules.__getitem__):
            with self.assertRaisesRegex(RuntimeError, 'valid local contract'):
                check_image.check_local_compiler()


if __name__ == "__main__":
    unittest.main()
