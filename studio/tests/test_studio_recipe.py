"""Studio routing, media preservation and native graph contract regressions.

These tests do not make claims about GPU inference or perceptual quality.
"""
import ast
import copy
import hashlib
import importlib.util
import itertools
import json
import os
from pathlib import Path
import types
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "studio_recipe_test", ROOT / "custom_nodes/ComfyUI-H3MAX/studio_recipe.py")
recipe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(recipe)

# Return-port counts from the pinned native/custom node schemas. In particular,
# conditioning is port 0, AV latent 1; TimeSmear map 1 and resulting frame count 2.
PORTS = {
    "UNETLoader": 1, "MiniMaxH3HybridLoader": 1, "CLIPLoader": 1, "VAELoader": 1,
    "H3MAXDirectorText": 1, "H3MAXMotionPreset": 2, "LoadImage": 2,
    "H3MAXReferenceVideo": 2, "LoadAudio": 1, "MiniMaxH3ImageToVideo": 2,
    "MiniMaxH3ReferenceToVideo": 2, "KSamplerSelect": 1, "RandomNoise": 1,
    "BasicGuider": 1, "SamplerCustomAdvanced": 2, "BasicScheduler": 1,
    "VAEDecodeAudio": 1, "VAEDecode": 1, "H3JerkOracle": 6, "H3TimeSmear": 4,
    "VAEEncode": 1, "H3AudioSmear": 1, "VAEEncodeAudio": 1, "H3V2VInit": 1,
    "H3InjectSchedule": 1, "MinimaxH3LatentUpscaler3DRefineHandoff": 1,
    "H3ExactRecover": 1, "CreateVideo": 1, "SaveVideo": 1,
}

# Canonical UTF-8/LF SHA256 checked against the public URLs at sources.lock.json
# revisions on 2026-09-23. Fail closed if a local audit cache silently drifts.
PINNED_SOURCE_HASHES = {
    "nodes.py": "1af4a41e1d844550a836cf1d1b00fad85d3d0aefaf435743431a8f1598643e22",
    "nodes_minimax_h3.py": "108ceff11e5a5c9a34a57bbc380447cf9941beb673a1bd421abc818de54ccd5c",
    "nodes_custom_sampler.py": "b0ba1521c72475e06fed15db004274ed7c8bb2bf73f1d58849faf6f9f9d264fe",
    "nodes_audio.py": "897429f8a08be406486beceb39a250c5c206a1162dce868003c93df80dd01887",
    "nodes_video.py": "5879633287808ba2dac6753bcbc90acf8d73c72e8df1d0a9755a4ab70e712a0d",
    "minimaxh3.py": "b5a2021b12d7aaa6a0a3048ce7d9941172ca21a20185adc74f7e8d0ab0ee3b0c",
    "motion.py": "98b61b0a25d72ad17778b31bb3034b1b930fffcf367e19d4ea8917f5b1a0b353",
    "minimax_h3_refine.py": "2322365333a626b8e5fe844bf974c0a1caf655ad95f4c1c2a4292b1bafa8ee95",
    "minimax_h3_latent_upscaler_3d.py": "98ae75ea63b082d2e5d51a7cf47ebca1b25b544c5364b71f372e46838b015061",
}


class _SchemaPort:
    """Record actual upstream declarations; never import or run model code."""
    def __init__(self, kind):
        self.kind = kind

    def Input(self, name, **options):
        optional = options.pop("optional", False)
        kind = options.pop("options") if self.kind == "COMBO" else self.kind
        return name, (kind, options), optional

    def Output(self, *args, **kwargs):
        return self.kind


def _input_dict(inputs):
    schema = {"required": {}, "optional": {}}
    for name, spec, optional in inputs:
        schema["optional" if optional else "required"][name] = spec
    return schema


class _DynamicCombo(_SchemaPort):
    def __init__(self):
        super().__init__("COMFY_DYNAMICCOMBO_V3")

    @staticmethod
    def Option(key, inputs):
        return {"key": key, "inputs": _input_dict(inputs)}


class _Autogrow(_SchemaPort):
    def __init__(self):
        super().__init__("COMFY_AUTOGROW_V3")

    @staticmethod
    def TemplatePrefix(input, prefix, min, max):
        return {"input": _input_dict([input]), "prefix": prefix, "min": min, "max": max}


