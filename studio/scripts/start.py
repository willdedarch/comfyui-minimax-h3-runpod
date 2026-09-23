#!/usr/bin/env python3
"""Runpod startup hook; H3MAX_ROOT owns models and user data."""
from __future__ import annotations
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from runtime_env import configure_environment

PACKAGE = Path(__file__).resolve().parents[1]
COMFY = Path("/opt/ComfyUI")

def extra_arguments():
    extra = json.loads(os.environ.get("H3MAX_COMFY_ARGS", "[]"))
    if not isinstance(extra, list) or not all(isinstance(v, str) for v in extra):
        raise ValueError("H3MAX_COMFY_ARGS must be a JSON array of strings")
    # Validate before the download. The port and directories are managed by
    # this launcher, regardless of the Pod's storage choice.
    reserved = {"--input-directory", "--output-directory", "--user-directory",
                "--temp-directory", "--base-directory", "--models-directory", "--port"}
    if any(value.split("=", 1)[0] in reserved for value in extra):
        raise ValueError("H3MAX_COMFY_ARGS cannot override template directories or port; use H3MAX_ROOT for storage")
    return extra


def main():
    extra = extra_arguments()
    root = Path(os.environ.get("H3MAX_ROOT", "/workspace/h3max")).resolve()
    configure_environment(root)
    for child in ("models", "input", "output", "user/default/workflows/H3_MAX", "temp", "logs"):
        (root / child).mkdir(parents=True, exist_ok=True)
    # Runpod can mount /opt/ComfyUI/models on another filesystem. Moving or
    # replacing that directory fails with EXDEV on a real Pod. The pinned
    # ComfyUI supports --models-directory, so leave the image directory alone.
    for source in (PACKAGE / "workflows").glob("*.json"):
        dest = root / "user/default/workflows/H3_MAX" / source.name
        if not dest.exists():
            shutil.copy2(source, dest)
    if os.environ.get("H3MAX_DOWNLOAD_MODELS", "1") == "1":
        subprocess.run([sys.executable, str(PACKAGE / "scripts/download_models.py"), "--root", str(root)], check=True)
    command = [sys.executable, str(COMFY / "main.py"), "--listen", "0.0.0.0", "--port", "8188",
               "--models-directory", str(root / "models"),
               "--input-directory", str(root / "input"), "--output-directory", str(root / "output"),
               "--user-directory", str(root / "user"), "--temp-directory", str(root / "temp"), *extra]
    os.chdir(COMFY)
    print("Starting H3 Studio on port 8188 (/h3max). Models and results use H3MAX_ROOT.", flush=True)
    # Inherit stdout/stderr so startup failures appear in Runpod container logs.
    os.execv(sys.executable, command)

if __name__ == "__main__":
    main()
