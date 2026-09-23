"""Studio boundary regressions; no ComfyUI, Torch, model weights or GPU."""
import copy
import importlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import AsyncMock, patch


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "_h3max_studio_integration"
package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT / "custom_nodes" / "ComfyUI-H3MAX")]
sys.modules[PACKAGE] = package
routes = importlib.import_module(PACKAGE + ".studio_routes")
media = importlib.import_module(PACKAGE + ".studio_media")


class InputBoundaryTests(unittest.TestCase):
    def test_input_resolution_accepts_nested_file_and_refuses_other_locations(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "input"
            root.mkdir()
            (root / "clips").mkdir()
            good = root / "clips" / "take.mp4"
            good.write_bytes(b"reference")
            (root.parent / "outside.mp4").write_bytes(b"outside")
            self.assertEqual(routes.input_path(root, "clips/take.mp4"), good.resolve())
            for name in ("../outside.mp4", str(root.parent / "outside.mp4"),
                         "clips/../../outside.mp4", "C:/outside.mp4",
                         "https://example.org/ref.mp4", "take.mp4 [output]",
                         "clips\\take.mp4", "clips/absent.mp4", "clips", None):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    routes.input_path(root, name)

    def test_preflight_refuses_missing_selected_model_before_generation(self):
        folders = types.SimpleNamespace(get_full_path=lambda folder, name: None)
        recipe = {"required_models": [{"folder": "loras", "filename": "missing.safetensors"}]}
        with self.assertRaisesRegex(ValueError, "missing.safetensors"):
            routes.preflight(recipe, {"prompt": "test"}, folders)

    def test_preflight_checks_each_reference_path_even_when_weights_exist(self):
        with tempfile.TemporaryDirectory() as temporary:
            folders = types.SimpleNamespace(
                get_full_path=lambda folder, name: "/installed/" + name,
                get_input_directory=lambda: temporary)
            for field in ("first_frame", "last_frame", "references", "video_references", "audio_references"):
                value = "../outside.mp4" if field in ("first_frame", "last_frame") else ["../outside.mp4"]
                with self.subTest(field=field), self.assertRaises(ValueError):
                    routes.preflight({"required_models": []}, {field: value}, folders)


class ReferenceTimingTests(unittest.TestCase):
    def test_cfr_resampling_preserves_elapsed_time_and_valid_indices(self):
        for frames, fps in ((60, 30), (120, 60), (48, 24), (75, 25), (90, 30000 / 1001)):
            with self.subTest(frames=frames, fps=fps):
                indices = media.frame_indices(frames, fps)
                self.assertLessEqual(abs(len(indices) / 24 - frames / fps), 1 / 24)
                self.assertEqual(indices[0], 0)
                self.assertTrue(all(0 <= i < frames for i in indices))
                self.assertEqual(indices, sorted(indices))

    def test_invalid_duration_and_fps_are_refused(self):
        for count, fps in ((0, 24), (-1, 24), (24, 24), (384, 24),
                           (120, 0), (120, float("nan")), (120, float("inf"))):
            with self.subTest(count=count, fps=fps), self.assertRaises(ValueError):
                media.frame_indices(count, fps)

    def test_grid_alignment_never_extends_or_moves_original_frames(self):
        for count in (48, 107, 120, 124, 243, 360):
            retained = media.legal_frame_count(count)
            self.assertEqual(retained % 17, 5)
            self.assertLessEqual(retained, count)
            self.assertLess(count - retained, 17)

    def test_ffmpeg_normalizes_timestamps_and_resolution_before_tensor_decode(self):
        probe = {"format": {"duration": "5"}, "streams": [
            {"width": 3840, "height": 2160, "duration": "5"}]}
        completed = subprocess.CompletedProcess([], 0, json.dumps(probe).encode(), b"")
        with patch.object(media.subprocess, "run", return_value=completed) as run:
            media.normalize_reference(Path("source.mp4"), Path("bounded.mkv"))
        command = run.call_args_list[1].args[0]
        video_filter = command[command.index("-vf") + 1]
        self.assertIn("fps=fps=24:start_time=0", video_filter)
        self.assertIn("scale=", video_filter)
        self.assertIn(str(media.MAX_PIXELS), video_filter)
        self.assertIn("0:a:0?", command)
        self.assertIn("ffv1", command)
        self.assertIn("pcm_s16le", command)
        self.assertFalse(run.call_args.kwargs.get("shell", False))

    def test_bad_metadata_and_timeout_fail_before_video_allocation(self):
        for probe in ({"streams": []}, {"streams": [{"width": 640, "height": 360}],
                                         "format": {"duration": "30"}}):
            completed = subprocess.CompletedProcess([], 0, json.dumps(probe).encode(), b"")
            with self.subTest(probe=probe), patch.object(media.subprocess, "run", return_value=completed) as run:
                with self.assertRaises(ValueError):
                    media.normalize_reference("source.mp4", "bounded.mkv")
                self.assertEqual(run.call_count, 1)
        with patch.object(media.subprocess, "run", side_effect=subprocess.TimeoutExpired("ffmpeg", 180)):
            with self.assertRaisesRegex(ValueError, "tempo limite"):
                media._run_media(["ffmpeg"])


class ReferenceMetadataTests(unittest.IsolatedAsyncioTestCase):
    async def test_probe_metadata_keeps_video_order_and_does_not_mutate_request(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            names = ["silent.mp4", "speaking.mp4", "ambient.mp4", "voice.wav"]
            for name in names:
                (root / name).write_bytes(b"media fixture")
            folders = types.SimpleNamespace(get_input_directory=lambda: temporary,
                get_full_path=lambda folder, name: "/installed/" + name)
            request = {"prompt": "Use <Video 2> with <Audio 3>.", "seed": 812,
                       "video_references": names[:3], "audio_references": names[3:]}
            original = copy.deepcopy(request)
            metadata = {
                "silent.mp4": {"has_video": True, "has_audio": False, "duration": 3},
                "speaking.mp4": {"has_video": True, "has_audio": True, "duration": 3},
                "ambient.mp4": {"has_video": True, "has_audio": True, "duration": 3},
                "voice.wav": {"has_video": False, "has_audio": True, "duration": 3},
            }
            with patch.object(routes, "probe_media", new=AsyncMock(
                    side_effect=lambda path: copy.deepcopy(metadata[path.name]))) as probe:
                result = await routes.prepare_recipe(request, folders)
            self.assertEqual([call.args[0].name for call in probe.await_args_list], names)
            self.assertEqual(result["summary"]["reference_media"], {"video_references": [
                {"filename": "silent.mp4", "has_audio": False},
                {"filename": "speaking.mp4", "has_audio": True},
                {"filename": "ambient.mp4", "has_audio": True}]})
            self.assertEqual(request, original)
            self.assertNotIn("reference_media", request)

    async def test_silent_videos_do_not_invent_soundtrack_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "silent.mp4").write_bytes(b"media fixture")
            folders = types.SimpleNamespace(get_input_directory=lambda: temporary,
                get_full_path=lambda folder, name: "/installed/" + name)
            with patch.object(routes, "probe_media", new=AsyncMock(return_value={
                    "has_video": True, "has_audio": False, "duration": 3})):
                result = await routes.prepare_recipe({"prompt": "Use <Video 1>.",
                    "video_references": ["silent.mp4"]}, folders)
            self.assertEqual(result["summary"]["reference_media"]["video_references"],
                             [{"filename": "silent.mp4", "has_audio": False}])


class FakeFrames:
    def __init__(self, count):
        self.shape = (count, 736, 1280, 3)

    def __getitem__(self, selection):
        return FakeFrames(len(range(self.shape[0])[selection]))


class FakeWaveform:
    def __init__(self, samples):
        self.shape = (1, 2, samples)

    def __getitem__(self, selection):
        return FakeWaveform(len(range(self.shape[-1])[selection[-1]]))


class VideoAdapterTests(unittest.TestCase):
    def exercise_load(self, audio, decoded_count=107):
        constructor_calls = []
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source.mp4"
            source.write_bytes(b"fixture")

            class FakeVideo:
                def __init__(self, path, **kwargs):
                    constructor_calls.append((path, kwargs))
                    # Any full-resolution decode would be a regression.
                    if Path(path) == source:
                        raise AssertionError("Unbounded original passed to tensor decoder")
                    if not Path(path).is_file():
                        raise AssertionError("Normalization must finish before decoding")

                def get_frame_count(self):
                    return 120

                def get_frame_rate(self):
                    return 24

                def get_components(self):
                    return types.SimpleNamespace(images=FakeFrames(decoded_count), audio=audio, frame_rate=24)

            modules = {
                "folder_paths": types.SimpleNamespace(get_input_directory=lambda: temporary),
                "comfy_api": types.ModuleType("comfy_api"),
                "comfy_api.latest": types.SimpleNamespace(InputImpl=types.SimpleNamespace(VideoFromFile=FakeVideo)),
            }
            with patch.dict(sys.modules, modules), patch.object(media, "normalize_reference",
                    side_effect=lambda original, output: Path(output).write_bytes(b"normalized")):
                result = media.H3MAXReferenceVideo().load("source.mp4")
            self.assertEqual(constructor_calls[1][1], {"duration": 107 / 24})
            self.assertFalse(Path(constructor_calls[0][0]).exists(), "Temporary media must be cleaned up")
            return result

    def test_silent_reference_keeps_none_audio(self):
        images, audio = self.exercise_load(None)
        self.assertEqual(images.shape[0], 107)
        self.assertIsNone(audio)

    def test_soundtrack_is_trimmed_to_actual_decoded_video_grid(self):
        original = {"sample_rate": 32000, "waveform": FakeWaveform(160000)}
        images, audio = self.exercise_load(original, decoded_count=106)
        self.assertEqual(images.shape[0], 90)
        self.assertEqual(audio["waveform"].shape[-1], 120000)
        self.assertEqual(original["waveform"].shape[-1], 160000)


if __name__ == "__main__":
    unittest.main()