def _source_schemas(source_dir):
    """Evaluate only source schema methods against a recording IO facade.

    Uses the actual pinned source bodies for names, mandatory/optional inputs,
    bounds, choices, dynamic nesting and output port types. File availability
    and runtime sampler registries remain the real /object_info check's job.
    """
    io = types.SimpleNamespace(**{
        name: _SchemaPort(name.upper()) for name in
        ("Model", "Clip", "Vae", "String", "Int", "Float", "Boolean", "Image",
         "Audio", "Video", "Conditioning", "Latent", "Noise", "Guider", "Sampler", "Sigmas", "Combo")
    })
    io.DynamicCombo, io.Autogrow = _DynamicCombo(), _Autogrow()
    io.Hidden = types.SimpleNamespace(prompt="prompt", extra_pnginfo="extra_pnginfo")
    io.UploadType = types.SimpleNamespace(audio="audio", video="video", image="image")
    io.Schema = lambda inputs, outputs, **kwargs: {"input": _input_dict(inputs), "output": outputs}
    folder_paths = types.SimpleNamespace(
        get_filename_list=lambda folder: [], get_input_directory=lambda: ".",
        filter_files_content_types=lambda files, kinds: files)
    fake_os = types.SimpleNamespace(path=os.path, listdir=lambda path: [], makedirs=lambda *a, **k: None)
    global_tree = ast.parse((source_dir / "nodes.py").read_text(encoding="utf-8"))
    max_resolution = next(ast.literal_eval(n.value) for n in global_tree.body
                          if isinstance(n, ast.Assign)
                          and any(isinstance(t, ast.Name) and t.id == "MAX_RESOLUTION" for t in n.targets))
    scope = {
        "io": io, "IO": io, "os": fake_os, "folder_paths": folder_paths,
        "nodes": types.SimpleNamespace(MAX_RESOLUTION=max_resolution),
        "comfy": types.SimpleNamespace(samplers=types.SimpleNamespace(
            SCHEDULER_NAMES=["simple"], SAMPLER_NAMES=["res_multistep"])),
        "Types": types.SimpleNamespace(VideoCodec=types.SimpleNamespace(as_input=lambda: ["auto", "h264", "av1"])),
        "_profile_ids": lambda: ["minimax-h3"],
        "_scan_models": lambda: [], "_diffusion_model_filenames": lambda: [],
    }
    # Read the sizing labels from their actual Enum body, not our recipe.
    upscale_tree = ast.parse((source_dir / "minimax_h3_latent_upscaler_3d.py").read_text(encoding="utf-8"))
    enum = next(n for n in upscale_tree.body if isinstance(n, ast.ClassDef) and n.name == "UpscaleMode")
    modes = tuple(ast.literal_eval(n.value) for n in enum.body if isinstance(n, ast.Assign))
    scope["_upscale_modes"] = lambda: modes
    sources = {
        source_dir / "nodes.py": ["UNETLoader", "CLIPLoader", "VAELoader", "LoadImage", "VAEDecode", "VAEEncode"],
        source_dir / "nodes_minimax_h3.py": ["MiniMaxH3ImageToVideo", "MiniMaxH3ReferenceToVideo"],
        source_dir / "nodes_custom_sampler.py": ["RandomNoise", "BasicScheduler", "KSamplerSelect", "BasicGuider", "SamplerCustomAdvanced"],
        source_dir / "nodes_audio.py": ["LoadAudio", "VAEDecodeAudio", "VAEEncodeAudio"],
        source_dir / "nodes_video.py": ["CreateVideo", "SaveVideo"],
        source_dir / "minimaxh3.py": ["MiniMaxH3HybridLoader"],
        source_dir / "motion.py": ["H3JerkOracle", "H3TimeSmear", "H3AudioSmear", "H3V2VInit", "H3InjectSchedule", "H3ExactRecover"],
        source_dir / "minimax_h3_refine.py": ["MinimaxH3LatentUpscaler3DRefine"],
        ROOT / "custom_nodes/ComfyUI-H3MAX/__init__.py": ["H3MAXMotionPreset", "H3MAXDirectorText"],
        ROOT / "custom_nodes/ComfyUI-H3MAX/studio_media.py": ["H3MAXReferenceVideo"],
    }
    schemas = {}
    for source, names in sources.items():
        tree = ast.parse(source.read_text(encoding="utf-8"))
        # Only scalar/literal constants; no imports or top-level source calls.
        for item in tree.body:
            if isinstance(item, (ast.Assign, ast.AnnAssign)):
                targets = item.targets if isinstance(item, ast.Assign) else [item.target]
                try:
                    value = ast.literal_eval(item.value)
                except (ValueError, TypeError):
                    continue
                for target in targets:
                    if isinstance(target, ast.Name):
                        scope[target.id] = value
        if source.name == "minimaxh3.py":
            presets = next(n.value for n in tree.body if isinstance(n, ast.AnnAssign)
                           and isinstance(n.target, ast.Name) and n.target.id == "PRESETS")
            scope["PRESET_LIST"] = [ast.literal_eval(key) for key in presets.keys]
        for item in tree.body:
            if isinstance(item, ast.FunctionDef) and item.name in ("_cost_widgets", "_save_video_codec_input"):
                exec(compile(ast.Module(body=[item], type_ignores=[]), str(source), "exec"), scope)
        for item in tree.body:
            if not isinstance(item, ast.ClassDef) or item.name not in names:
                continue
            retained = []
            for member in item.body:
                if isinstance(member, ast.Assign):
                    try:
                        ast.literal_eval(member.value)
                    except (ValueError, TypeError):
                        continue
                    retained.append(member)
                elif isinstance(member, ast.FunctionDef) and member.name in ("INPUT_TYPES", "define_schema", "vae_list"):
                    retained.append(member)
            declaration = ast.ClassDef(name=item.name, bases=[], keywords=[], body=retained, decorator_list=[])
            module = ast.fix_missing_locations(ast.Module(body=[declaration], type_ignores=[]))
            exec(compile(module, str(source), "exec"), scope)
            cls = scope[item.name]
            if hasattr(cls, "define_schema"):
                schemas[item.name] = cls.define_schema()
            else:
                schemas[item.name] = {"input": cls.INPUT_TYPES(), "output": list(cls.RETURN_TYPES)}
    schemas["MinimaxH3LatentUpscaler3DRefineHandoff"] = schemas.pop("MinimaxH3LatentUpscaler3DRefine")
    return schemas


