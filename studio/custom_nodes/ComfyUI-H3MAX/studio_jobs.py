"""Durable Studio recipes and targeted queue operations on the pinned ComfyUI."""
from __future__ import annotations

import asyncio
from contextlib import suppress
import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
import uuid

TERMINAL = {"success", "error", "cancelled"}
WATCH_INTERVAL_SECONDS = 5
SECRET_KEYS = {"hf_token", "h3ir_llm_key", "hugging_face_hub_token",
               "auth_token_comfy_org", "api_key_comfy_org", "authorization", "api_key"}


def redact(value):
    """Keep runtime credentials out of the journal and API error messages."""
    if isinstance(value, dict):
        return {key: "[redacted]" if str(key).lower() in SECRET_KEYS else redact(item)
                for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if isinstance(value, str):
        for key in ("HF_TOKEN", "H3IR_LLM_KEY", "HUGGING_FACE_HUB_TOKEN"):
            secret = os.environ.get(key)
            if secret:
                value = value.replace(secret, "[redacted]")
    return value


def job_id(value):
    if not isinstance(value, str) or str(uuid.UUID(value)) != value:
        raise ValueError("Identificador de geração inválido.")
    return value


def saved_videos(history, output_root):
    output_root = Path(output_root).resolve()
    result = []
    for output in history.get("outputs", {}).values():
        for key in ("videos", "gifs", "images"):
            for item in output.get(key, []):
                if not isinstance(item, dict):
                    continue
                filename = item.get("filename", "")
                subfolder = item.get("subfolder", "")
                if (not isinstance(filename, str) or not isinstance(subfolder, str)
                        or any(c in filename + subfolder for c in ("\\", ":", "\x00"))
                        or Path(filename).name != filename or Path(subfolder).is_absolute()
                        or ".." in Path(subfolder).parts
                        or Path(filename).suffix.lower() not in (".mp4", ".webm", ".mov")
                        or item.get("type", "output") != "output"):
                    continue
                path = (output_root / subfolder / filename).resolve()
                if not path.is_relative_to(output_root) or not path.is_file() or path.stat().st_size == 0:
                    continue
                value = {"filename": filename, "subfolder": subfolder, "type": "output"}
                if value not in result:
                    result.append(value)
    return result


class JobStore:
    def __init__(self, root, output_root=None):
        self.root = Path(root).resolve()
        self.output_root = Path(output_root).resolve() if output_root is not None else self.root.parent.parent / "output"

    def save(self, record):
        identifier = job_id(record["id"])
        self.root.mkdir(parents=True, exist_ok=True)
        target = self.root / (identifier + ".json")
        temporary = self.root / (identifier + "." + uuid.uuid4().hex + ".tmp")
        try:
            temporary.write_text(json.dumps(redact(record), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)

    def read(self, identifier):
        target = self.root / (job_id(identifier) + ".json")
        if not target.resolve().is_relative_to(self.root) or not target.is_file():
            raise KeyError("Geração não encontrada na biblioteca do Studio.")
        record = json.loads(target.read_text(encoding="utf-8"))
        if (not isinstance(record, dict) or record.get("id") != identifier
                or record.get("status") not in TERMINAL | {"queued", "running", "unknown"}):
            raise ValueError("Registro de geração inválido.")
        return record

    def records(self, limit=100):
        if not self.root.is_dir():
            return []
        files = sorted(self.root.glob("*.json"), key=lambda p: p.stat().st_mtime_ns, reverse=True)
        result = []
        for path in files[:limit]:
            try:
                result.append(self.read(path.stem))
            except (OSError, ValueError, KeyError):
                continue
        return sorted(result, key=lambda r: r.get("created_at", ""), reverse=True)

    def refresh(self, record, queue):
        if record["status"] in TERMINAL:
            return record
        identifier = record["id"]
        updated = copy.deepcopy(record)
        history = queue.get_history(prompt_id=identifier).get(identifier)
        running, waiting = queue.get_current_queue_volatile()
        if history:
            # A later refine/temporal pass can fail after SaveVideo has written
            # the base generation. Keep those usable artifacts in the library.
            updated["outputs"] = saved_videos(history, self.output_root)
            status = history.get("status") or {}
            messages = status.get("messages", [])
            interrupted = any(m[0] == "execution_interrupted" for m in messages if isinstance(m, (list, tuple)) and m)
            if interrupted:
                updated["status"] = "cancelled"
            elif status.get("status_str") == "error":
                updated["status"] = "error"
                failure = next((m[1] for m in messages if isinstance(m, (list, tuple)) and len(m) > 1 and m[0] == "execution_error"), {})
                failure = failure if isinstance(failure, dict) else {}
                updated["error"] = redact(str(failure.get("exception_message", "A geração falhou.")))[:2000]
            elif status.get("completed") or status.get("status_str") == "success":
                expected = updated.get("summary", {}).get("outputs")
                expected_count = len(expected) if isinstance(expected, list) and expected else 1
                updated["status"] = "success" if len(updated["outputs"]) >= expected_count else "error"
                if not updated["outputs"]:
                    updated["error"] = "A geração terminou sem retornar um arquivo de vídeo."
                elif len(updated["outputs"]) < expected_count:
                    updated["error"] = (f"A geração retornou {len(updated['outputs'])} de {expected_count} vídeos previstos. "
                                        "O resultado ficou incompleto; os arquivos disponíveis foram preservados.")
        elif any(item[1] == identifier for item in running):
            updated["status"] = "running"
        elif any(item[1] == identifier for item in waiting):
            updated["status"] = "queued"
        else:
            updated["status"] = "unknown"
            updated["error"] = "A execução não está na fila atual. A receita foi preservada; o servidor pode ter reiniciado."
        if updated != record:
            self.save(updated)
        return updated

    def cancel(self, identifier, queue):
        record = self.refresh(self.read(identifier), queue)
        if record["status"] in TERMINAL:
            return {"status": record["status"], "cancelled": False, "message": "Esta geração já terminou."}
        if record["status"] == "unknown":
            return {"status": "unknown", "cancelled": False,
                    "message": "Esta geração não está na fila atual; a receita continua salva."}
        # The pinned queue checks the running ID and signals under the same lock.
        # A global interrupt would risk cancelling another user's next job.
        cancelled = queue.delete_queue_item(lambda item: item[1] == identifier)
        if cancelled:
            record["status"] = "cancelled"
            self.save(record)
        else:
            cancelled = queue.interrupt_if_running(identifier)
        return {"status": record["status"], "cancelled": bool(cancelled),
                "message": "Cancelamento solicitado para esta geração." if cancelled else "A geração já não está em execução."}


def register_job_routes(server):
    from aiohttp import web
    import execution
    import folder_paths
    import torch
    from comfy.cli_args import args
    from .studio_routes import prepare_recipe
    from .studio_recipe import _validate

    store = JobStore(Path(os.environ.get("H3MAX_ROOT", "/workspace/h3max")) / "studio" / "jobs",
                     folder_paths.get_output_directory())

    def public(record):
        return redact({key: value for key, value in record.items() if key != "prompt"})

    @server.routes.get("/h3max/api/jobs")
    async def list_jobs(request):
        return web.json_response({"jobs": [public(store.refresh(r, server.prompt_queue)) for r in store.records()]})

    @server.routes.get("/h3max/api/jobs/{identifier}")
    async def get_job(request):
        try:
            record = store.read(request.match_info["identifier"])
            return web.json_response(public(store.refresh(record, server.prompt_queue)))
        except (KeyError, ValueError) as exc:
            return web.json_response({"error": str(exc)}, status=404)

    @server.routes.get("/h3max/api/jobs/{identifier}/graph")
    async def get_graph(request):
        try:
            record = store.read(request.match_info["identifier"])
            return web.json_response(redact({"prompt": record["prompt"],
                "summary": record["summary"], "required_models": record.get("required_models", []),
                "source": "saved_job", "job_id": record["id"], "status": record["status"]}))
        except (KeyError, ValueError) as exc:
            return web.json_response({"error": str(exc)}, status=404)

    @server.routes.post("/h3max/api/jobs")
    async def submit_job(request):
        record = None
        try:
            if args.cpu or not torch.cuda.is_available():
                raise ValueError("A geração aguarda uma GPU disponível no servidor.")
            if request.content_length and request.content_length > 128 * 1024:
                raise ValueError("Solicitação muito longa.")
            raw = await request.read()
            if len(raw) > 128 * 1024:
                raise ValueError("Solicitação muito longa.")
            body = json.loads(raw)
            if not isinstance(body, dict) or not isinstance(body.get("request"), dict):
                raise ValueError("Envie a receita completa da cena.")
            result = await prepare_recipe(body["request"], folder_paths)
            identifier = str(uuid.uuid4())
            settings = _validate({**body["request"], "seed": result["summary"]["seed"],
                                  "model": result["summary"]["engine"]})
            settings.pop("engine", None)
            payload = {"prompt": result["prompt"], "extra_data": {"extra_pnginfo": {"h3max": result["summary"]}}}
            client_id = body.get("client_id")
            if client_id is not None:
                if not isinstance(client_id, str) or len(client_id) > 128:
                    raise ValueError("Identificador de cliente inválido.")
                payload["client_id"] = client_id
            payload = server.trigger_on_prompt(payload)
            prompt = payload["prompt"]
            server.node_replace_manager.apply_replacements(prompt)
            valid = await execution.validate_prompt(identifier, prompt, None)
            if not valid[0]:
                return web.json_response(redact({"error": valid[1], "node_errors": valid[3]}), status=400)
            record = {"id": identifier, "status": "queued", "recipe_version": 1,
                      "created_at": datetime.now(timezone.utc).isoformat(), "request": settings,
                      "summary": result["summary"], "prompt": prompt,
                      "required_models": result["required_models"], "outputs": []}
            # Record the complete recipe BEFORE putting it into the paid GPU queue.
            store.save(record)
            extra = payload.get("extra_data", {})
            if client_id is not None:
                extra["client_id"] = client_id
            extra["create_time"] = int(time.time() * 1000)
            sensitive = {key: extra.pop(key) for key in execution.SENSITIVE_EXTRA_DATA_KEYS if key in extra}
            number = server.number
            server.number += 1
            server.prompt_queue.put((number, identifier, prompt, extra, valid[2], sensitive))
            return web.json_response(redact({"prompt_id": identifier, "summary": result["summary"], "request": settings}))
        except Exception as exc:
            message = redact(str(exc))
            if record is not None:
                record.update(status="error", error=message)
                with suppress(OSError):
                    store.save(record)
            return web.json_response({"error": message, "message": message},
                                     status=400 if isinstance(exc, (ValueError, TypeError, KeyError)) else 500)

    @server.routes.post("/h3max/api/jobs/{identifier}/cancel")
    async def cancel_job(request):
        try:
            return web.json_response(store.cancel(request.match_info["identifier"], server.prompt_queue))
        except (ValueError, KeyError) as exc:
            return web.json_response({"error": str(exc)}, status=404)

    async def journal_lifecycle(app):
        async def watch():
            while True:
                for record in store.records(limit=None):
                    with suppress(OSError, KeyError, ValueError):
                        store.refresh(record, server.prompt_queue)
                await asyncio.sleep(WATCH_INTERVAL_SECONDS)
        task = asyncio.create_task(watch())
        yield
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
    server.app.cleanup_ctx.append(journal_lifecycle)
