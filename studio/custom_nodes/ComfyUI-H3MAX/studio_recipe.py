"""Compile one Studio request to a native, self-contained ComfyUI API graph.

This module has no ComfyUI, Torch, filesystem, network, or GPU dependency. The
server must check uploaded media, installed models and the runtime node schemas
before queuing the returned graph. Compiling a recipe is not a quality test.
"""
from __future__ import annotations

import re
import secrets
from pathlib import PurePosixPath


FPS = 24
MAX_SEED = 2**53 - 1  # Exact through browser JSON and Python.
BASE_SIZE = {"16:9": (1280, 736), "9:16": (736, 1280), "1:1": (960, 960)}
REFINE_SIZE = {"16:9": (1664, 960), "9:16": (960, 1664), "1:1": (1248, 1248)}
FRAMES = {5: 124, 10: 243}  # The native 17k+5 grid, at 24 fps.
MODELS = {
    "fl2va": ("diffusion_models", "minimax_h3_fl2va_pruned_int8_convrot.safetensors"),
    "ref2va": ("diffusion_models", "minimax_h3_ref2va_pruned_int8_convrot.safetensors"),
    "encoder": ("text_encoders", "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"),
    "video_vae": ("vae", "minimax_h3_video_vae_int8_convrot.safetensors"),
    "audio_vae": ("vae", "minimax_h3_audio_vae_fp32.safetensors"),
    "natural": ("loras", "Motion_Repair.safetensors"),
    "action": ("loras", "H3_Combat_V2.safetensors"),
    "weapon": ("loras", "Bunny_weapon_combatV1.safetensors"),
    "objects": ("loras", "wushu_spatial_physics_clean_3000_pruned.safetensors"),
    "people_realism": ("loras", "h3-realism-people-t2v-i2v-r2v.safetensors"),
    "camera_motion": ("loras", "camera_motion_h3_lora_v1_3000_pruned.safetensors"),
    "refine": ("latent_upscale_models", "minimax_h3_latent_upscaler_3d_conv_v1_fp16.safetensors"),
}
PROFILES = {"natural": "natural", "action": "acao_corporal",
            "objects": "objetos_experimental", "weapon": "acao_com_arma"}
# Native text directions, following MiniMax's motion type + amplitude + speed
# guide. These do not add trajectory tensors, ControlNet, nodes or weights.
CAMERA_PRESETS = {
    "auto": "",
    "locked": "The camera holds a static shot, keeping its position and framing fixed.",
    "push_in": "The camera pushes in{amount}{speed} toward the main subject.",
    "pull_out": "The camera pulls out{amount}{speed} away from the main subject.",
    "tracking": "The camera tracks the moving subject{amount}{speed}, keeping the subject in frame.",
    "pan_left": "The camera pans left{amount}{speed} from a fixed position.",
    "pan_right": "The camera pans right{amount}{speed} from a fixed position.",
    "orbit": "The camera makes an arc shot{amount}{speed} around the main subject.",
}
CAMERA_LABELS = {"auto": "Conforme a cena", "locked": "Câmera fixa",
                 "push_in": "Aproximar", "pull_out": "Afastar", "tracking": "Acompanhar",
                 "pan_left": "Panorâmica à esquerda", "pan_right": "Panorâmica à direita",
                 "orbit": "Arco ao redor do assunto"}
CAMERA_SPEEDS = {"slow": " at slow speed", "normal": "", "fast": " at fast speed"}
CAMERA_AMOUNTS = {"subtle": " with small amplitude", "medium": "", "wide": " with large amplitude"}
FRAMING_PRESETS = {
    "auto": "",
    "wide": "Frame the main subject in a wide shot, showing the surrounding environment.",
    "medium": "Frame the main subject in a medium shot.",
    "closeup": "Frame the main subject in a close-up shot.",
}
TOGGLES = ("motion", "people_realism", "camera_motion", "refine", "temporal", "director", "output_audio")
FIELDS = {"prompt", "model", "scene", "aspect", "duration", "seed", "first_frame",
          "last_frame", "references", "video_references", "audio_references",
          "camera", "camera_speed", "camera_amount", "framing", *TOGGLES}
