"""Durable Studio lifecycle against the pinned queue contract, without GPU work."""
import asyncio
import copy
import importlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import AsyncMock, Mock, patch
import uuid


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "_h3max_jobs_tests"
package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT / "custom_nodes/ComfyUI-H3MAX")]
sys.modules[PACKAGE] = package
jobs = importlib.import_module(PACKAGE + ".studio_jobs")
routes = importlib.import_module(PACKAGE + ".studio_routes")
HAS_AIOHTTP = importlib.util.find_spec("aiohttp") is not None


def identifier():
    return str(uuid.uuid4())


def record(number=None):
    return {"id": number or identifier(), "status": "queued", "created_at": "2026-09-23T12:00:00Z",
            "recipe_version": 1, "request": {"prompt": "A person walking", "seed": 17},
            "summary": {"seed": 17}, "prompt": {"1": {"class_type": "SaveVideo", "inputs": {}}},
            "outputs": []}


def item(number):
    return (0, number, {}, {}, ["1"], {})


class Queue:
    """Public contract of ComfyUI's six-item prompt queue, no worker thread."""
    def __init__(self):
        self.running = []
        self.waiting = []
        self.history = {}
        self.put = Mock(side_effect=self.waiting.append)
        self.delete_queue_item = Mock(side_effect=self.delete)
        self.interrupt_if_running = Mock(side_effect=lambda number: any(i[1] == number for i in self.running))

    def get_history(self, prompt_id=None):
        return {prompt_id: copy.deepcopy(self.history[prompt_id])} if prompt_id in self.history else {}

    def get_current_queue_volatile(self):
        return self.running[:], self.waiting[:]

    def delete(self, predicate):
        for value in self.waiting:
            if predicate(value):
                self.waiting.remove(value)
                return True
        return False


class JobStoreTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="h3-jobs-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.output = self.root / "output"
        self.output.mkdir()
        self.store = jobs.JobStore(self.root / "studio/jobs", self.output)
        self.queue = Queue()

    def test_canonical_uuid_prevents_path_access(self):
        valid = identifier()
        self.assertEqual(jobs.job_id(valid), valid)
        for value in (None, 1, "../outside", "/tmp/file", "a/../b", "C:\\outside", valid.upper(), valid.replace("-", "")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.store.read(value)
        self.assertFalse(self.store.root.exists())

    def test_recipe_and_seed_survive_restart_when_queue_is_lost(self):
        original = record()
        original["request"].update(refine=True, temporal=True, references=["person.png"],
                                   video_references=["walk.mp4"], audio_references=["voice.wav"])
        self.store.save(original)
        restarted = jobs.JobStore(self.store.root, self.output)
        loaded = restarted.refresh(restarted.read(original["id"]), Queue())
        self.assertEqual(loaded["status"], "unknown")
        self.assertEqual(loaded["request"], original["request"])
        self.assertEqual(loaded["summary"]["seed"], 17)
        self.assertEqual(loaded["prompt"], original["prompt"])
        self.assertEqual(restarted.read(original["id"]), loaded)
        self.assertEqual(list(self.store.root.glob("*.tmp")), [])

    def history_for(self, value, filenames):
        self.queue.history[value["id"]] = {"status": {"status_str": "success", "completed": True},
            "outputs": {"1": {"videos": filenames}}}

    def test_success_requires_a_nonempty_video_file_inside_output(self):
        for filename in ("missing.mp4", "empty.mp4", "actual.mp4"):
            value = record()
            if filename != "missing.mp4":
                (self.output / filename).write_bytes(b"video" if filename == "actual.mp4" else b"")
            self.store.save(value)
            self.history_for(value, [{"filename": filename, "subfolder": "", "type": "output"}])
            result = self.store.refresh(value, self.queue)
            self.assertEqual(result["status"], "success" if filename == "actual.mp4" else "error")
            self.assertEqual(bool(result["outputs"]), filename == "actual.mp4")

    def test_history_file_names_cannot_escape_output_or_return_other_file_types(self):
        (self.root / "outside.mp4").write_bytes(b"outside")
        (self.output / "valid.mp4").write_bytes(b"inside")
        variants = [{"filename": "outside.mp4", "subfolder": ".."},
                    {"filename": "../outside.mp4"}, {"filename": "C:\\outside.mp4"},
                    {"filename": "valid.mp4", "type": "input"}, {"filename": "photo.png"},
                    {"filename": "valid.mp4"}, {"filename": "valid.mp4"}]
        history = {"outputs": {"1": {"videos": variants}}}
        self.assertEqual(jobs.saved_videos(history, self.output),
                         [{"filename": "valid.mp4", "subfolder": "", "type": "output"}])

    def test_failed_or_interrupted_second_pass_preserves_base_video(self):
        (self.output / "17_base.mp4").write_bytes(b"base video")
        for event, status in (("execution_error", "error"), ("execution_interrupted", "cancelled")):
            with self.subTest(event=event):
                value = record()
                value["summary"]["outputs"] = ["base", "final"]
                self.store.save(value)
                self.queue.history[value["id"]] = {
                    "status": {"status_str": "error", "completed": False,
                               "messages": [[event, {"exception_message": "Refine failed"}]]},
                    "outputs": {"base-save": {"videos": [{"filename": "17_base.mp4", "type": "output"}]}}}
                result = self.store.refresh(value, self.queue)
                self.assertEqual(result["status"], status)
                self.assertEqual(result["outputs"], [{"filename": "17_base.mp4", "subfolder": "", "type": "output"}])
                restarted = jobs.JobStore(self.store.root, self.output)
                self.assertEqual(restarted.refresh(restarted.read(value["id"]), Queue())["outputs"], result["outputs"])

    def test_completed_history_requires_every_expected_video(self):
        for filename in ("17_base.mp4", "17_final.mp4"):
            (self.output / filename).write_bytes(b"video")
        for returned in (("17_base.mp4",), ("17_base.mp4", "17_final.mp4")):
            with self.subTest(returned=returned):
                value = record()
                value["summary"]["outputs"] = ["base", "final"]
                self.store.save(value)
                self.history_for(value, [{"filename": name, "type": "output"} for name in returned])
                result = self.store.refresh(value, self.queue)
                self.assertEqual(result["status"], "success" if len(returned) == 2 else "error")
                self.assertEqual(len(result["outputs"]), len(returned))
                if len(returned) == 1:
                    self.assertIn("1 de 2", result["error"])

    def test_pending_cancel_deletes_only_the_studio_job(self):
        value, other = record(), identifier()
        self.store.save(value)
        self.queue.waiting = [item(other), item(value["id"])]
        self.assertTrue(self.store.cancel(value["id"], self.queue)["cancelled"])
        self.assertEqual(self.queue.waiting, [item(other)])
        self.queue.interrupt_if_running.assert_not_called()
        self.assertEqual(self.store.read(value["id"])["status"], "cancelled")

    def test_running_cancel_uses_atomic_queue_method_for_exact_id(self):
        value = record()
        self.store.save(value)
        self.queue.running = [item(value["id"])]
        with patch.dict(sys.modules, {"nodes": types.SimpleNamespace(interrupt_processing=Mock(side_effect=AssertionError("global interrupt")))}):
            result = self.store.cancel(value["id"], self.queue)
        self.assertTrue(result["cancelled"])
        self.queue.interrupt_if_running.assert_called_once_with(value["id"])
        self.assertEqual(self.store.read(value["id"])["status"], "running")

    def test_unknown_and_external_jobs_never_cancel_other_queue_items(self):
        value, external = record(), identifier()
        self.store.save(value)
        self.queue.running = [item(external)]
        self.queue.waiting = [item(external)]
        self.assertFalse(self.store.cancel(value["id"], self.queue)["cancelled"])
        with self.assertRaises(KeyError):
            self.store.cancel(external, self.queue)
        self.queue.delete_queue_item.assert_not_called()
        self.queue.interrupt_if_running.assert_not_called()
        self.assertEqual(self.queue.running, [item(external)])

    def test_job_finishing_during_cancel_cannot_interrupt_its_successor(self):
        value, successor = record(), identifier()
        self.store.save(value)
        self.queue.running = [item(value["id"])]
        def finish_before_interrupt(predicate):
            self.queue.running = [item(successor)]
            return False
        self.queue.delete_queue_item.side_effect = finish_before_interrupt
        self.assertFalse(self.store.cancel(value["id"], self.queue)["cancelled"])
        self.queue.interrupt_if_running.assert_called_once_with(value["id"])
        self.assertEqual(self.queue.running, [item(successor)])

    def test_interruption_is_journaled_and_tokens_in_failure_are_redacted(self):
        value = record()
        self.store.save(value)
        self.queue.history[value["id"]] = {"status": {"status_str": "error", "messages": [
            ["execution_error", {"exception_message": "Failure hf_test_only llm_test_only"}]]}}
        with patch.dict(os.environ, {"HF_TOKEN": "hf_test_only", "H3IR_LLM_KEY": "llm_test_only"}):
            result = self.store.refresh(value, self.queue)
        text = (self.store.root / (value["id"] + ".json")).read_text(encoding="utf-8")
        self.assertEqual(result["status"], "error")
        self.assertNotIn("hf_test_only", text)
        self.assertNotIn("llm_test_only", text)
        second = record()
        self.store.save(second)
        self.queue.history[second["id"]] = {"status": {"messages": [["execution_interrupted", {}]]}}
        self.assertEqual(self.store.refresh(second, self.queue)["status"], "cancelled")

    def test_corrupt_records_do_not_break_library_listing(self):
        value = record()
        self.store.save(value)
        for body in ("{", "[]", '{"status":"queued"}'):
            (self.store.root / (identifier() + ".json")).write_text(body)
        self.assertEqual(self.store.records(), [value])


@unittest.skipUnless(HAS_AIOHTTP, "aiohttp is supplied by the ComfyUI image")
class StudioJobHTTPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from aiohttp import web
        from aiohttp.test_utils import TestClient, TestServer
        temporary = tempfile.TemporaryDirectory(prefix="h3-job-http-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.store = jobs.JobStore(self.root / "studio/jobs", self.root / "output")
        self.args = types.SimpleNamespace(cpu=False)
        self.gpu = True
        self.queue = Queue()
        self.validate = AsyncMock(return_value=(True, None, ["1"], {}))
        self.folders = types.SimpleNamespace(get_output_directory=lambda: str(self.root / "output"),
            get_input_directory=lambda: str(self.root / "input"),
            get_full_path=lambda folder, filename: "/simulated-models/" + filename)
        self.server = types.SimpleNamespace(app=web.Application(), routes=web.RouteTableDef(),
            prompt_queue=self.queue, number=7, trigger_on_prompt=lambda value: value,
            node_replace_manager=types.SimpleNamespace(apply_replacements=Mock()))
        self.environment = patch.dict(os.environ, {"H3MAX_ROOT": str(self.root),
            "HF_TOKEN": "hf_test_env_only", "H3IR_LLM_KEY": "llm_test_env_only"})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        watcher_interval = patch.object(jobs, "WATCH_INTERVAL_SECONDS", 0.01)
        watcher_interval.start()
        self.addCleanup(watcher_interval.stop)
        with patch.dict(sys.modules, {"execution": types.SimpleNamespace(validate_prompt=self.validate,
                SENSITIVE_EXTRA_DATA_KEYS=("auth_token_comfy_org", "api_key_comfy_org")),
                "folder_paths": self.folders, "torch": types.SimpleNamespace(
                    cuda=types.SimpleNamespace(is_available=lambda: self.gpu)),
                "comfy": types.ModuleType("comfy"), "comfy.cli_args": types.SimpleNamespace(args=self.args)}):
            jobs.register_job_routes(self.server)
        self.server.app.add_routes(self.server.routes)
        self.client = TestClient(TestServer(self.server.app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    async def submit(self, settings=None, **body):
        return await self.client.post("/h3max/api/jobs", json={"request": settings or {"prompt": "A person walking"}, **body})

    async def test_post_validates_then_persists_complete_recipe_before_queueing(self):
        def enqueue(value):
            self.assertEqual(self.validate.await_count, 1)
            self.assertEqual(len(value), 6)
            saved = self.store.read(value[1])
            self.assertEqual(saved["prompt"], value[2])
            self.assertEqual(saved["status"], "queued")
            self.assertEqual(saved["request"]["seed"], saved["summary"]["seed"])
            self.queue.waiting.append(value)
        self.queue.put.side_effect = enqueue
        response = await self.submit()
        self.assertEqual(response.status, 200)
        body = await response.json()
        self.assertIsInstance(body["request"]["seed"], int)
        self.assertEqual(body["request"]["model"], "fl2va")
        self.assertTrue(body["request"]["motion"])
        for field in ("director", "refine", "temporal", "camera_motion", "people_realism",
                      "references", "video_references", "audio_references", "aspect", "duration"):
            self.assertIn(field, body["request"])
        restarted = jobs.JobStore(self.store.root, self.root / "output")
        self.assertEqual(restarted.read(body["prompt_id"])["request"], body["request"])
        public = await (await self.client.get("/h3max/api/jobs/" + body["prompt_id"])).json()
        self.assertNotIn("prompt", public)
        self.assertEqual(public["request"], body["request"])
        self.assertNotIn("hf_test_env_only", json.dumps(public))
        self.assertNotIn("llm_test_env_only", json.dumps(public))

    async def test_cpu_or_unavailable_gpu_rejects_before_recipe_or_queue(self):
        for cpu, gpu in ((True, True), (False, False)):
            self.args.cpu, self.gpu = cpu, gpu
            response = await self.submit()
            self.assertEqual(response.status, 400)
            self.assertIn("GPU", (await response.json())["error"])
        self.validate.assert_not_awaited()
        self.queue.put.assert_not_called()
        self.assertFalse(self.store.root.exists())

    async def test_graph_inspection_returns_saved_graph_without_queue_or_credentials(self):
        response = await self.submit({"prompt": "A person walks", "seed": 42, "refine": True})
        number = (await response.json())["prompt_id"]
        saved = self.store.read(number)
        self.queue.put.reset_mock()
        self.validate.reset_mock()
        result = await self.client.get("/h3max/api/jobs/" + number + "/graph")
        self.assertEqual(result.status, 200)
        graph = await result.json()
        self.assertEqual(graph["prompt"], saved["prompt"])
        self.assertEqual(graph["required_models"], saved["required_models"])
        self.assertTrue(graph["required_models"])
        self.assertEqual(graph["source"], "saved_job")
        self.assertEqual(graph["job_id"], number)
        self.assertNotIn("hf_test_env_only", json.dumps(graph))
        self.queue.put.assert_not_called()
        self.validate.assert_not_awaited()
        self.assertEqual((await self.client.get("/h3max/api/jobs/" + identifier() + "/graph")).status, 404)

    async def test_invalid_recipe_and_runtime_validation_never_persist_or_queue(self):
        response = await self.submit({"prompt": "Scene", "HF_TOKEN": "never-save-this"})
        self.assertEqual(response.status, 400)
        self.validate.assert_not_awaited()
        self.validate.return_value = (False, {"message": "invalid runtime node"}, [], {"1": "bad"})
        response = await self.submit()
        self.assertEqual(response.status, 400)
        self.queue.put.assert_not_called()
        self.assertFalse(self.store.root.exists())

    async def test_disk_failure_prevents_gpu_queue_and_queue_failure_is_recorded(self):
        with patch.object(jobs.JobStore, "save", side_effect=OSError("disk full")):
            response = await self.submit()
        self.assertEqual(response.status, 500)
        self.queue.put.assert_not_called()
        self.queue.put.side_effect = RuntimeError("queue failure hf_test_env_only llm_test_env_only")
        response = await self.submit()
        self.assertEqual(response.status, 500)
        self.assertNotIn("hf_test_env_only", await response.text())
        persisted = self.store.records()
        self.assertEqual(len(persisted), 1)
        self.assertEqual(persisted[0]["status"], "error")
        self.assertNotIn("llm_test_env_only", json.dumps(persisted))

    async def test_sensitive_callback_metadata_stays_in_private_queue_slot(self):
        def hook(payload):
            payload["extra_data"]["auth_token_comfy_org"] = "comfy_test_only"
            return payload
        self.server.trigger_on_prompt = hook
        response = await self.submit(client_id="browser-session")
        self.assertEqual(response.status, 200)
        queued = self.queue.put.call_args.args[0]
        self.assertEqual(queued[5], {"auth_token_comfy_org": "comfy_test_only"})
        self.assertNotIn("auth_token_comfy_org", queued[3])
        self.assertEqual(queued[3]["client_id"], "browser-session")
        self.assertNotIn("comfy_test_only", json.dumps(self.store.records()))

    async def test_unknown_cancel_is_404_and_does_not_touch_external_queue(self):
        external = identifier()
        self.queue.running = [item(external)]
        response = await self.client.post("/h3max/api/jobs/" + external + "/cancel")
        self.assertEqual(response.status, 404)
        self.queue.delete_queue_item.assert_not_called()
        self.queue.interrupt_if_running.assert_not_called()

    async def test_chunked_oversized_request_is_rejected_before_queue(self):
        payload = json.dumps({"request": {"prompt": "A person walking"}, "padding": "x" * (129 * 1024)}).encode()
        async def chunks():
            for start in range(0, len(payload), 8192):
                yield payload[start:start + 8192]
        response = await self.client.post("/h3max/api/jobs", data=chunks(),
                                          headers={"Content-Type": "application/json"})
        self.assertEqual(response.status, 400)
        self.assertIn("longa", (await response.json())["error"])
        self.validate.assert_not_awaited()
        self.queue.put.assert_not_called()

    async def test_background_journal_preserves_completion_without_browser_polling(self):
        response = await self.submit({"prompt": "A person walking", "seed": 9321})
        number = (await response.json())["prompt_id"]
        output = self.root / "output" / "saved.mp4"
        output.parent.mkdir()
        output.write_bytes(b"simulated video artifact")
        self.queue.waiting.clear()
        self.queue.history[number] = {"status": {"status_str": "success", "completed": True},
            "outputs": {"1": {"videos": [{"filename": "saved.mp4", "type": "output"}]}}}
        # No GET request refreshes this record; the server lifecycle owns it.
        for _ in range(50):
            if self.store.read(number)["status"] == "success":
                break
            await asyncio.sleep(0.01)
        self.assertEqual(self.store.read(number)["status"], "success")
        self.queue.history.clear()
        restarted = jobs.JobStore(self.store.root, output.parent)
        persisted = restarted.refresh(restarted.read(number), Queue())
        self.assertEqual(persisted["status"], "success")
        self.assertEqual(persisted["request"]["seed"], 9321)
        self.assertEqual(persisted["outputs"][0]["filename"], "saved.mp4")

    async def test_probed_audio_metadata_is_ordered_and_persists_across_restart(self):
        input_root = self.root / "input"
        input_root.mkdir()
        names = ["silent.mp4", "speaking.mp4", "ambient.mp4", "voice.wav"]
        for name in names:
            (input_root / name).write_bytes(b"reference fixture")
        settings = {"prompt": "Use <Video 2> with <Audio 3>.", "seed": 132,
                    "video_references": names[:3], "audio_references": names[3:]}
        metadata = {
            "silent.mp4": {"has_video": True, "has_audio": False, "duration": 3},
            "speaking.mp4": {"has_video": True, "has_audio": True, "duration": 3},
            "ambient.mp4": {"has_video": True, "has_audio": True, "duration": 3},
            "voice.wav": {"has_video": False, "has_audio": True, "duration": 3},
        }
        expected = {"video_references": [{"filename": name, "has_audio": metadata[name]["has_audio"]}
                                          for name in names[:3]]}
        with patch.object(routes, "probe_media", new=AsyncMock(
                side_effect=lambda path: copy.deepcopy(metadata[path.name]))) as probe:
            response = await self.submit(settings)
        self.assertEqual(response.status, 200)
        body = await response.json()
        self.assertEqual([call.args[0].name for call in probe.await_args_list], names)
        self.assertEqual(body["summary"]["reference_media"], expected)
        self.assertNotIn("reference_media", body["request"])
        self.assertEqual(body["request"]["video_references"], names[:3])
        restarted = jobs.JobStore(self.store.root, self.root / "output")
        saved = restarted.read(body["prompt_id"])
        self.assertEqual(saved["summary"]["reference_media"], expected)
        public = await (await self.client.get("/h3max/api/jobs/" + body["prompt_id"])).json()
        self.assertEqual(public["summary"]["reference_media"], expected)
        self.assertNotIn("reference_media", public["request"])


if __name__ == "__main__":
    unittest.main()