def nodes(result, name):
    return [(key, node["inputs"]) for key, node in result["prompt"].items()
            if node["class_type"] == name]


class StudioRecipeTests(unittest.TestCase):
    def build(self, **kwargs):
        return recipe.compile_request({"prompt": "Uma pessoa senta em uma cadeira.", "seed": 42, **kwargs})

    def assert_graph(self, result):
        graph = result["prompt"]
        outputs = nodes(result, "SaveVideo")
        refined = any(stage in result["summary"]["stages"] for stage in ("refine", "temporal"))
        self.assertEqual(len(outputs), 2 if refined else 1,
                         "Preserve the base only when producing a refined final video")
        self.assertEqual(result["summary"]["outputs"], ["base", "final"] if refined else ["final"])
        dependencies = {}
        for key, node in graph.items():
            self.assertIn(node["class_type"], PORTS)
            dependencies[key] = set()
            for value in node["inputs"].values():
                if not isinstance(value, list):
                    continue
                self.assertEqual(len(value), 2)
                source, port = value
                self.assertIn(source, graph)
                self.assertIs(type(port), int)
                self.assertGreaterEqual(port, 0)
                self.assertLess(port, PORTS[graph[source]["class_type"]])
                self.assertLess(int(source), int(key), "Graph must be topologically ordered")
                dependencies[key].add(source)
        reached = set()

        def visit(key):
            reached.add(key)
            for source in dependencies[key]:
                if source not in reached:
                    visit(source)

        for output_id, _ in outputs:
            visit(output_id)
        self.assertEqual(reached, set(graph), "No ignored uploads or dead processing branches")

    def test_auto_routes_text_keyframes_and_all_reference_kinds(self):
        text = self.build(motion=False)
        keyframes = self.build(first_frame="studio/start.png", last_frame="studio/end.png")
        refs = self.build(references=["person.png"], video_references=["motion.mp4"],
                          audio_references=["voice.wav"])
        self.assertEqual(text["summary"]["engine"], "fl2va")
        self.assertEqual(keyframes["summary"]["engine"], "fl2va")
        self.assertEqual(refs["summary"]["engine"], "ref2va")
        inputs = nodes(keyframes, "MiniMaxH3ImageToVideo")[0][1]
        self.assertIn("first_frame", inputs)
        self.assertIn("last_frame", inputs)
        ref_inputs = nodes(refs, "MiniMaxH3ReferenceToVideo")[0][1]
        media_id = nodes(refs, "H3MAXReferenceVideo")[0][0]
        self.assertEqual(ref_inputs["ref_videos.ref_video_0"], [media_id, 0])
        self.assertEqual(ref_inputs["ref_video_audios.ref_video_audio_0"], [media_id, 1])
        self.assertIn("ref_images.ref_image_0", ref_inputs)
        self.assertIn("ref_audios.ref_audio_0", ref_inputs)
        for result in (text, keyframes, refs):
            self.assert_graph(result)

    def test_nine_images_and_three_videos_keep_all_dynamic_slots(self):
        result = self.build(references=[f"image{i}.png" for i in range(9)],
                            video_references=[f"video{i}.mp4" for i in range(3)])
        inputs = nodes(result, "MiniMaxH3ReferenceToVideo")[0][1]
        self.assertEqual(sum(key.startswith("ref_images.") for key in inputs), 9)
        self.assertEqual(sum(key.startswith("ref_videos.") for key in inputs), 3)
        self.assertEqual(sum(key.startswith("ref_video_audios.") for key in inputs), 3)
        self.assert_graph(result)

    def test_toggle_matrix_produces_connected_graphs_for_each_engine(self):
        for engine in ("fl2va", "ref2va", "hybrid"):
            for switches in itertools.product((False, True), repeat=5):
                motion, people, camera, refine, temporal = switches
                assets = {"first_frame": "first.png"} if engine == "fl2va" else {"references": ["person.png"]}
                if engine == "fl2va" and not temporal:
                    assets["last_frame"] = "last.png"
                with self.subTest(engine=engine, switches=switches):
                    result = self.build(model=engine, motion=motion, people_realism=people,
                                        camera_motion=camera, refine=refine, temporal=temporal, **assets)
                    self.assert_graph(result)
                    self.assertEqual(bool(nodes(result, "H3MAXMotionPreset")), motion or people or camera)
                    self.assertEqual(bool(nodes(result, "H3JerkOracle")), temporal)
                    self.assertEqual(bool(nodes(result, "H3ExactRecover")), temporal)
                    self.assertEqual(bool(nodes(result, "MinimaxH3LatentUpscaler3DRefineHandoff")), refine)
                    self.assertFalse(nodes(result, "H3MAXDirectorText"))

    def test_second_pass_keeps_scene_appearance_and_reduces_only_natural_motion(self):
        for scene, profile in recipe.PROFILES.items():
            extra = {} if scene == "weapon" else {"people_realism": True, "camera_motion": True}
            result = self.build(scene=scene, motion=True, temporal=True, refine=True, **extra)
            first, second = [item[1] for item in nodes(result, "H3MAXMotionPreset")]
            self.assertEqual(first["model"], second["model"], "Never stack the second preset onto the first")
            self.assertEqual(first["profile"], profile)
            self.assertEqual(second["profile"], profile)
            self.assertEqual(second["people_realism"], first["people_realism"])
            self.assertEqual(second["camera_motion"], first["camera_motion"])
            self.assertAlmostEqual(second["motion_multiplier"], 0.25 / 0.9 if scene == "natural" else 1)

    def test_temporal_refine_preserves_original_audio_and_recovers_after_refine(self):
        result = self.build(temporal=True, refine=True, duration=10, aspect="9:16", first_frame="start.png")
        video = nodes(result, "CreateVideo")[-1][1]
        original_audio_id, original_audio = nodes(result, "VAEDecodeAudio")[0]
        first_sampler_id = nodes(result, "SamplerCustomAdvanced")[0][0]
        self.assertEqual(original_audio["samples"], [first_sampler_id, 0])
        self.assertEqual(video["audio"], [original_audio_id, 0])
        refine_id = nodes(result, "MinimaxH3LatentUpscaler3DRefineHandoff")[0][0]
        recover_id, recovery = nodes(result, "H3ExactRecover")[0]
        final_decode = result["prompt"][recovery["images"][0]]["inputs"]
        self.assertEqual(final_decode["samples"], [refine_id, 0])
        self.assertEqual(video["images"], [recover_id, 0])
        smear_id = nodes(result, "H3TimeSmear")[0][0]
        second_conditioning = nodes(result, "MiniMaxH3ImageToVideo")[1][1]
        self.assertEqual(second_conditioning["length"], [smear_id, 2])
        self.assertIn("first_frame", second_conditioning)
        self.assertEqual(result["summary"]["stages"], ["generate", "temporal", "refine", "recover"])
        self.assert_graph(result)

    def test_comparison_saves_original_once_and_shares_original_audio(self):
        for refine, temporal in itertools.product((False, True), repeat=2):
            with self.subTest(refine=refine, temporal=temporal):
                result = self.build(refine=refine, temporal=temporal)
                saves = nodes(result, "SaveVideo")
                expected = ["base", "final"] if refine or temporal else ["final"]
                self.assertEqual(result["summary"]["outputs"], expected)
                self.assertEqual([value["filename_prefix"] for _, value in saves],
                                 [f"H3_MAX/Studio/42_{label}" for label in expected])
                audio = nodes(result, "VAEDecodeAudio")
                self.assertEqual(len(audio), 1)
                videos = [result["prompt"][save["video"][0]]["inputs"] for _, save in saves]
                self.assertTrue(all(video["audio"] == [audio[0][0], 0] for video in videos))
                first_sampler = nodes(result, "SamplerCustomAdvanced")[0][0]
                base_decodes = [(key, value) for key, value in nodes(result, "VAEDecode")
                                if value["samples"] == [first_sampler, 0]]
                self.assertEqual(len(base_decodes), 1, "Decode the original generation exactly once")
                self.assertEqual(videos[0]["images"], [base_decodes[0][0], 0])
                if temporal:
                    self.assertEqual(nodes(result, "H3TimeSmear")[0][1]["images"],
                                     [base_decodes[0][0], 0])
                self.assert_graph(result)

    def test_real_dimensions_duration_and_seed_propagate_without_manual_sync(self):
        for aspect, duration, refine in itertools.product(recipe.BASE_SIZE, (5, 10), (False, True)):
            result = self.build(aspect=aspect, duration=duration, refine=refine, director=True,
                                seed=recipe.MAX_SEED)
            summary = result["summary"]
            self.assertEqual((summary["frames"] - 5) % 17, 0)
            self.assertEqual(summary["seconds"], summary["frames"] / 24)
            expected = (recipe.REFINE_SIZE if refine else recipe.BASE_SIZE)[aspect]
            self.assertEqual((summary["width"], summary["height"]), expected)
            director = nodes(result, "H3MAXDirectorText")[0][1]
            self.assertEqual(director["seconds"], summary["seconds"])
            self.assertEqual(director["aspect"], aspect)
            self.assertEqual(director["seed"], summary["seed"])
            for _, noise in nodes(result, "RandomNoise"):
                self.assertTrue(0 <= noise["noise_seed"] <= recipe.MAX_SEED)

    def test_off_means_no_extra_models_and_objects_experiment_requires_opt_in(self):
        result = self.build(motion=False)
        self.assertEqual(len(result["required_models"]), 4)
        self.assertFalse(any(item["folder"] == "loras" for item in result["required_models"]))
        self.assertFalse(nodes(result, "H3MAXMotionPreset"))
        objects = self.build(scene="objects")
        self.assertEqual(objects["summary"]["profile"], "base")
        enabled = self.build(scene="objects", motion=True)
        self.assertEqual(enabled["summary"]["profile"], "objetos_experimental")
        self.assertTrue(any("experimental" in note for note in enabled["summary"]["notes"]))

    def test_all_required_weights_are_real_manifest_entries(self):
        manifest = json.loads((ROOT / "models.lock.json").read_text(encoding="utf-8"))
        available = {item["destination"] for item in manifest["models"]}
        for scene in recipe.PROFILES:
            for engine in ("fl2va", "ref2va", "hybrid"):
                assets = {} if engine == "fl2va" else {"references": ["person.png"]}
                result = self.build(scene=scene, motion=True, model=engine, refine=True, **assets)
                for item in result["required_models"]:
                    self.assertIn(f"models/{item['folder']}/{item['filename']}", available)

    def test_incompatible_features_are_rejected_never_dropped(self):
        invalid = [
            {"references": ["r.png"], "first_frame": "f.png"},
            {"references": ["r.png"], "last_frame": "l.png"},
            {"model": "fl2va", "references": ["r.png"]},
            {"model": "ref2va"}, {"model": "hybrid"},
            {"audio_references": ["voice.wav"]},
            {"references": ["r.png"], "director": True},
            {"last_frame": "end.png", "temporal": True},
            {"scene": "weapon", "motion": True, "camera_motion": True},
            {"scene": "weapon", "motion": True, "people_realism": True},
            {"references": [f"r{i}.png" for i in range(10)]},
            {"references": ["r.png"], "video_references": ["v.mp4"] * 4},
            {"references": ["r.png"] * 9, "video_references": ["v.mp4"] * 3,
             "audio_references": ["a.wav"]},
        ]
        for values in invalid:
            with self.subTest(values=values), self.assertRaises(recipe.RecipeError):
                self.build(**values)

    def test_untrusted_paths_and_invalid_types_fail_before_compiling(self):
        for path in ("../a.png", "dir/../a.png", "dir/./a.png", "/tmp/a.png", "C:/a.png",
                     "https://x/a.png", "a.png [output]", "a.png\n", "a.png;run",
                     "$(cmd).png", "a`cmd`.png", "x\\a.png", "dir//a.png", "a%2f.png"):
            with self.subTest(path=path), self.assertRaises(recipe.RecipeError):
                self.build(first_frame=path)
        invalid = [{"prompt": ""}, {"prompt": []}, {"duration": True}, {"duration": 5.0},
                   {"duration": 20}, {"seed": True}, {"seed": -1}, {"seed": recipe.MAX_SEED + 1},
                   {"motion": "false"}, {"model": []}, {"references": "r.png"},
                   {"references": [None]}, {"tempral": True}, {"pose": True}]
        for values in invalid:
            with self.subTest(values=values), self.assertRaises(recipe.RecipeError):
                self.build(**values)

    def test_request_is_unchanged_and_explicit_seed_is_reproducible(self):
        request = {"prompt": "Cena", "seed": 99, "references": ["person.png"], "refine": True}
        before = copy.deepcopy(request)
        first = recipe.compile_request(request)
        self.assertEqual(request, before)
        self.assertEqual(first, recipe.compile_request(request))
        with patch.object(recipe.secrets, "randbits", return_value=123):
            self.assertEqual(recipe.compile_request({"prompt": "Cena"})["summary"]["seed"], 123)

    def test_default_camera_preserves_pre_camera_graphs_for_all_engines(self):
        # Captured before adding camera controls, with deterministic seeds.
        expected_hashes = {
            "fl2va": "64b440fc39bb7e23432b0364d315c7d1ba8e638fbadc008c0a6d045685c89fe4",
            "ref2va": "8042960c9b20255ddb98228af44ae16ddc03d05f69acf224a0f4a40f9fbc7c63",
            "hybrid": "6c1efedd207d37cf636584176b9491c742d7633aa49ad51dad03b0356376aa50",
        }
        for engine, expected in expected_hashes.items():
            with self.subTest(engine=engine):
                settings = {"prompt": "Cena de teste", "seed": 42, "model": engine,
                            "refine": True, "temporal": True}
                if engine != "fl2va":
                    settings["references"] = ["person.png"]
                default = recipe.compile_request(settings)
                digest = hashlib.sha256(json.dumps(default["prompt"], sort_keys=True,
                                                    separators=(",", ":")).encode()).hexdigest()
                self.assertEqual(digest, expected)
                explicit = recipe.compile_request({**settings, "camera": "auto",
                    "camera_speed": "fast", "camera_amount": "wide"})
                self.assertEqual(explicit["prompt"], default["prompt"])
                self.assertEqual(explicit["required_models"], default["required_models"])
                self.assertEqual(default["summary"]["camera"], "auto")

    def test_camera_directions_reach_every_engine_without_extra_nodes_or_weights(self):
        for engine, camera in itertools.product(("fl2va", "ref2va", "hybrid"), recipe.CAMERA_PRESETS):
            with self.subTest(engine=engine, camera=camera):
                assets = {} if engine == "fl2va" else {"references": ["person.png"]}
                baseline = self.build(model=engine, motion=False, **assets)
                result = self.build(model=engine, motion=False, camera=camera, **assets)
                self.assertEqual(result["required_models"], baseline["required_models"])
                self.assertEqual([n["class_type"] for n in result["prompt"].values()],
                                 [n["class_type"] for n in baseline["prompt"].values()])
                kind = "MiniMaxH3ImageToVideo" if engine == "fl2va" else "MiniMaxH3ReferenceToVideo"
                prompt = nodes(result, kind)[0][1]["prompt"]
                self.assertTrue(prompt.startswith("Uma pessoa senta em uma cadeira."))
                if camera == "auto":
                    self.assertEqual(prompt, "Uma pessoa senta em uma cadeira.")
                else:
                    self.assertIn("The camera ", prompt)
                self.assertEqual(result["summary"]["camera"], camera)
                self.assertTrue(result["summary"]["camera_label"])
                self.assert_graph(result)

    def test_camera_direction_stays_in_both_passes_with_or_without_motion_preset(self):
        for engine, motion in itertools.product(("fl2va", "ref2va", "hybrid"), (False, True)):
            assets = {} if engine == "fl2va" else {"references": ["person.png"]}
            result = self.build(model=engine, camera="push_in", motion=motion,
                                refine=True, temporal=True, **assets)
            kind = "MiniMaxH3ImageToVideo" if engine == "fl2va" else "MiniMaxH3ReferenceToVideo"
            conditions = nodes(result, kind)
            self.assertEqual(len(conditions), 2)
            for _, condition in conditions:
                text = condition["prompt"]
                if motion:
                    preset = result["prompt"][text[0]]
                    self.assertEqual(preset["class_type"], "H3MAXMotionPreset")
                    self.assertEqual(text[1], 1)
                    text = preset["inputs"]["prompt"]
                self.assertIn("The camera pushes in with small amplitude at slow speed", text)
            self.assert_graph(result)

    def test_camera_direction_enters_director_once_and_is_shared_by_both_presets(self):
        request = {"prompt": "A person walks.", "seed": 84, "camera": "pan_right",
                   "camera_speed": "fast", "camera_amount": "wide", "director": True,
                   "motion": True, "refine": True, "temporal": True}
        original = copy.deepcopy(request)
        result = recipe.compile_request(request)
        self.assertEqual(request, original)
        director_id, director = nodes(result, "H3MAXDirectorText")[0]
        self.assertEqual(director["prompt"],
                         "A person walks.\n\nThe camera pans right with large amplitude at fast speed from a fixed position.")
        presets = nodes(result, "H3MAXMotionPreset")
        self.assertEqual(len(presets), 2)
        self.assertTrue(all(preset["prompt"] == [director_id, 0] for _, preset in presets))
        self.assertEqual(result["summary"]["camera_speed"], "fast")
        self.assertEqual(result["summary"]["camera_amount"], "wide")

    def test_camera_amplitude_and_speed_are_natural_text_and_static_ignores_them(self):
        normal = self.build(camera="pull_out", camera_amount="medium", camera_speed="normal", motion=False)
        text = nodes(normal, "MiniMaxH3ImageToVideo")[0][1]["prompt"]
        self.assertTrue(text.endswith("The camera pulls out away from the main subject."))
        self.assertNotIn("amplitude", text)
        self.assertNotIn("speed", text)
        fixed = self.build(camera="locked", motion=False)
        changed = self.build(camera="locked", camera_amount="wide", camera_speed="fast", motion=False)
        self.assertEqual(fixed["prompt"], changed["prompt"])
        self.assertEqual(changed["summary"]["camera_speed"], "fast")
        self.assertEqual(changed["summary"]["camera_amount"], "wide")
        self.assertIn("static shot", nodes(fixed, "MiniMaxH3ImageToVideo")[0][1]["prompt"])

    def test_invalid_camera_options_and_fixed_camera_lora_conflict_fail_early(self):
        invalid = [{"camera": value} for value in (None, True, [], "zoom", "PAN_LEFT", "")]
        invalid += [{"camera_speed": value} for value in (None, True, "turbo", "")]
        invalid += [{"camera_amount": value} for value in (None, 0.5, "extreme", "")]
        invalid += [{"camera": "locked", "camera_motion": True}]
        for settings in invalid:
            with self.subTest(settings=settings), self.assertRaises(recipe.RecipeError):
                self.build(**settings)

    def test_framing_reaches_director_and_conditioning_without_rewriting_user_request(self):
        for framing in recipe.FRAMING_PRESETS:
            request = {"prompt": "A person sits.", "seed": 12, "framing": framing, "motion": False}
            original = copy.deepcopy(request)
            direct = recipe.compile_request(request)
            directed = recipe.compile_request({**request, "director": True})
            direct_text = nodes(direct, "MiniMaxH3ImageToVideo")[0][1]["prompt"]
            director_id, director = nodes(directed, "H3MAXDirectorText")[0]
            self.assertEqual(direct_text, director["prompt"])
            self.assertEqual(nodes(directed, "MiniMaxH3ImageToVideo")[0][1]["prompt"], [director_id, 0])
            self.assertEqual(request, original)
            self.assertEqual(direct["summary"]["framing"], framing)
            if framing == "auto":
                self.assertEqual(direct_text, request["prompt"])
            else:
                self.assertIn(recipe.FRAMING_PRESETS[framing], direct_text)

    def test_silent_export_omits_both_soundtracks_and_keeps_only_needed_audio_nodes(self):
        for engine, temporal, refine in itertools.product(("fl2va", "ref2va", "hybrid"), (False, True), (False, True)):
            with self.subTest(engine=engine, temporal=temporal, refine=refine):
                assets = {} if engine == "fl2va" else {"references": ["person.png"], "audio_references": ["voice.wav"]}
                result = self.build(model=engine, output_audio=False, temporal=temporal, refine=refine, **assets)
                videos = nodes(result, "CreateVideo")
                self.assertEqual(len(videos), 2 if temporal or refine else 1)
                self.assertTrue(all("audio" not in values for _, values in videos))
                decoded = nodes(result, "VAEDecodeAudio")
                self.assertEqual(bool(decoded), temporal)
                audio_vae_nodes = [(key, values) for key, values in nodes(result, "VAELoader")
                                   if values["vae_name"] == recipe.MODELS["audio_vae"][1]]
                self.assertEqual(bool(audio_vae_nodes), temporal or engine != "fl2va")
                if temporal:
                    self.assertEqual(nodes(result, "H3AudioSmear")[0][1]["audio"], [decoded[0][0], 0])
                self.assertFalse(result["summary"]["output_audio"])
                self.assert_graph(result)

    def test_default_audio_export_is_unchanged_and_invalid_control_types_fail(self):
        implicit = self.build(temporal=True, refine=True)
        explicit = self.build(temporal=True, refine=True, output_audio=True, framing="auto")
        self.assertEqual(implicit, explicit)
        self.assertTrue(explicit["summary"]["output_audio"])
        for settings in ({"output_audio": "false"}, {"output_audio": None}, {"output_audio": 0},
                         {"framing": "close-up"}, {"framing": None}, {"framing": 1}):
            with self.subTest(settings=settings), self.assertRaises(recipe.RecipeError):
                self.build(**settings)


