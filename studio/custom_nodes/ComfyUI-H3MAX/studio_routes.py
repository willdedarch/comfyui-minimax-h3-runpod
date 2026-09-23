"""Same-origin Studio routes. Preparing a recipe never queues a GPU job."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import uuid

from .studio_recipe import compile_request

WEB = Path(__file__).parent / "studio_web"
MEDIA_EXTENSIONS = {".mp4", ".webm", ".mov", ".mkv", ".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac", ".opus"}
MAX_UPLOAD = 256 * 1024 * 1024


def director_available():
    return bool(os.environ.get("H3IR_LLM_URL", "").strip() and os.environ.get("H3IR_LLM_MODEL", "").strip())


def runtime_capabilities(folder_paths, node_classes, *, gpu, director=False):
    """Check files and node registration, never claim inference or visual quality."""
    def check(body):
        result = compile_request({"prompt": "Verificação de disponibilidade", "seed": 0,
                                  "motion": False, **body})
        missing_models = sorted({m["filename"] for m in result["required_models"]
                                 if not folder_paths.get_full_path(m["folder"], m["filename"])})
        missing_nodes = sorted({n["class_type"] for n in result["prompt"].values()
                                if n["class_type"] not in node_classes})
        reason = ("Os modelos necessários ainda não foram baixados." if missing_models else
                  "Um componente necessário ainda não carregou no servidor." if missing_nodes else "")
        return {"available": not (missing_models or missing_nodes), "reason": reason,
                "missing_models": missing_models, "missing_nodes": missing_nodes}

    requests = {"fl2va": {"model": "fl2va"},
                "ref2va": {"model": "ref2va", "references": ["reference.png"]},
                "hybrid": {"model": "hybrid", "references": ["reference.png"]}}
    models = {name: check(body) for name, body in requests.items()}

    def combine(options):
        # Missing optional alternatives do not disable a working engine.
        for option in options:
            if option["available"]:
                return {"available": True, "reason": "", "missing_models": [], "missing_nodes": []}
        return {"available": False, "reason": options[0]["reason"],
                "missing_models": sorted({name for item in options for name in item["missing_models"]}),
                "missing_nodes": sorted({name for item in options for name in item["missing_nodes"]})}

    # Auto selects native FL2VA or REF2VA; Hybrid is an explicit choice.
    models["auto"] = combine([models["fl2va"], models["ref2va"]])
    scenes = {scene: combine([check({**body, "motion": True, "scene": scene})
                             for body in requests.values()])
              for scene in ("natural", "action", "objects", "weapon")}
    features = {key: check({"model": "fl2va", key: "frame.png"})
                for key in ("first_frame", "last_frame")}
    features["references"] = check(requests["ref2va"])
    features["video_references"] = check({"model": "ref2va", "video_references": ["reference.mp4"]})
    features["audio_references"] = check({**requests["ref2va"], "audio_references": ["reference.wav"]})
    for key in ("people_realism", "camera_motion", "refine", "temporal"):
        features[key] = combine([check({**body, key: True}) for body in requests.values()])
    features["motion"] = combine(list(scenes.values()))
    features["director"] = check({"model": "fl2va", "director": True})
    if not director:
        features["director"].update(available=False,
            reason="O serviço de direção de texto ainda não foi configurado no servidor.")
    usable = combine([models[name] for name in requests])
    ready = bool(gpu and usable["available"])
    return {"preview": False, "runtime_ready": ready, "gpu_available": bool(gpu),
            "director_available": features["director"]["available"],
            "models": models, "scenes": scenes, "features": features,
            "missing_models": usable["missing_models"], "missing_nodes": usable["missing_nodes"],
            "quality_validated": False, "gpu_inference_validated": False,
            "message": "Servidor disponível para gerar. Qualidade visual deste pacote ainda em validação." if ready
                       else "A geração aguarda GPU, modelos e componentes disponíveis no servidor."}


def input_path(root, name):
    """Do not allow model annotations, URLs, symlink escapes or absolute paths."""
    if not isinstance(name, str) or not name or any(c in name for c in ("\\", ":", "\x00", "[", "]")):
        raise ValueError("Nome de mídia inválido. Envie o arquivo pelo painel.")
    relative = Path(name)
    root = Path(root).resolve()
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("A mídia precisa estar na pasta de entradas do Studio.")
    result = (root / relative).resolve()
    if not result.is_relative_to(root):
        raise ValueError("A mídia está fora da pasta de entradas do Studio.")
    if not result.is_file():
        raise ValueError("Arquivo não encontrado. Envie novamente a mídia: " + name)
    return result


def preflight(result, request, folder_paths):
    missing = [m["filename"] for m in result["required_models"]
               if not folder_paths.get_full_path(m["folder"], m["filename"])]
    if missing:
        raise ValueError("O servidor ainda não tem todos os modelos desta configuração: " + ", ".join(missing))
    for field in ("first_frame", "last_frame"):
        if request.get(field):
            input_path(folder_paths.get_input_directory(), request[field])
    for field in ("references", "video_references", "audio_references"):
        for name in request.get(field, []):
            input_path(folder_paths.get_input_directory(), name)
    if request.get("director") and not director_available():
        raise ValueError("A direção de texto ainda não foi configurada neste servidor.")


async def probe_media(path):
    process = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe", "-show_entries", "format=duration:stream=codec_type,width,height",
        "-of", "json", str(path), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=25)
    except asyncio.TimeoutError:
        process.kill()
        await process.communicate()
        raise ValueError("Não foi possível ler essa mídia dentro do tempo limite.")
    if process.returncode:
        raise ValueError("O arquivo não contém vídeo ou áudio válido.")
    info = json.loads(stdout)
    duration = float(info.get("format", {}).get("duration", 0))
    if not 2 <= duration <= 15.05:
        raise ValueError("Use referências de vídeo e áudio entre 2 e 15 segundos. O Studio não corta seu arquivo silenciosamente.")
    streams = info.get("streams", [])
    if not any(s.get("codec_type") in ("video", "audio") for s in streams):
        raise ValueError("Nenhuma faixa de vídeo ou áudio foi encontrada.")
    for stream in streams:
        if stream.get("codec_type") == "video" and stream.get("width", 0) * stream.get("height", 0) > 3840 * 2160:
            raise ValueError("Use uma referência de até 4K para limitar o consumo de memória.")
    return {"duration": duration, "has_video": any(s.get("codec_type") == "video" for s in streams),
            "has_audio": any(s.get("codec_type") == "audio" for s in streams)}


async def prepare_recipe(body, folder_paths):
    """Compile and check files/media; never queue or spend GPU time."""
    result = compile_request(body)
    preflight(result, body, folder_paths)
    # Core Ref2VA otherwise trims long references to the output length.
    # Reject it before queueing so the selected material is not silently changed.
    total_video = 0.0
    video_metadata = []
    for filename in body.get("video_references", []):
        media = await probe_media(input_path(folder_paths.get_input_directory(), filename))
        if not media["has_video"]:
            raise ValueError("A referência de vídeo não contém uma faixa de vídeo.")
        if media["duration"] > result["summary"]["seconds"] + 1 / 24:
            raise ValueError("A referência de vídeo é mais longa que a cena. Escolha uma duração maior para preservar a referência inteira.")
        total_video += media["duration"]
        video_metadata.append({"filename": filename, "has_audio": media["has_audio"]})
    if total_video > 15.05:
        raise ValueError("A soma dos vídeos de referência precisa ter até 15 segundos.")
    total_audio = 0.0
    for filename in body.get("audio_references", []):
        media = await probe_media(input_path(folder_paths.get_input_directory(), filename))
        if not media["has_audio"]:
            raise ValueError("A referência de áudio não contém uma faixa de áudio.")
        total_audio += media["duration"]
    if total_audio > 15.05:
        raise ValueError("A soma dos áudios de referência precisa ter até 15 segundos.")
    result["summary"]["reference_media"] = {"video_references": video_metadata}
    return result


def register_routes(server):
    import folder_paths
    import nodes
    import torch
    from aiohttp import web
    from comfy.cli_args import args

    routes = server.routes

    @web.middleware
    async def studio_home(request, handler):
        if request.method == "GET" and request.path == "/" and request.query.get("comfy") != "1":
            raise web.HTTPFound("/h3max")
        return await handler(request)

    server.app.middlewares.append(studio_home)

    @routes.get("/h3max")
    @routes.get("/h3max/")
    async def studio_index(request):
        return web.FileResponse(WEB / "index.html", headers={"Cache-Control": "no-store"})

    @routes.get("/h3max/studio.css")
    async def studio_css(request):
        return web.FileResponse(WEB / "studio.css", headers={"Cache-Control": "no-cache"})

    @routes.get("/h3max/studio.js")
    async def studio_js(request):
        return web.FileResponse(WEB / "studio.js", headers={"Cache-Control": "no-cache"})

    @routes.get("/h3max/api/capabilities")
    async def capabilities(request):
        return web.json_response(runtime_capabilities(folder_paths, nodes.NODE_CLASS_MAPPINGS,
            gpu=torch.cuda.is_available() and not args.cpu, director=director_available()))

    @routes.post("/h3max/api/prepare")
    async def prepare(request):
        try:
            if request.content_length and request.content_length > 128 * 1024:
                raise ValueError("A descrição enviada excede o limite permitido.")
            body = await request.json()
            return web.json_response(await prepare_recipe(body, folder_paths))
        except (ValueError, TypeError, KeyError) as exc:
            return web.json_response({"error": str(exc), "message": str(exc)}, status=400)

    @routes.post("/h3max/api/upload")
    async def upload(request):
        destination = None
        temporary = None
        try:
            reader = await request.multipart()
            part = await reader.next()
            if part is None or part.name != "file" or not part.filename:
                raise ValueError("Selecione um arquivo de vídeo ou áudio.")
            extension = Path(part.filename).suffix.lower()
            if extension not in MEDIA_EXTENSIONS:
                raise ValueError("Formato não suportado. Use MP4, WebM, MOV, MKV, MP3, WAV, FLAC, M4A ou OGG.")
            root = Path(folder_paths.get_input_directory()).resolve()
            root.mkdir(parents=True, exist_ok=True)
            destination = root / ("h3studio_" + uuid.uuid4().hex + extension)
            temporary = destination.with_suffix(extension + ".upload")
            size = 0
            with temporary.open("xb") as handle:
                while chunk := await part.read_chunk(256 * 1024):
                    size += len(chunk)
                    if size > MAX_UPLOAD:
                        raise ValueError("Cada referência pode ter até 256 MB.")
                    handle.write(chunk)
            if not size:
                raise ValueError("O arquivo está vazio.")
            media = await probe_media(temporary)
            temporary.replace(destination)
            return web.json_response({"name": destination.name, "subfolder": "", "type": "input", **media})
        except (ValueError, TypeError, OSError) as exc:
            return web.json_response({"error": str(exc), "message": str(exc)}, status=400)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()
