#!/usr/bin/env python3
"""Check live ComfyUI contracts; a GPU render requires --queue-smoke."""
from __future__ import annotations
import argparse
import copy
import json
from pathlib import Path
import time
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
FILE_INPUTS = {
    ("UNETLoader", "unet_name"), ("CLIPLoader", "clip_name"), ("VAELoader", "vae_name"),
    ("MiniMaxH3HybridLoader", "base_model"), ("MiniMaxH3HybridLoader", "overlay_model"),
    ("MinimaxH3LatentUpscaler3DRefineHandoff", "model_name"), ("LoadImage", "image"),
    ("LoadAudio", "audio"), ("H3MAXReferenceVideo", "file"),
}


def request(base, path, payload=None):
    body = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(base.rstrip("/") + path, data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"ComfyUI HTTP {exc.code} on {path}: {detail}") from exc


def expand_inputs(schema, live, prefix=""):
    """Expand the pinned V3 DynamicCombo/Autogrow /object_info contracts."""
    result = {}
    for category in ("required", "optional"):
        for name, spec in schema.get(category, {}).items():
            key, kind = prefix + name, spec[0]
            opts = spec[1] if len(spec) > 1 else {}
            if kind == "COMFY_AUTOGROW_V3":
                template = opts["template"]
                names = template.get("names")
                if names is None:
                    names = [template["prefix"] + str(i) for i in range(template["max"])]
                entries = [(cat, value) for cat in ("required", "optional")
                           for value in template["input"].get(cat, {}).values()]
                if len(entries) != 1:
                    raise ValueError(f"Unsupported Autogrow template: {key}")
                cat, child = entries[0]
                for i, child_name in enumerate(names):
                    result[key + "." + child_name] = (cat == "required" and i < template.get("min", 0), child)
            elif kind == "COMFY_DYNAMICCOMBO_V3":
                choices = {option["key"]: option["inputs"] for option in opts["options"]}
                result[key] = (category == "required", [list(choices)])
                if key in live and isinstance(live[key], str) and live[key] in choices:
                    result.update(expand_inputs(choices[live[key]], live, key + "."))
            elif isinstance(kind, str) and kind.startswith("COMFY_"):
                raise ValueError(f"Unsupported dynamic contract: {key} ({kind})")
            else:
                result[key] = (category == "required", spec)
    return result


def validate_prompt_schema(prompt, info, *, nodes_only=False, check_images=False):
    errors = []
    for node_id, node in prompt.items():
        kind, inputs = node["class_type"], node["inputs"]
        label = f"{node_id}/{kind}"
        if kind not in info:
            errors.append(f"{label}: node not registered")
            continue
        try:
            schema = expand_inputs(info[kind]["input"], inputs)
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(f"{label}: cannot expand schema: {exc}")
            continue
        for key in inputs.keys() - schema.keys():
            errors.append(f"{label}: unknown input {key}")
        for key, (required, spec) in schema.items():
            if key not in inputs:
                if required:
                    errors.append(f"{label}: missing required input {key}")
                continue
            value, expected = inputs[key], spec[0]
            options = spec[1] if len(spec) > 1 else {}
            if isinstance(value, list):
                if len(value) != 2 or not isinstance(value[0], str) or type(value[1]) is not int:
                    errors.append(f"{label}.{key}: malformed link")
                    continue
                source = prompt.get(value[0])
                outputs = info.get(source["class_type"], {}).get("output", []) if source else []
                if not 0 <= value[1] < len(outputs):
                    errors.append(f"{label}.{key}: missing source or output slot {value!r}")
                elif not isinstance(expected, list) and expected != "*" and outputs[value[1]] not in (expected, "*"):
                    errors.append(f"{label}.{key}: expects {expected}, got {outputs[value[1]]}")
                continue
            if (kind, key) in FILE_INPUTS and (nodes_only or (kind == "LoadImage" and not check_images)):
                continue
            choices = expected if isinstance(expected, list) else options.get("options") if expected == "COMBO" else None
            if choices is not None:
                if value not in choices:
                    errors.append(f"{label}.{key}: unavailable choice {value!r}")
            elif expected == "INT" and type(value) is not int:
                errors.append(f"{label}.{key}: expected INT")
            elif expected == "FLOAT" and type(value) not in (int, float):
                errors.append(f"{label}.{key}: expected FLOAT")
            elif expected == "BOOLEAN" and type(value) is not bool:
                errors.append(f"{label}.{key}: expected BOOLEAN")
            elif expected == "STRING" and not isinstance(value, str):
                errors.append(f"{label}.{key}: expected STRING")
            if type(value) in (int, float):
                if "min" in options and value < options["min"]:
                    errors.append(f"{label}.{key}: below minimum {options['min']}")
                if "max" in options and value > options["max"]:
                    errors.append(f"{label}.{key}: above maximum {options['max']}")
    if errors:
        raise RuntimeError("Schema validation failed:\n" + "\n".join(errors))


