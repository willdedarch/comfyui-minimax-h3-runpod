#!/usr/bin/env python3
"""CPU-only container boot check. Never downloads weights or submits inference."""
from __future__ import annotations
import argparse
import importlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.request

PACKAGE = Path(__file__).resolve().parents[1]


def check_studio(url, info):
    """Validate the actual server UI and dynamic recipes, without queueing jobs."""
    from check_runtime import validate_prompt_schema
    for route, expected in (("/h3max", "text/html"), ("/h3max/studio.js", "javascript"),
                            ("/h3max/studio.css", "text/css")):
        with urllib.request.urlopen(url + route, timeout=10) as response:
            if expected not in response.headers.get("Content-Type", "") or not response.read():
                raise RuntimeError("Studio asset not served correctly: " + route)
    with urllib.request.urlopen(url + "/", timeout=10) as response:
        if not response.url.endswith("/h3max"):
            raise RuntimeError("The default page must open Studio")
    with urllib.request.urlopen(url + "/h3max/api/capabilities", timeout=10) as response:
        capabilities = json.load(response)
    if capabilities["runtime_ready"] or capabilities["preview"]:
        raise RuntimeError("CPU boot must not advertise GPU generation or a local preview")
    with urllib.request.urlopen(url + "/h3max/api/jobs", timeout=10) as response:
        if json.load(response).get("jobs") != []:
            raise RuntimeError("A clean Studio image must start with an empty library")
    request = urllib.request.Request(url + "/h3max/api/jobs",
        data=json.dumps({"request": {"prompt": "CPU boot check"}}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        urllib.request.urlopen(request, timeout=10)
    except urllib.error.HTTPError as error:
        if error.code != 400 or "GPU" not in error.read().decode():
            raise RuntimeError("Studio must reject generation without a GPU") from error
    else:
        raise RuntimeError("Studio accepted generation without a GPU")
    spec = importlib.util.spec_from_file_location("studio_build_recipe", PACKAGE / "custom_nodes/ComfyUI-H3MAX/studio_recipe.py")
    recipe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(recipe)
    count = 0
    for inputs in ({}, {"first_frame": "first.png", "last_frame": "last.png"},
                   {"references": ["person.png"]}, {"model": "hybrid", "references": ["person.png"]},
                   {"references": ["person.png"], "video_references": ["motion.mp4"], "audio_references": ["voice.wav"]}):
        for options in ({"motion": False}, {"refine": True}, {"temporal": True},
                        {"refine": True, "temporal": True}, {"people_realism": True, "camera_motion": True},
                        {"camera": "tracking", "camera_speed": "slow", "camera_amount": "medium", "framing": "wide"},
                        {"camera": "locked", "output_audio": False},
                        {"refine": True, "output_audio": False},
                        {"temporal": True, "output_audio": False}):
            if inputs.get("last_frame") and options.get("temporal"):
                continue  # ExactRecover does not preserve the final-frame anchor.
            graph = recipe.compile_request({"prompt": "A person walks across a courtyard.", **inputs, **options})["prompt"]
            validate_prompt_schema(graph, info, nodes_only=True)
            count += 1
    return {"studio_routes_verified": True, "studio_jobs_cpu_guard_verified": True,
            "studio_recipe_schemas_verified": count,
            "studio_gpu_render_executed": False}


def check_local_compiler():
    """Check local imports and the published contract without invoking an LLM."""
    compiler = importlib.import_module('h3ir.compile')
    if not callable(getattr(compiler, 'compile_brief', None)):
        raise RuntimeError('Installed OpenH3 compiler has no callable compile_brief')
    contract_module = importlib.import_module('h3ir.contract')
    contract = contract_module.contract()
    if not isinstance(contract, dict) or not contract.get('contract_version'):
        raise RuntimeError('Installed OpenH3 compiler returned no valid local contract')
    return {'compiler_import_verified': True, 'compiler_contract_verified': True,
            'compiler_contract_version': contract['contract_version'],
            'director_request_executed': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('/artifacts'))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    url = 'http://127.0.0.1:8188'
    report = {'cpu_boot_verified': False, 'node_schema_verified': False,
              'installed_pack_registration_verified': False,
              'compiler_import_verified': False, 'compiler_contract_verified': False,
              'director_request_executed': False, 'all_pack_nodes_executed': False,
              'package_startup_verified': False, 'base_entrypoint_executed': False,
              'gpu_render_executed': False, 'model_weights_downloaded': False}
    env = dict(os.environ, H3MAX_DOWNLOAD_MODELS='0', HF_HUB_OFFLINE='1',
               H3MAX_ROOT='/workspace/h3max', H3MAX_COMFY_ARGS='["--cpu"]')
    log_path = args.output / 'comfy-cpu-boot.log'
    try:
        report.update(check_local_compiler())
        with log_path.open('w', encoding='utf-8') as log:
            process = subprocess.Popen(
                [sys.executable, str(PACKAGE / 'scripts/start.py')],
                cwd='/opt/ComfyUI', env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 300
                while True:
                    if process.poll() is not None:
                        raise RuntimeError(f'ComfyUI exited with {process.returncode}; see {log_path}')
                    try:
                        with urllib.request.urlopen(url + '/system_stats', timeout=5) as response:
                            json.load(response)
                        break
                    except (urllib.error.URLError, TimeoutError):
                        if time.monotonic() >= deadline:
                            raise TimeoutError(f'CPU boot did not become ready; see {log_path}')
                        time.sleep(2)
                report['cpu_boot_verified'] = True
                command = Path(f'/proc/{process.pid}/cmdline').read_bytes().split(b'\0')
                if (b'--models-directory' not in command or
                    command[command.index(b'--models-directory') + 1] != b'/workspace/h3max/models'):
                    raise RuntimeError('Startup did not select the configured models directory')
                installed = Path('/workspace/h3max/user/default/workflows/H3_MAX')
                for workflow in (PACKAGE / 'workflows').glob('*.json'):
                    if not (installed / workflow.name).is_file():
                        raise RuntimeError(f'Startup did not install workflow {workflow.name}')
                report['package_startup_verified'] = True
                with urllib.request.urlopen(url + '/object_info', timeout=60) as response:
                    (args.output / 'object-info.json').write_bytes(response.read())
                result = subprocess.run(
                    [sys.executable, str(PACKAGE / 'scripts/check_runtime.py'), '--url', url, '--nodes-only'],
                    text=True, encoding='utf-8', stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=180)
                (args.output / 'registration-check.log').write_text(result.stdout, encoding='utf-8')
                print(result.stdout, flush=True)
                result.check_returncode()
                report['node_schema_verified'] = True
                report['installed_pack_registration_verified'] = True
                info = json.loads((args.output / 'object-info.json').read_text())
                report.update(check_studio(url, info))
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=20)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=10)
    finally:
        (args.output / 'image-verification.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        for name in ('python-resolved.txt', 'requirements-merged.txt', 'pip-install-report.json', 'base-torch-constraints.txt'):
            artifact = PACKAGE / name
            if artifact.exists():
                (args.output / artifact.name).write_bytes(artifact.read_bytes())


if __name__ == '__main__':
    main()
