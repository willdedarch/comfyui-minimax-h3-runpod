#!/usr/bin/env python3
"""Runpod startup hook; the /workspace mount owns all user data."""
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
    # Validate before the download. Port and directories are part of the
    # template's health check and persistence contract.
    reserved = {"--input-directory", "--output-directory", "--user-directory",
                "--temp-directory", "--base-directory", "--port"}
    if any(value.split("=", 1)[0] in reserved for value in extra):
        raise ValueError("H3MAX_COMFY_ARGS cannot override template directories or port; use H3MAX_ROOT for storage")
    return extra


def main():
    extra = extra_arguments()
    root = Path(os.environ.get("H3MAX_ROOT", "/workspace/h3max")).resolve()
    configure_environment(root)
    for child in ("models", "input", "output", "user/default/workflows/H3_MAX", "temp", "logs"):
        (root / child).mkdir(parents=True, exist_ok=True)
    model_link = COMFY / "models"
    if not model_link.is_symlink():
        original = COMFY / "models.from-image"
        if original.exists():
            raise RuntimeError("Unexpected models.from-image directory; inspect before changing model locations")
        if model_link.exists():
            # Preserve even the placeholders. Never delete a pre-existing model directory.
            model_link.rename(original)
        model_link.symlink_to(root / "models", target_is_directory=True)
    elif model_link.resolve() != root / "models":
        raise RuntimeError("ComfyUI model link points to a different H3MAX_ROOT")
    for source in (PACKAGE / "workflows").glob("*.json"):
        dest = root / "user/default/workflows/H3_MAX" / source.name
        if not dest.exists():
            shutil.copy2(source, dest)
    if os.environ.get("H3MAX_DOWNLOAD_MODELS", "1") == "1":
        subprocess.run([sys.executable, str(PACKAGE / "scripts/download_models.py"), "--root", str(root)], check=True)
    command = [sys.executable, str(COMFY / "main.py"), "--listen", "0.0.0.0", "--port", "8188",
               "--input-directory", str(root / "input"), "--output-directory", str(root / "output"),
               "--user-directory", str(root / "user"), "--temp-directory", str(root / "temp"), *extra]
    os.chdir(COMFY)
    print("Starting H3 Studio on port 8188 (/h3max). Models and results remain on the persistent volume.", flush=True)
    # Inherit stdout/stderr so startup failures appear in Runpod container logs.
    os.execv(sys.executable, command)

if __name__ == "__main__":
    main()