def validate_pack_registration(info, *, root=ROOT, workflow_types=()):
    """Require visible registration from every installed pack, including unused ones.

    The pinned ComfyUI core sets RELATIVE_PYTHON_MODULE for V1 and V3 nodes
    and exports it as python_module in /object_info. One registered node proves
    pack presence, not that every optional node or its lazy dependencies work.
    """
    lock = json.loads((root / "sources.lock.json").read_text(encoding="utf-8"))
    directories = [spec["directory"] for spec in lock["custom_nodes"]] + ["ComfyUI-H3MAX"]
    used = set(workflow_types)
    report, missing = {}, []
    for directory in directories:
        module = "custom_nodes." + directory
        registered = {name for name, schema in info.items() if schema.get("python_module") == module}
        if not registered:
            missing.append(directory)
        report[directory] = {"python_module": module,
                             "registered_node_count": len(registered),
                             "workflow_node_count": len(registered & used)}
    if missing:
        raise RuntimeError("Installed packs without visible node registrations: " + ", ".join(missing))
    return report


def validate_nodes(info, *, root=ROOT, nodes_only=False):
    workflows = sorted((root / "workflows").glob("*.json"))
    used = {node["type"] for path in workflows for node in json.loads(path.read_text(encoding="utf-8"))["nodes"]}
    packs = validate_pack_registration(info, root=root, workflow_types=used)
    missing = sorted(used - info.keys())
    if missing:
        raise RuntimeError("Missing node registrations: " + ", ".join(missing))
    checked = []
    for workflow in workflows:
        path = root / "api_prompts" / workflow.name
        if not path.is_file():
            raise RuntimeError(f"Missing API prompt: {path.name}")
        validate_prompt_schema(json.loads(path.read_text(encoding="utf-8")), info, nodes_only=nodes_only)
        checked.append(path.name)
    if not nodes_only:
        choices = set(info.get("LoraLoaderModelOnly", {}).get("input", {}).get("required", {}).get("lora_name", [[]])[0])
        manifest = json.loads((root / "models.lock.json").read_text(encoding="utf-8"))
        expected = {Path(m["destination"]).name for m in manifest["models"]
                    if m["destination"].replace("\\", "/").startswith("models/loras/") and "h3" in m.get("groups", [])}
        if expected - choices:
            raise RuntimeError("Missing preset LoRAs: " + ", ".join(sorted(expected - choices)))
    return {"node_registration": "passed", "schema_validation": "passed", "node_types": len(used),
            "installed_pack_registration": "passed", "installed_packs": packs,
            "all_pack_nodes_executed": False, "director_request_executed": False,
            "api_prompts_checked": checked, "model_availability_checked": not nodes_only,
            "gpu_render_executed": False, "quality_comparison_executed": False}