class PinnedSourceContractTests(unittest.TestCase):
    """An optional offline source audit, additional to live /object_info CI.

    Set H3MAX_CONTRACT_SOURCES to a directory containing the exact pinned audit
    sources. This source audit is explicitly skipped when that cache is absent;
    no network downloads or model imports occur during tests.
    """
    @classmethod
    def setUpClass(cls):
        source_dir = Path(os.environ.get("H3MAX_CONTRACT_SOURCES", ROOT.parent / "audit-sources-workflows"))
        required = ("nodes.py", "nodes_minimax_h3.py", "nodes_custom_sampler.py", "nodes_audio.py",
                    "nodes_video.py", "minimaxh3.py", "motion.py", "minimax_h3_refine.py",
                    "minimax_h3_latent_upscaler_3d.py")
        missing = [name for name in required if not (source_dir / name).is_file()]
        if missing:
            raise unittest.SkipTest("Pinned source audit cache unavailable; live /object_info is checked in the image build: " + ", ".join(missing))
        for filename, expected in PINNED_SOURCE_HASHES.items():
            source = (source_dir / filename).read_text(encoding="utf-8-sig").replace("\r\n", "\n")
            actual = hashlib.sha256(source.encode()).hexdigest()
            if actual != expected:
                raise AssertionError(f"Pinned source cache drift: {filename}: {actual} != {expected}")
        cls.source_dir = source_dir
        cls.schemas = _source_schemas(source_dir)
        spec = importlib.util.spec_from_file_location("studio_schema_runtime_test", ROOT / "scripts/check_runtime.py")
        cls.runtime = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.runtime)

    def test_all_used_node_ports_match_actual_source_declarations(self):
        self.assertEqual(set(PORTS), set(self.schemas))
        for name, count in PORTS.items():
            with self.subTest(node=name):
                self.assertEqual(count, len(self.schemas[name]["output"]))

    def test_native_schemas_accept_silent_exports_and_camera_framing_directions(self):
        for engine, temporal, refine in itertools.product(("fl2va", "ref2va", "hybrid"), (False, True), (False, True)):
            assets = {} if engine == "fl2va" else {"references": ["person.png"], "audio_references": ["voice.wav"]}
            with self.subTest(engine=engine, temporal=temporal, refine=refine):
                graph = recipe.compile_request({"prompt": "A person walks.", "seed": 1,
                    "model": engine, "camera": "tracking", "framing": "wide", "output_audio": False,
                    "temporal": temporal, "refine": refine, **assets})["prompt"]
                self.runtime.validate_prompt_schema(graph, self.schemas, nodes_only=True)

    def test_actual_source_schemas_accept_all_generated_inputs_and_links(self):
        cases = []
        for engine, scene, switches in itertools.product(
                ("fl2va", "ref2va", "hybrid"), recipe.PROFILES,
                itertools.product((False, True), repeat=5)):
            motion, people, camera, refine, temporal = switches
            if scene == "weapon" and motion and (people or camera):
                continue  # Explicit incompatibility is covered by request tests.
            assets = {"first_frame": "a.png", "director": True} if engine == "fl2va" else {
                "references": [f"image{i}.png" for i in range(6)],
                "video_references": [f"video{i}.mp4" for i in range(3)],
                "audio_references": [f"audio{i}.wav" for i in range(3)],
            }
            if engine == "fl2va" and not temporal:
                assets["last_frame"] = "z.png"
            cases.append({"prompt": "Cena", "seed": 0, "model": engine, "scene": scene,
                          "motion": motion, "people_realism": people, "camera_motion": camera,
                          "refine": refine, "temporal": temporal, **assets})
        for request in cases:
            with self.subTest(engine=request["model"], scene=request["scene"],
                              refine=request["refine"], temporal=request["temporal"]):
                graph = recipe.compile_request(request)["prompt"]
                self.runtime.validate_prompt_schema(graph, self.schemas, nodes_only=True)

    def test_audit_rejects_wrong_presets_dynamic_paths_and_port_types(self):
        result = recipe.compile_request({"prompt": "Cena", "seed": 1,
                                         "references": ["p.png"], "temporal": True, "refine": True})
        mutations = [
            ("H3JerkOracle", "preset", "balanced"),
            ("H3JerkOracle", "profile_mode", "jerk"),
            ("H3V2VInit", "audio_mode", "follow original performance"),
            ("MinimaxH3LatentUpscaler3DRefineHandoff", "mode", "target_dimensions"),
            ("SaveVideo", "format.codec", "invalid"),
        ]
        for kind, field, bad_value in mutations:
            graph = copy.deepcopy(result["prompt"])
            target = next(node for node in graph.values() if node["class_type"] == kind)
            target["inputs"][field] = bad_value
            with self.subTest(kind=kind, field=field), self.assertRaises(RuntimeError):
                self.runtime.validate_prompt_schema(graph, self.schemas, nodes_only=True)
        graph = copy.deepcopy(result["prompt"])
        condition = next(node for node in graph.values() if node["class_type"] == "MiniMaxH3ReferenceToVideo")
        condition["inputs"]["ref_images.ref_image_99"] = condition["inputs"].pop("ref_images.ref_image_0")
        with self.assertRaisesRegex(RuntimeError, "unknown input"):
            self.runtime.validate_prompt_schema(graph, self.schemas, nodes_only=True)
        graph = copy.deepcopy(result["prompt"])
        smear_id = next(key for key, node in graph.items() if node["class_type"] == "H3TimeSmear")
        recover = next(node for node in graph.values() if node["class_type"] == "H3ExactRecover")
        recover["inputs"]["hold_map"] = [smear_id, 0]  # IMAGE, not the STRING map at port 1.
        with self.assertRaisesRegex(RuntimeError, "expects STRING, got IMAGE"):
            self.runtime.validate_prompt_schema(graph, self.schemas, nodes_only=True)

    def test_native_recovery_discards_a_padded_final_anchor(self):
        # Execute the actual pinned recovery method on a tiny frame/index stand-in.
        # [1,4] holds encode 2 world frames into 5 frames; the final anchor is 4.
        tree = ast.parse((self.source_dir / "motion.py").read_text(encoding="utf-8"))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "H3ExactRecover")
        method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "recover")
        scope = {"json": json, "torch": types.SimpleNamespace(tensor=lambda values: values)}
        exec(compile(ast.Module(body=[method], type_ignores=[]), "motion.py", "exec"), scope)

        class Frames:
            def __init__(self, values):
                self.values = values
                self.shape = (len(values),)

            def __getitem__(self, indices):
                return Frames([self.values[index] for index in indices])

            def cpu(self):
                return self

        recovered = scope["recover"](None, Frames(list(range(5))), json.dumps({"holds": [1, 4]}))[0]
        self.assertEqual(recovered.values, [0, 1])
        self.assertNotIn(4, recovered.values)
        with self.assertRaisesRegex(recipe.RecipeError, "imagem final"):
            recipe.compile_request({"prompt": "Cena", "last_frame": "end.png", "temporal": True})


if __name__ == "__main__":
    unittest.main()