EXTENSIONS = {
    "image": {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"},
    "video": {".mp4", ".mov", ".webm", ".mkv"},
    "audio": {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac", ".opus"},
}


class RecipeError(ValueError):
    """An actionable request error suitable for display in the Studio."""


def _choice(request, key, allowed, default):
    value = request.get(key, default)
    if not isinstance(value, str) or value not in allowed:
        raise RecipeError(f"Opção inválida para {key}: use {', '.join(allowed)}.")
    return value


def _file(value, kind, label):
    if not isinstance(value, str) or not 1 <= len(value) <= 240:
        raise RecipeError(f"{label}: selecione um arquivo enviado ao Studio.")
    # No annotated [output]/[temp], drive, URL, encoded path, shell syntax,
    # backslash or traversal. Uploaded filenames are data, never commands.
    if (value != value.strip() or re.search(r"[^\w .()/+\-]", value)
            or value.startswith("/") or "\\" in value
            or any(part in ("", ".", "..") or part != part.strip()
                   for part in value.split("/"))):
        raise RecipeError(f"{label}: caminho de arquivo inválido.")
    if PurePosixPath(value).suffix.lower() not in EXTENSIONS[kind]:
        raise RecipeError(f"{label}: formato de {kind} não aceito.")
    return value


def _files(request, key, kind, limit):
    values = request.get(key, [])
    if not isinstance(values, list) or len(values) > limit:
        raise RecipeError(f"{key}: use no máximo {limit} arquivos.")
    return [_file(value, kind, key) for value in values]


def _validate(request):
    if not isinstance(request, dict):
        raise RecipeError("A solicitação precisa ser um objeto.")
    unknown = set(request) - FIELDS
    if unknown:
        raise RecipeError("Controles não reconhecidos: " + ", ".join(sorted(map(str, unknown))))
    prompt = request.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 12000:
        raise RecipeError("Descreva a cena em até 12.000 caracteres.")
    values = {
        "prompt": prompt.strip(),
        "model": _choice(request, "model", ("auto", "fl2va", "ref2va", "hybrid"), "auto"),
        "scene": _choice(request, "scene", tuple(PROFILES), "natural"),
        "aspect": _choice(request, "aspect", tuple(BASE_SIZE), "16:9"),
        "camera": _choice(request, "camera", tuple(CAMERA_PRESETS), "auto"),
        "camera_speed": _choice(request, "camera_speed", tuple(CAMERA_SPEEDS), "slow"),
        "camera_amount": _choice(request, "camera_amount", tuple(CAMERA_AMOUNTS), "subtle"),
        "framing": _choice(request, "framing", tuple(FRAMING_PRESETS), "auto"),
        "duration": request.get("duration", 5),
    }
    if type(values["duration"]) is not int or values["duration"] not in FRAMES:
        raise RecipeError("Escolha duração de 5 ou 10 segundos.")
    seed = request.get("seed")
    if seed is not None and (type(seed) is not int or not 0 <= seed <= MAX_SEED):
        raise RecipeError(f"A semente precisa ser um inteiro entre 0 e {MAX_SEED}.")
    values["seed"] = secrets.randbits(32) if seed is None else seed
    for key in TOGGLES:
        default = key == "output_audio" or (key == "motion" and values["scene"] != "objects")
        value = request.get(key, default)
        if type(value) is not bool:
            raise RecipeError(f"{key}: use ligado ou desligado.")
        values[key] = value
    if values["camera"] == "locked" and values["camera_motion"]:
        raise RecipeError("Câmera fixa é incompatível com o reforço de movimento de câmera. Desligue esse reforço.")
    for key in ("first_frame", "last_frame"):
        value = request.get(key)
        values[key] = None if value is None else _file(value, "image", key)
    for key, kind, limit in (("references", "image", 9),
                             ("video_references", "video", 3),
                             ("audio_references", "audio", 3)):
        values[key] = _files(request, key, kind, limit)
    reference_count = sum(len(values[key]) for key in
                          ("references", "video_references", "audio_references"))
    if reference_count > 12:
        raise RecipeError("Use até 12 referências no total (9 imagens, 3 vídeos e 3 áudios no máximo por tipo).")
    if values["audio_references"] and not (values["references"] or values["video_references"]):
        raise RecipeError("A referência de áudio precisa acompanhar uma imagem ou um vídeo de referência.")
    has_keyframes = bool(values["first_frame"] or values["last_frame"])
    if reference_count and has_keyframes:
        raise RecipeError("Imagens de início/fim e referências usam condicionamentos diferentes. Nesta versão, escolha um dos dois modos.")
    engine = values["model"]
    if engine == "auto":
        engine = "ref2va" if reference_count else "fl2va"
    if engine == "fl2va" and reference_count:
        raise RecipeError("FL2VA usa texto e imagens de início/fim. Para referências, escolha Automático ou REF2VA.")
    if engine in ("ref2va", "hybrid") and (not reference_count or has_keyframes):
        raise RecipeError("REF2VA e Híbrido precisam de referências; imagens de início/fim usam FL2VA.")
    if reference_count and values["director"]:
        raise RecipeError("O diretor de texto ainda não analisa referências. Desligue-o para manter o uso correto das mídias enviadas.")
    if values["last_frame"] and values["temporal"]:
        # ExactRecover selects the first frame in each hold, while the native
        # last-frame anchor sits at the final dilated frame. Legal-grid padding
        # can therefore discard that anchor. Do not silently weaken this input.
        raise RecipeError("O reparo temporal pode descartar a imagem final durante a recuperação dos quadros. Desligue o reparo temporal para preservar essa orientação; o refino de detalhes continua disponível.")
    if values["motion"] and values["scene"] == "weapon" and (
            values["people_realism"] or values["camera_motion"]):
        raise RecipeError("O perfil de ação com objetos de mão usa a LoRA isolada. Desligue realismo de pessoas e movimento de câmera neste perfil.")
    values["engine"] = engine
    return values


class _Graph:
    def __init__(self):
        self.nodes = {}

    def add(self, class_type, **inputs):
        node_id = str(len(self.nodes) + 1)
        self.nodes[node_id] = {"class_type": class_type, "inputs": inputs}
        return [node_id, 0]


def _output(link, slot):
    return [link[0], slot]


def compile_request(request: dict) -> dict:
    """Return an API graph, its actual settings and only its needed weights."""
    v = _validate(request)
    graph = _Graph()
    add = graph.add
    width, height = BASE_SIZE[v["aspect"]]
    frames = FRAMES[v["duration"]]
    seed = v["seed"]
    notes = ["A configuração foi verificada em código; a qualidade visual desta combinação ainda precisa de validação em GPU."]
    if not v["output_audio"]:
        notes.append("Os vídeos serão exportados sem faixa de áudio.")
    stages = ["generate"]
    required = []

    def model_file(key):
        folder, filename = MODELS[key]
        item = {"folder": folder, "filename": filename}
        if item not in required:
            required.append(item)
        return filename

    if v["engine"] == "hybrid":
        raw_model = add("MiniMaxH3HybridLoader", base_model=model_file("fl2va"),
                        overlay_model=model_file("ref2va"), overlay_preset="block_range_adaln",
                        block_range_start=25, block_range_end=49,
                        final_adaln_from_overlay=False, custom_overlays="", custom_base="",
                        weight_dtype="default")
        notes.append("O Híbrido é experimental; não há vantagem de qualidade confirmada sobre os modelos originais.")
    else:
        raw_model = add("UNETLoader", unet_name=model_file(v["engine"]), weight_dtype="default")
    clip = add("CLIPLoader", clip_name=model_file("encoder"), type="minimax", device="default")
    vae = add("VAELoader", vae_name=model_file("video_vae"))
    needs_audio_decode = v["output_audio"] or v["temporal"]
    needs_audio_vae = needs_audio_decode or v["engine"] != "fl2va"
    audio_vae = add("VAELoader", vae_name=model_file("audio_vae")) if needs_audio_vae else None
    prompt = v["prompt"]
    if v["framing"] != "auto":
        prompt += "\n\n" + FRAMING_PRESETS[v["framing"]]
    if v["camera"] != "auto":
        instruction = CAMERA_PRESETS[v["camera"]].format(
            amount=CAMERA_AMOUNTS[v["camera_amount"]], speed=CAMERA_SPEEDS[v["camera_speed"]])
        prompt += "\n\n" + instruction
        notes.append("A câmera é orientada pelo texto; o modelo interpreta o movimento, sem uma trajetória 3D definida.")
    if v["director"]:
        prompt = add("H3MAXDirectorText", prompt=prompt, enabled=True, seconds=frames / FPS,
                     aspect=v["aspect"], seed=seed)
        notes.append("O diretor requer um serviço de linguagem configurado e pode consumir esse serviço.")

    profile = PROFILES[v["scene"]] if v["motion"] else "base"
    if v["motion"]:
        model_file(v["scene"])
        if v["scene"] == "objects":
            notes.append("O ajuste de objetos é experimental; não comprova conservação de massa, colisões ou líquidos corretos.")
    for key in ("people_realism", "camera_motion"):
        if v[key]:
            model_file(key)
    use_preset = v["motion"] or v["people_realism"] or v["camera_motion"]

    def preset(second=False):
        if not use_preset:
            return raw_model, prompt
        strength = 0.25 / 0.9 if second and profile == "natural" else 1.0
        node = add("H3MAXMotionPreset", model=raw_model, prompt=prompt, profile=profile,
                   motion_multiplier=strength, people_realism=v["people_realism"],
                   people_strength=0.65, camera_motion=v["camera_motion"], camera_strength=0.8)
        return node, _output(node, 1)

    # Uploads are loaded once and shared between all generation stages.
    assets = {}
    for key in ("first_frame", "last_frame"):
        if v[key]:
            assets[key] = add("LoadImage", image=v[key])
    for index, file in enumerate(v["references"]):
        assets[f"ref_images.ref_image_{index}"] = add("LoadImage", image=file)
    for index, file in enumerate(v["video_references"]):
        media = add("H3MAXReferenceVideo", file=file)
        assets[f"ref_videos.ref_video_{index}"] = media
        assets[f"ref_video_audios.ref_video_audio_{index}"] = _output(media, 1)
    for index, file in enumerate(v["audio_references"]):
        assets[f"ref_audios.ref_audio_{index}"] = add("LoadAudio", audio=file)
    if v["video_references"]:
        notes.append("Referências de vídeo são convertidas para 24 fps e até aproximadamente 1 MP; a grade do H3 pode remover até 16 quadros finais, com áudio aparado junto.")
        notes.append(f"Cada vídeo de referência deve caber na geração de {frames / FPS:.2f} s; a verificação de mídia rejeita vídeos mais longos antes da geração.")

    def conditioning(text, length):
        inputs = dict(clip=clip, vae=vae, prompt=text, width=width, height=height,
                      length=length, **assets)
        if v["engine"] == "fl2va":
            return add("MiniMaxH3ImageToVideo", **inputs)
        return add("MiniMaxH3ReferenceToVideo", **inputs, audio_vae=audio_vae, ref_image_size="match")

    sampler = add("KSamplerSelect", sampler_name="res_multistep")

    def sample(model, cond, latent, schedule, stage_seed):
        noise = add("RandomNoise", noise_seed=stage_seed)
        guider = add("BasicGuider", model=model, conditioning=cond)
        return add("SamplerCustomAdvanced", noise=noise, guider=guider, sampler=sampler,
                   sigmas=schedule, latent_image=latent)

    first_model, first_prompt = preset()
    first_cond = conditioning(first_prompt, frames)
    schedule = add("BasicScheduler", model=first_model, scheduler="simple", steps=25, denoise=1.0)
    latent = sample(first_model, first_cond, _output(first_cond, 1), schedule, seed)
    # Decode the final audio from the original performance even when temporal
    # dilation/refinement is enabled. Dilation is internal, never user output.
    # The model still generates joint AV latents. Muting is a real export
    # choice; temporal repair continues to use the original audio internally.
    audio = add("VAEDecodeAudio", samples=latent, vae=audio_vae) if needs_audio_decode else None
    exported_audio = {"audio": audio} if v["output_audio"] else {}
    base_images = None
    outputs = ["final"]
    if v["temporal"] or v["refine"]:
        # Preserve the first generation for direct comparison. The temporal
        # pass shares this decode rather than decoding the same latent twice.
        base_images = add("VAEDecode", samples=latent, vae=vae)
        base_video = add("CreateVideo", images=base_images, **exported_audio, fps=FPS, bit_depth=8)
        add("SaveVideo", video=base_video, filename_prefix=f"H3_MAX/Studio/{seed}_base",
            **{"format": "auto", "format.codec": "auto"})
        outputs = ["base", "final"]
        comparison = "movimento, detalhes e áudio" if v["output_audio"] else "movimento e detalhes"
        notes.append(f"O original e o resultado final são salvos juntos para comparar {comparison} sem gerar a cena novamente.")
    cond = first_cond
    second_model, second_prompt = (None, None)
    if v["temporal"] or v["refine"]:
        second_model, second_prompt = preset(second=True)

    hold_map = None
    if v["temporal"]:
        stages.append("temporal")
        notes.append("O reparo temporal é experimental, acrescenta uma geração e pode aumentar bastante o consumo de memória e o tempo.")
        oracle = add("H3JerkOracle", samples=latent, length=frames, q=0.75, d_max=4,
                     ramp=True, preset="balanced (default)", bridge=8,
                     profile_mode="value |d3| (default)", abstain_below=0.0,
                     fps=FPS, s_per_step=0.0, est_steps=12, overhead_s=6.7)
        smear = add("H3TimeSmear", images=base_images, dilation=4, hold_map=oracle,
                    expand_to_end=True, fps=FPS, s_per_step=0.0, est_steps=12, overhead_s=6.7)
        hold_map = _output(smear, 1)
        video_init = add("VAEEncode", pixels=smear, vae=vae)
        audio_smear = add("H3AudioSmear", audio=audio, hold_map=hold_map, fps=FPS)
        audio_init = add("VAEEncodeAudio", audio=audio_smear, vae=audio_vae)
        init = add("H3V2VInit", samples=video_init, length=0, freeze_threshold=0.0,
                   freeze_grow=2, mask_feather=0, invert_mask=False, time_varying=False,
                   audio_latent=audio_init, audio_mode="follow the original performance (0.5)",
                   audio_strength=0.5)
        cond = conditioning(second_prompt, _output(smear, 2))
        schedule = add("H3InjectSchedule", model=second_model, scheduler="simple",
                       total_steps=25, inject=0.48, preset="custom")
        latent = sample(second_model, cond, init, schedule, (seed + 1) % (MAX_SEED + 1))

    output_width, output_height = width, height
    if v["refine"]:
        stages.append("refine")
        output_width, output_height = REFINE_SIZE[v["aspect"]]
        # Refine the dilated latent before exact recovery. No lossy extra VAE
        # encode and no mismatch between its temporal grid and conditioning.
        if not v["temporal"]:
            cond = conditioning(second_prompt, frames)
        schedule = add("BasicScheduler", model=second_model, scheduler="simple", steps=25, denoise=0.3)
        noise = add("RandomNoise", noise_seed=(seed + 2) % (MAX_SEED + 1))
        latent = add("MinimaxH3LatentUpscaler3DRefineHandoff", latent=latent,
                     model_name=model_file("refine"), mode="target dimensions", scale=2.0,
                     width=output_width, height=output_height, megapixels=1.5, align=32,
                     keep_proportion=False, lock_audio=True, cfg=1.0, device="cuda",
                     precision="fp16", offload_after_upscale=True, model=second_model,
                     positive=cond, noise=noise, sampler=sampler, sigmas=schedule)
        audio_note = "o áudio original é preservado" if v["output_audio"] else "a exportação permanece sem faixa de áudio"
        notes.append(f"Detalhes usa ampliação aprendida e mais 25 passos de geração; {audio_note}.")
    images = add("VAEDecode", samples=latent, vae=vae)
    if hold_map is not None:
        stages.append("recover")
        images = add("H3ExactRecover", images=images, hold_map=hold_map)
    video = add("CreateVideo", images=images, **exported_audio, fps=FPS, bit_depth=8)
    add("SaveVideo", video=video, filename_prefix=f"H3_MAX/Studio/{seed}_final",
        **{"format": "auto", "format.codec": "auto"})
    return {
        "prompt": graph.nodes,
        "summary": {
            "engine": v["engine"], "width": output_width, "height": output_height,
            "base_width": width, "base_height": height, "frames": frames,
            "fps": FPS, "seconds": frames / FPS, "requested_seconds": v["duration"],
            "seed": seed, "stages": stages, "notes": notes, "profile": profile,
            "camera": v["camera"], "camera_label": CAMERA_LABELS[v["camera"]],
            "camera_speed": v["camera_speed"], "camera_amount": v["camera_amount"],
            "framing": v["framing"], "output_audio": v["output_audio"],
            "outputs": outputs,
        },
        "required_models": required,
    }
