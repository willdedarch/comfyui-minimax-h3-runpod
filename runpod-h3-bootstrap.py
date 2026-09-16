"""Official Runpod MiniMax H3 bootstrap for I2V, R2V, or both."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import shutil
import secrets

WORKFLOW_COMMIT = "aaac56dd5cc5497533d92cbe50edc35ea660e587"
BASE_REV = "a98869194787969724c7425d95d0ed73ce9202af"
LORA_REV = "3ec17a324ced54151364f24f8b5fb6bf7e26414f"
MODELS = [
    ("Comfy-Org/MiniMax-H3", BASE_REV, "diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors", "diffusion_models", 20970379616, "e889202c41dafb67b10d67b97f0d8541508036a6090af23425a5c2615d03c47a"),
    ("Comfy-Org/MiniMax-H3", BASE_REV, "text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors", "text_encoders", 15687142551, "35a88d51044231fe332301d7a62aa81e3f2cba62febeb446e2c1e3e0ef76f2c6"),
    ("Comfy-Org/MiniMax-H3", BASE_REV, "vae/minimax_h3_video_vae_fp16.safetensors", "vae", 5207808496, "7c1f131492e7eddacaac9069a61b81bdd39de5cc96561e677c5eab1cdce5e522"),
    ("Comfy-Org/MiniMax-H3", BASE_REV, "vae/minimax_h3_audio_vae_fp32.safetensors", "vae", 605254808, "8e505d95dd1561d47abd43d4238fd40d9bb1ae9e147ed0a4cba778d76ae4db48"),
    ("lightx2v/Minimax-h3-Turbo", LORA_REV, "minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors", "loras", 1956193000, "2339acdf19bfe123f46b971ea35d367a84adb85de43627e1eceafa5a5b2b111e"),
]
I2V_MODELS = list(MODELS)
R2V_MODELS = list(MODELS)
R2V_MODELS[0] = ("Comfy-Org/MiniMax-H3", BASE_REV, "diffusion_models/minimax_h3_ref2va_pruned_int8_convrot.safetensors", "diffusion_models", 20970379616, "9255f52b6677845ad238f20dfaafa94727053694127ab7f255c048f0f9365779")
R2V_MODELS[4] = ("Comfy-Org/MiniMax-H3", BASE_REV, "loras/minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors", "loras", 1956193000, "5b9ab5ade15d0775676d01a907268a69a1468dc6033b3b0d3ded5502f3ebb84c")
PROFILE_MODELS = {"i2v": I2V_MODELS, "r2v": R2V_MODELS}
PROFILE = os.environ.get("H3_PROFILE", "i2v")
if PROFILE not in {"i2v", "r2v", "both"}:
    raise ValueError("H3_PROFILE must be i2v, r2v, or both")
PROFILES = ("i2v", "r2v") if PROFILE == "both" else (PROFILE,)
# The encoder and VAEs are shared; download and verify each file only once.
MODELS = list(dict.fromkeys(model for profile in PROFILES for model in PROFILE_MODELS[profile]))

def run(*args, **kwargs):
    subprocess.run(args, check=True, **kwargs)

def download(url, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    run("curl", "--fail", "--location", "--retry", "5", "--retry-all-errors", "--connect-timeout", "30", "--output", str(destination), url)

def install_workflows(root):
    for profile in PROFILES:
        workflow_url = f"https://raw.githubusercontent.com/Comfy-Org/workflow_templates/{WORKFLOW_COMMIT}/templates/video_minimax_h3_{profile}.json"
        workflow_file = root / f"user/default/workflows/MiniMax H3 - Official {profile.upper()}.json"
        download(workflow_url, workflow_file)
        workflow = json.loads(workflow_file.read_text())
        all_text = json.dumps(workflow)
        for _, _, source, _, _, _ in PROFILE_MODELS[profile]:
            if Path(source).name not in all_text:
                raise RuntimeError("Official workflow does not reference " + source)
        # Keep both official graphs intact and provide their stock image inputs.
        for node in workflow.get("nodes", []):
            if node.get("type") == "LoadImage":
                name = node["widgets_values"][0]
                if Path(name).name != name:
                    raise RuntimeError("Unexpected example image path")
                url = f"https://raw.githubusercontent.com/Comfy-Org/workflow_templates/{WORKFLOW_COMMIT}/input/{name}"
                try:
                    download(url, root / "input" / name)
                except subprocess.CalledProcessError:
                    print("Upload your reference or first-frame image before generating.", flush=True)

def main():
    root = Path("/workspace/runpod-slim/ComfyUI")
    root.parent.mkdir(parents=True, exist_ok=True)
    print("H3: preparing the official Runpod ComfyUI bundle", flush=True)
    baked = Path("/opt/comfyui-baked")
    if not (baked / "main.py").is_file():
        raise RuntimeError("Official ComfyUI image bundle is missing")
    if not root.exists():
        shutil.copytree(baked, root)
    import torch
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA GPU unavailable")
    print("GPU:", torch.cuda.get_device_name(0), "CUDA:", torch.version.cuda, flush=True)
    from huggingface_hub import hf_hub_download
    for repo, revision, source, folder, size, digest in MODELS:
        print("H3: downloading and verifying", source, flush=True)
        target = root / "models" / folder / Path(source).name
        if target.is_file() and target.stat().st_size == size:
            with target.open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() == digest:
                    print("H3: verified existing file", target.name, flush=True)
                    continue
        # Flat filenames match the official local workflow. New disposable pods
        # always download; an interrupted boot can resume its own partial files.
        cache_root = root / ".downloads" / repo.replace("/", "_")
        fetched = Path(hf_hub_download(repo_id=repo, filename=source, revision=revision, local_dir=str(cache_root)))
        if fetched.stat().st_size != size:
            raise RuntimeError("Incorrect model size: " + source)
        with fetched.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual != digest:
            raise RuntimeError("Incorrect SHA256: " + source)
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(fetched, target)
    install_workflows(root)
    (root / "h3-model-manifest.json").write_text(json.dumps(MODELS, indent=2))
    print(f"H3: {len(MODELS)} model hashes verified; workflows: {', '.join(PROFILES)}. Starting official Runpod services.", flush=True)
    os.environ.setdefault("JUPYTER_PASSWORD", secrets.token_urlsafe(24))
    os.environ.setdefault("FILEBROWSER_PASSWORD", secrets.token_urlsafe(24))
    os.execv("/bin/bash", ["bash", "/start.sh"])

if __name__ == "__main__":
    main()
