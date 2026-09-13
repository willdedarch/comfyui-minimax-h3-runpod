# ComfyUI MiniMax H3 for disposable Runpod Pods

Based on the official `runpod/comfyui:1.4.7-cuda13.0` image, pinned by digest.
The entrypoint copies the official bundled ComfyUI, downloads five exact models
from pinned upstream revisions, validates SHA-256 and size, installs the official
I2V workflow, and starts the original `/start.sh` services.

Use an RTX PRO 6000 96 GB with a CUDA 13.0-compatible driver, 150 GB container
disk and no network volume. Expose HTTP ports 8188 (ComfyUI), 8888 (Jupyter),
and 8080 (FileBrowser). Enable Runpod's Jupyter password generation.
Set FILEBROWSER_PASSWORD to your own password if using FileBrowser; otherwise
the bootstrap generates an inaccessible random password for that service.

Each new Pod downloads about 45 GB. Existing complete files in the same Pod
are verified and reused after an interrupted/repeated boot. Download outputs
before terminating: no files persist after Pod termination.

## Exact files

From `Comfy-Org/MiniMax-H3`:
- `diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors`
- `text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors`
- `vae/minimax_h3_video_vae_fp16.safetensors`
- `vae/minimax_h3_audio_vae_fp32.safetensors`

From `lightx2v/Minimax-h3-Turbo`:
- `minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors`

ComfyUI opens on port 8188 after download and validation finish. The saved graph
is `MiniMax H3 - Official I2V.json`; supply your own first-frame image.
The official graph and its default settings remain unchanged.

The CI checks image structure and workflow/model compatibility. It does not
perform GPU inference or download the model weights. GPU generation remains
unverified until an actual Pod is tested.
