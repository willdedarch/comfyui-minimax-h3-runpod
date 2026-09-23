"""H3 MAX convenience nodes. No model training or new inference implementation."""
from __future__ import annotations

import importlib
import os
import re
import sys
import types
from pathlib import Path


PROFILES = {
    "base": None,
    "natural": ("Motion_Repair.safetensors", 0.9),
    "acao_corporal": ("H3_Combat_V2.safetensors", 0.8),
    "acao_com_arma": ("Bunny_weapon_combatV1.safetensors", 0.45),
    "objetos_experimental": ("wushu_spatial_physics_clean_3000_pruned.safetensors", 0.35),
}


class H3MAXMotionPreset:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "model": ("MODEL",),
            "prompt": ("STRING", {"multiline": True, "forceInput": True}),
            "profile": (list(PROFILES), {"default": "natural"}),
            "motion_multiplier": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.5, "step": 0.05}),
            "people_realism": ("BOOLEAN", {"default": False}),
            "people_strength": ("FLOAT", {"default": 0.65, "min": 0.0, "max": 1.0, "step": 0.05}),
            "camera_motion": ("BOOLEAN", {"default": False}),
            "camera_strength": ("FLOAT", {"default": 0.8, "min": 0.0, "max": 1.2, "step": 0.05}),
        }}

    RETURN_TYPES = ("MODEL", "STRING")
    RETURN_NAMES = ("model", "prompt")
    FUNCTION = "apply"
    CATEGORY = "H3 MAX"

    def apply(self, model, prompt, profile, motion_multiplier, people_realism,
              people_strength, camera_motion, camera_strength):
        import nodes
        choices = []
        if profile not in PROFILES:
            raise ValueError(f"Unknown H3 MAX profile: {profile}")
        motion = PROFILES[profile]
        triggers = []
        if motion and motion_multiplier:
            choices.append((motion[0], motion[1] * motion_multiplier))
            if profile == "acao_com_arma" and not re.search(r"\bBUNNY\b", prompt):
                triggers.append("BUNNY")
        if people_realism and people_strength:
            choices.append(("h3-realism-people-t2v-i2v-r2v.safetensors", people_strength))
            if "r34l1sm" not in prompt:
                triggers.append("r34l1sm")
        if camera_motion and camera_strength:
            choices.append(("camera_motion_h3_lora_v1_3000_pruned.safetensors", camera_strength))
            # The author's camera trigger must remain first even with realism.
            prompt = re.sub(r"^\s*camera motion\b[\s,]*", "", prompt, count=1, flags=re.I)
            triggers.insert(0, "camera motion")
        for filename, strength in choices:
            model = nodes.LoraLoaderModelOnly().load_lora_model_only(model, filename, strength)[0]
        if triggers:
            prompt = ", ".join(triggers) + "\n\n" + prompt
        return (model, prompt)


class H3MAXDirectorText:
    """Call the pinned OpenH3 compiler without loading MODEL, CLIP or VAE.

    This initial adapter compiles TEXT only. Image references go directly to H3.
    The endpoint/key are runtime environment variables, never workflow widgets.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "prompt": ("STRING", {"multiline": True}),
            "enabled": ("BOOLEAN", {"default": False}),
            "seconds": ("FLOAT", {"default": 124 / 24, "min": 1, "max": 30}),
            "aspect": (["16:9", "9:16", "1:1", "4:3", "3:4"],),
            "seed": ("INT", {"default": 123456, "min": 0, "max": 2**63 - 1, "control_after_generate": False}),
        }}

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("prompt",)
    FUNCTION = "compile"
    CATEGORY = "H3 MAX"

    def compile(self, prompt, enabled, seconds, aspect, seed):
        if not enabled:
            return (prompt,)
        url = os.environ.get("H3IR_LLM_URL", "").strip()
        model = os.environ.get("H3IR_LLM_MODEL", "").strip()
        if not url or not model:
            raise RuntimeError("Director enabled: set H3IR_LLM_URL and H3IR_LLM_MODEL in the Pod environment.")
        pack = Path(__file__).resolve().parent.parent / "ComfyUI-OpenH3-IR"
        alias = "_h3max_pinned_openh3ir"
        if alias not in sys.modules:
            namespace = types.ModuleType(alias)
            namespace.__path__ = [str(pack)]
            sys.modules[alias] = namespace
        client = importlib.import_module(alias + ".h3ir_client")
        compiler = importlib.import_module(alias + ".compiler")
        payload = client.build_payload(
            prompt, seconds=seconds, aspect=aspect, creativity="restrained",
            effort="standard", megapixels=0.9, seed=seed, silent=False,
            shots=1, assets=[], transcripts={},
        )
        def no_asset_hash(path):
            raise RuntimeError("The text-only director cannot read media assets.")
        result = compiler.compile_here(payload, sha_of=no_asset_hash,
                                       llm_url=url, llm_model=model, timeout=300)
        if result.get("degraded"):
            raise RuntimeError("OpenH3 compiler fell back: " + str(result.get("fallback_reason")))
        compiled = result.get("prompt")
        if not isinstance(compiled, str) or not compiled.strip():
            raise RuntimeError("OpenH3 compiler returned no prompt.")
        return (compiled,)


NODE_CLASS_MAPPINGS = {"H3MAXMotionPreset": H3MAXMotionPreset,
                       "H3MAXDirectorText": H3MAXDirectorText}
NODE_DISPLAY_NAME_MAPPINGS = {"H3MAXMotionPreset": "H3 MAX — perfil de movimento",
                              "H3MAXDirectorText": "H3 MAX — prompt / diretor de texto"}

# ComfyUI loads this package after creating PromptServer. Keep plain-Python
# contract tests importable without importing the GPU/server dependencies.
try:
    from server import PromptServer
except ModuleNotFoundError as exc:
    if exc.name != "server":
        raise
else:
    from .studio_media import H3MAXReferenceVideo
    from .studio_routes import register_routes
    from .studio_jobs import register_job_routes
    NODE_CLASS_MAPPINGS["H3MAXReferenceVideo"] = H3MAXReferenceVideo
    NODE_DISPLAY_NAME_MAPPINGS["H3MAXReferenceVideo"] = "H3 Studio — referência de vídeo a 24 fps"
    register_routes(PromptServer.instance)
    register_job_routes(PromptServer.instance)
