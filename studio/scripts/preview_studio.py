#!/usr/bin/env python3
"""Local, read-only interface preview. Never uploads media or queues generation."""
from __future__ import annotations

import argparse
import importlib.util
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "custom_nodes/ComfyUI-H3MAX"
spec = importlib.util.spec_from_file_location("studio_recipe_preview", PACK / "studio_recipe.py")
recipe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recipe)


class PreviewHandler(BaseHTTPRequestHandler):
    def reply(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/h3max/api/jobs":
            self.reply({"jobs": [], "preview": True})
            return
        if path == "/h3max/api/capabilities":
            feature = {k: {"available": True} for k in ("motion", "people_realism", "camera_motion", "refine", "temporal", "first_frame", "last_frame", "references", "video_references", "audio_references")}
            feature["director"] = {"available": False, "reason": "O serviço de direção será configurado no servidor."}
            self.reply({"preview": True, "runtime_ready": False, "director_available": False,
                        "features": feature, "missing_models": [], "quality_validated": False,
                        "models": {k: {"available": True} for k in ("auto", "fl2va", "ref2va", "hybrid")},
                        "scenes": {k: {"available": True} for k in ("natural", "action", "objects", "weapon")},
                        "message": "Prévia da interface. Este computador não está conectado à geração."})
            return
        files = {"/": ("index.html", "text/html"), "/h3max": ("index.html", "text/html"),
                 "/h3max/": ("index.html", "text/html"), "/h3max/studio.css": ("studio.css", "text/css"),
                 "/h3max/studio.js": ("studio.js", "text/javascript")}
        if path not in files:
            self.reply({"error": "Página não encontrada."}, 404)
            return
        name, content_type = files[path]
        data = (PACK / "studio_web" / name).read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        origin = self.headers.get("Origin")
        if origin and urlsplit(origin).netloc != self.headers.get("Host"):
            self.reply({"error": "Origem não permitida."}, 403)
            return
        if urlsplit(self.path).path != "/h3max/api/prepare":
            self.reply({"error": "A prévia não envia arquivos nem gera vídeos."}, 409)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > 128 * 1024:
                raise ValueError("Descrição inválida ou muito longa.")
            request = json.loads(self.rfile.read(length))
            result = recipe.compile_request(request)
            result["preview"] = True
            result["summary"].setdefault("notes", []).append("Configuração verificada localmente; nenhum vídeo foi gerado.")
            self.reply(result)
        except (ValueError, TypeError, KeyError) as exc:
            self.reply({"error": str(exc), "message": str(exc)}, 400)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    print(f"Interface preview: http://127.0.0.1:{args.port}/h3max?preview=1", flush=True)
    ThreadingHTTPServer(("127.0.0.1", args.port), PreviewHandler).serve_forever()
