"""Real aiohttp HTTP integration with simulated ComfyUI/GPU dependencies."""
import importlib
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "_h3max_studio_http"
package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT / "custom_nodes" / "ComfyUI-H3MAX")]
sys.modules[PACKAGE] = package
routes = importlib.import_module(PACKAGE + ".studio_routes")
HAS_AIOHTTP = importlib.util.find_spec("aiohttp") is not None


@unittest.skipUnless(HAS_AIOHTTP, "aiohttp is supplied by the ComfyUI image")
class StudioHTTPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from aiohttp import web
        from aiohttp.test_utils import TestClient, TestServer

        self.temporary = tempfile.TemporaryDirectory(prefix="h3-studio-http-")
        self.addCleanup(self.temporary.cleanup)
        self.models_present = False
        self.absent_models = set()
        folder_paths = types.SimpleNamespace(
            get_input_directory=lambda: self.temporary.name,
            get_full_path=lambda folder, filename: "/simulated-models/" + filename
            if self.models_present and filename not in self.absent_models else None)
        self.gpu_present = False
        torch = types.SimpleNamespace(cuda=types.SimpleNamespace(is_available=lambda: self.gpu_present))
        self.args = types.SimpleNamespace(cpu=False)
        self.node_classes = {}
        for body in ({"refine": True, "temporal": True, "director": True},
                     {"model": "hybrid", "references": ["ref.png"],
                      "video_references": ["ref.mp4"], "audio_references": ["ref.wav"]},
                     {"references": ["ref.png"]}):
            compiled = routes.compile_request({"prompt": "fixture", **body})
            self.node_classes.update({node["class_type"]: object for node in compiled["prompt"].values()})
        app = web.Application()
        server = types.SimpleNamespace(app=app, routes=web.RouteTableDef())
        # register_routes captures these imports. No real Torch or ComfyUI is
        # imported, while HTTP parsing, middleware and FileResponse are real.
        with patch.dict(sys.modules, {"folder_paths": folder_paths, "torch": torch,
                "nodes": types.SimpleNamespace(NODE_CLASS_MAPPINGS=self.node_classes),
                "comfy": types.ModuleType("comfy"),
                "comfy.cli_args": types.SimpleNamespace(args=self.args)}):
            routes.register_routes(server)

        async def native_root(request):
            return web.Response(text="simulated native ComfyUI route")

        app.router.add_get("/", native_root)
        app.add_routes(server.routes)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()
        self.environment = patch.dict(os.environ, {"H3IR_LLM_URL": "", "H3IR_LLM_MODEL": ""})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    async def asyncTearDown(self):
        await self.client.close()

    async def test_default_root_redirects_and_native_entry_remains_accessible(self):
        response = await self.client.get("/", allow_redirects=False)
        self.assertEqual(response.status, 302)
        self.assertEqual(response.headers["Location"], "/h3max")
        native = await self.client.get("/?comfy=1")
        self.assertEqual(native.status, 200)
        self.assertIn("native ComfyUI", await native.text())

    async def test_studio_and_assets_are_served_by_real_http(self):
        for path, content_type in (("/h3max", "text/html"), ("/h3max/", "text/html"),
                                   ("/h3max/studio.css", "text/css"),
                                   ("/h3max/studio.js", "javascript")):
            with self.subTest(path=path):
                response = await self.client.get(path)
                self.assertEqual(response.status, 200)
                self.assertIn(content_type, response.headers["Content-Type"])
                self.assertGreater(len(await response.read()), 100)
        missing = await self.client.get("/h3max/not-a-served-file")
        self.assertEqual(missing.status, 404)

    async def test_capabilities_do_not_claim_ready_or_validated_without_gpu(self):
        response = await self.client.get("/h3max/api/capabilities")
        self.assertEqual(response.status, 200)
        body = await response.json()
        self.assertFalse(body["runtime_ready"])
        self.assertFalse(body["quality_validated"])
        self.assertFalse(body["director_available"])
        self.assertGreater(len(body["missing_models"]), 0)
        self.models_present = True
        present = await (await self.client.get("/h3max/api/capabilities")).json()
        self.assertFalse(present["runtime_ready"])
        self.assertEqual(present["missing_models"], [])

    async def test_ref2va_remains_ready_without_fl2va_and_controls_match_installed_files(self):
        self.models_present = self.gpu_present = True
        self.absent_models.update({"minimax_h3_fl2va_pruned_int8_convrot.safetensors",
                                   "Motion_Repair.safetensors"})
        body = await (await self.client.get("/h3max/api/capabilities")).json()
        self.assertTrue(body["runtime_ready"])
        self.assertTrue(body["models"]["ref2va"]["available"])
        self.assertTrue(body["models"]["auto"]["available"])
        self.assertFalse(body["models"]["fl2va"]["available"])
        self.assertFalse(body["models"]["hybrid"]["available"])
        self.assertFalse(body["features"]["first_frame"]["available"])
        self.assertTrue(body["features"]["references"]["available"])
        self.assertFalse(body["scenes"]["natural"]["available"])
        self.assertTrue(body["scenes"]["action"]["available"])
        self.assertTrue(body["features"]["motion"]["available"])
        self.assertFalse(body["quality_validated"])
        self.assertFalse(body["gpu_inference_validated"])

    async def test_optional_missing_nodes_only_disable_their_features(self):
        self.models_present = self.gpu_present = True
        del self.node_classes["H3MAXReferenceVideo"]
        del self.node_classes["H3JerkOracle"]
        self.absent_models.add("minimax_h3_latent_upscaler_3d_conv_v1_fp16.safetensors")
        body = await (await self.client.get("/h3max/api/capabilities")).json()
        self.assertTrue(body["runtime_ready"])
        self.assertFalse(body["features"]["video_references"]["available"])
        self.assertTrue(body["features"]["audio_references"]["available"])
        self.assertFalse(body["features"]["temporal"]["available"])
        self.assertFalse(body["features"]["refine"]["available"])
        self.assertIn("H3JerkOracle", body["features"]["temporal"]["missing_nodes"])
        self.assertTrue(body["features"]["temporal"]["reason"])
        self.assertTrue(body["features"]["refine"]["reason"])
        self.assertEqual(body["missing_models"], [])

    async def test_missing_common_node_or_encoder_prevents_all_engines(self):
        self.models_present = self.gpu_present = True
        removed = self.node_classes.pop("SaveVideo")
        body = await (await self.client.get("/h3max/api/capabilities")).json()
        self.assertFalse(body["runtime_ready"])
        self.assertIn("SaveVideo", body["missing_nodes"])
        self.assertTrue(all(not state["available"] for state in body["models"].values()))
        self.node_classes["SaveVideo"] = removed
        self.absent_models.add("qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors")
        body = await (await self.client.get("/h3max/api/capabilities")).json()
        self.assertFalse(body["runtime_ready"])
        self.assertTrue(all(not state["available"] for state in body["models"].values()))

    async def test_cpu_flag_overrides_cuda_and_director_needs_both_configuration_and_node(self):
        self.models_present = self.gpu_present = True
        self.args.cpu = True
        with patch.dict(os.environ, {"H3IR_LLM_URL": "http://configured.invalid", "H3IR_LLM_MODEL": "fixture"}):
            body = await (await self.client.get("/h3max/api/capabilities")).json()
            self.assertFalse(body["runtime_ready"])
            self.assertTrue(body["director_available"])
            del self.node_classes["H3MAXDirectorText"]
            body = await (await self.client.get("/h3max/api/capabilities")).json()
            self.assertFalse(body["director_available"])
            self.assertIn("H3MAXDirectorText", body["features"]["director"]["missing_nodes"])

    async def test_prepare_invalid_request_returns_actionable_400(self):
        for value in ({}, {"prompt": "scene", "duration": 7}, [], None):
            with self.subTest(value=value):
                response = await self.client.post("/h3max/api/prepare", json=value)
                self.assertEqual(response.status, 400)
                body = await response.json()
                self.assertTrue(body["error"])
                self.assertEqual(body["message"], body["error"])
        malformed = await self.client.post("/h3max/api/prepare", data="{", headers={"Content-Type": "application/json"})
        self.assertEqual(malformed.status, 400)

    async def test_prepare_missing_models_returns_400_before_generation(self):
        response = await self.client.post("/h3max/api/prepare", json={"prompt": "A person walking", "motion": False})
        self.assertEqual(response.status, 400)
        self.assertIn("modelos", (await response.json())["error"])

    async def test_prepare_can_compile_without_a_gpu_but_never_queues(self):
        self.models_present = True
        response = await self.client.post("/h3max/api/prepare", json={"prompt": "A person walking", "motion": False, "seed": 7})
        self.assertEqual(response.status, 200)
        body = await response.json()
        self.assertEqual(body["summary"]["seed"], 7)
        self.assertIsInstance(body["prompt"], dict)
        self.assertTrue(any(node["class_type"] == "SaveVideo" for node in body["prompt"].values()))
        self.assertNotIn("prompt_id", body)


if __name__ == "__main__":
    unittest.main()
