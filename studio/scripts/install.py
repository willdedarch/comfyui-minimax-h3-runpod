#!/usr/bin/env python3
"""Image build: pinned source checkouts, dependencies, workflow installation."""
from __future__ import annotations
import importlib.metadata
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

PACKAGE = Path(__file__).resolve().parents[1]

def run(*args):
    subprocess.run(args, check=True)

def checkout(url, revision, destination):
    destination = Path(destination)
    if destination.exists():
        raise RuntimeError(f"Refusing to overwrite an existing checkout: {destination}")
    destination.mkdir(parents=True)
    run("git", "-C", str(destination), "init", "-q")
    run("git", "-C", str(destination), "remote", "add", "origin", url)
    run("git", "-C", str(destination), "fetch", "--depth", "1", "origin", revision)
    run("git", "-C", str(destination), "checkout", "--detach", "FETCH_HEAD")
    actual = subprocess.check_output(["git", "-C", str(destination), "rev-parse", "HEAD"], text=True).strip()
    if actual != revision:
        raise RuntimeError(f"Commit mismatch: {url}")

def main():
    lock = json.loads((PACKAGE / "sources.lock.json").read_text())
    checkout(lock["core"]["repository"], lock["core"]["commit"], "/opt/ComfyUI")
    # Respect the CUDA PyTorch stack supplied by the image instead of replacing it.
    constraints = []
    for name in ("torch", "torchvision", "torchaudio"):
        try:
            constraints.append(f"{name}=={importlib.metadata.version(name)}")
        except importlib.metadata.PackageNotFoundError:
            if name == "torch":
                raise
    constraint_file = PACKAGE / "base-torch-constraints.txt"
    constraint_file.write_text("\n".join(constraints) + "\n")
    pip = [sys.executable, "-m", "pip", "install", "-c", str(constraint_file)]
    requirements = [Path("/opt/ComfyUI/requirements.txt")]
    for spec in lock["custom_nodes"]:
        dest = Path("/opt/ComfyUI/custom_nodes") / spec["directory"]
        checkout(spec["repository"], spec["commit"], dest)
        req = dest / "requirements.txt"
        if req.exists():
            requirements.append(req)
    compiler = lock["compiler"]
    checkout(compiler["repository"], compiler["commit"], "/opt/open-h3-ir")
    # Resolve core, compiler and nodes together. VHS and KJNodes request two
    # OpenCV distributions sharing cv2; this headless image needs only one.
    merged = ["huggingface_hub==1.32.0"]
    for req in requirements:
        for line in req.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith(("-", ".", "/")) or "\\" in stripped:
                raise RuntimeError(f"Review requirement directive/path before merging: {req}: {line}")
            line = re.sub(r"^opencv-python(?=[<>=!~;\[\s]|$)", "opencv-python-headless", stripped)
            merged.append(line)
    merged_file = PACKAGE / "requirements-merged.txt"
    merged_file.write_text("\n".join(dict.fromkeys(merged)) + "\n", encoding="utf-8")
    run(*pip, "--report", str(PACKAGE / "pip-install-report.json"),
        "/opt/open-h3-ir", "-r", str(merged_file))
    shutil.copytree(PACKAGE / "custom_nodes/ComfyUI-H3MAX", "/opt/ComfyUI/custom_nodes/ComfyUI-H3MAX")
    run(sys.executable, "-m", "pip", "check")
    # pip check cannot detect two distributions overwriting the same cv2 files.
    opencv = [d.metadata["Name"].lower().replace("_", "-")
              for d in importlib.metadata.distributions()
              if (d.metadata["Name"] or "").lower().replace("_", "-").startswith("opencv-")]
    if opencv != ["opencv-python-headless"]:
        raise RuntimeError(f"Expected one headless OpenCV distribution, found {opencv}")
    run(sys.executable, "-c", "import cv2; print('OpenCV:', cv2.__version__)")
    (PACKAGE / "python-resolved.txt").write_text(subprocess.check_output(
        [sys.executable, "-m", "pip", "freeze"], text=True))
    run(sys.executable, str(PACKAGE / "scripts/validate.py"))

if __name__ == "__main__":
    main()