def smoke_prompt(prompt, images=(), profile=None):
    prompt = copy.deepcopy(prompt)
    loaders = [node for node in prompt.values() if node["class_type"] == "LoadImage"]
    if len(images) != len(loaders):
        raise ValueError(f"This workflow needs {len(loaders)} --image arguments naming existing ComfyUI input files")
    for node, filename in zip(loaders, images):
        node["inputs"]["image"] = filename
    for node in prompt.values():
        kind, inputs = node["class_type"], node["inputs"]
        if kind in ("MiniMaxH3ImageToVideo", "MiniMaxH3ReferenceToVideo"):
            inputs.update(width=640, height=384)
            if not isinstance(inputs["length"], list):
                inputs["length"] = 39
        elif kind == "BasicScheduler":
            inputs["steps"] = 8
        elif kind == "H3InjectSchedule":
            inputs["total_steps"] = 8
        elif kind == "H3JerkOracle":
            inputs["length"] = 39
        elif kind == "H3MAXDirectorText":
            inputs.update(enabled=False, seconds=39 / 24)
        elif kind == "H3MAXMotionPreset" and profile:
            inputs["profile"] = profile
        elif kind == "MinimaxH3LatentUpscaler3DRefineHandoff":
            inputs["megapixels"] = 0.5
        elif kind == "SaveVideo":
            inputs["filename_prefix"] = "H3_MAX/SMOKE_NOT_QUALITY_BENCHMARK"
    return prompt


def saved_files(outputs):
    if isinstance(outputs, dict):
        if outputs.get("filename") and outputs.get("type") == "output":
            yield outputs
        for value in outputs.values():
            yield from saved_files(value)
    elif isinstance(outputs, list):
        for value in outputs:
            yield from saved_files(value)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8188")
    parser.add_argument("--nodes-only", action="store_true", help="Check registration and all API schemas without requiring weights/input images. No render.")
    parser.add_argument("--queue-smoke", action="store_true", help="Render a short smoke test. Uses paid GPU time; advanced paths use additional passes.")
    parser.add_argument("--workflow", default="01_H3_MAX_TEXTO", help="API prompt stem from api_prompts/.")
    parser.add_argument("--image", action="append", default=[], help="Existing ComfyUI input filename, once per image loader.")
    parser.add_argument("--profile", choices=["base", "natural", "acao_corporal", "acao_com_arma", "objetos_experimental"])
    parser.add_argument("--timeout-seconds", type=int, default=3600)
    parser.add_argument("--report", type=Path, help="Write the actual check result as JSON.")
    args = parser.parse_args()
    if args.nodes_only and args.queue_smoke:
        parser.error("--nodes-only cannot be combined with --queue-smoke")
    if Path(args.workflow).name != args.workflow:
        parser.error("--workflow must be a filename stem, not a path")
    info = request(args.url, "/object_info")
    report = validate_nodes(info, nodes_only=args.nodes_only)
    report["system"] = request(args.url, "/system_stats")
    print(json.dumps(report, ensure_ascii=False), flush=True)
    if args.queue_smoke:
        path = ROOT / "api_prompts" / (args.workflow.removesuffix(".json") + ".json")
        prompt = smoke_prompt(json.loads(path.read_text(encoding="utf-8")), args.image, args.profile)
        validate_prompt_schema(prompt, info, check_images=True)
        response = request(args.url, "/prompt", {"prompt": prompt, "client_id": str(uuid.uuid4())})
        if response.get("node_errors") or not response.get("prompt_id"):
            raise RuntimeError(json.dumps(response))
        prompt_id = response["prompt_id"]
        print(f"Queued smoke render {prompt_id}", flush=True)
        deadline = time.monotonic() + args.timeout_seconds
        while time.monotonic() < deadline:
            history = request(args.url, "/history/" + prompt_id)
            if prompt_id in history:
                result = history[prompt_id]
                if result.get("status", {}).get("status_str") != "success":
                    raise RuntimeError("GPU smoke failed: " + json.dumps(result, ensure_ascii=False))
                files = list(saved_files(result.get("outputs", {})))
                if not files:
                    raise RuntimeError("Smoke reported success but returned no saved output file")
                report.update(gpu_render_executed=True, workflow=path.name, prompt_id=prompt_id, output_files=files)
                print(json.dumps(report, ensure_ascii=False), flush=True)
                break
            time.sleep(10)
        else:
            raise TimeoutError(f"Render still pending. It was NOT canceled: {prompt_id}")
    if args.report:
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
