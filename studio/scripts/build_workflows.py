#!/usr/bin/env python3
"""Generate flat, editable ComfyUI workflows from the pinned upstream examples."""
from __future__ import annotations
import copy
import json
from pathlib import Path
import uuid

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "source_workflows"
BASE = json.loads((SOURCE / "official_r2v.json").read_text(encoding="utf-8"))
TEMPLATES = {n["type"]: n for n in BASE["nodes"]}
TEMPLATES["MiniMaxH3ImageToVideo"] = json.loads((SOURCE / "official_i2v_node.json").read_text(encoding="utf-8"))
FL = "minimax_h3_fl2va_pruned_int8_convrot.safetensors"
REF = "minimax_h3_ref2va_pruned_int8_convrot.safetensors"
TEXT = "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"
VIDEO = "minimax_h3_video_vae_int8_convrot.safetensors"
AUDIO = "minimax_h3_audio_vae_fp32.safetensors"
UPSCALE = "minimax_h3_latent_upscaler_3d_conv_v1_fp16.safetensors"
PROMPT = (
    "Single continuous documentary shot, full body. An adult athlete in a plain gray "
    "T-shirt and dark pants stands on a dry concrete courtyard in soft daylight. "
    "The athlete takes three quick running steps, decelerates, turns 90 degrees, "
    "then settles into a balanced stance. The planted foot stays fixed during the turn. "
    "The pelvis and torso carry momentum; knees bend to absorb the stop. "
    "Natural anatomy, skin texture, fabric movement and subtle breathing. "
    "Camera stays at chest height, the ground remains visible, no cuts. "
    "Audio: footsteps on concrete and quiet outdoor ambience, no dialogue or music."
)

WIDGET_NAMES = {
    "H3MAXDirectorText": ["prompt", "enabled", "seconds", "aspect", "seed"],
    "H3MAXMotionPreset": ["profile", "motion_multiplier", "people_realism", "people_strength", "camera_motion", "camera_strength"],
    "UNETLoader": ["unet_name", "weight_dtype"],
    "MiniMaxH3HybridLoader": ["base_model", "overlay_model", "overlay_preset", "block_range_start", "block_range_end", "final_adaln_from_overlay", "custom_overlays", "custom_base", "weight_dtype"],
    "CLIPLoader": ["clip_name", "type", "device"],
    "VAELoader": ["vae_name"], "LoadImage": ["image", None],
    "MiniMaxH3ImageToVideo": ["prompt", "width", "height", "length"],
    "MiniMaxH3ReferenceToVideo": ["prompt", "width", "height", "length", "ref_image_size"],
    "RandomNoise": ["noise_seed", None],
    "BasicScheduler": ["scheduler", "steps", "denoise"],
    "KSamplerSelect": ["sampler_name"], "BasicGuider": [], "SamplerCustomAdvanced": [],
    "VAEDecode": [], "VAEDecodeAudio": [], "VAEEncode": [], "VAEEncodeAudio": [],
    "CreateVideo": ["fps", "bit_depth"], "SaveVideo": ["filename_prefix", "format", "format.codec"],
    "MinimaxH3LatentUpscaler3DRefineHandoff": ["model_name", "mode", "scale", "width", "height", "megapixels", "align", "keep_proportion", "lock_audio", "cfg", "device", "precision", "offload_after_upscale"],
    "H3JerkOracle": ["length", "q", "d_max", "ramp", "preset", "bridge", "profile_mode", "abstain_below", "fps", "s_per_step", "est_steps", "overhead_s"],
    "H3TimeSmear": ["dilation", "hold_map", "expand_to_end", "fps", "s_per_step", "est_steps", "overhead_s"],
    "H3InjectSchedule": ["scheduler", "total_steps", "inject", "preset"],
    "H3JerkHeatmap": ["alpha", "strip_height", "show_drift"],
    "H3AudioSmear": ["hold_map", "fps"],
    "H3V2VInit": ["length", "freeze_threshold", "freeze_grow", "mask_feather", "invert_mask", "time_varying", "audio_mode", "audio_strength"],
    "H3ExactRecover": ["hold_map"],
}

def graph_to_api(graph):
    """Serialize the pinned node widgets and explicit links; never infer widget names."""
    links = {link[0]: link for link in graph["links"]}
    api = {}
    for node in graph["nodes"]:
        names = WIDGET_NAMES[node["type"]]
        values = node.get("widgets_values", [])
        if len(names) != len(values):
            raise ValueError(f"Widget count mismatch for {node['type']}: {names!r} / {values!r}")
        inputs = {name: value for name, value in zip(names, values) if name is not None}
        for port in node.get("inputs", []):
            if port.get("link") is not None:
                link = links[port["link"]]
                inputs[port["name"]] = [str(link[1]), link[2]]
        api[str(node["id"])] = {"class_type": node["type"], "inputs": inputs,
                                 "_meta": {"title": node["title"]}}
    return api

def inp(name, kind, widget=False):
    result = {"name": name, "type": kind, "link": None}
    if widget:
        result["widget"] = {"name": name}
    return result

def out(name, kind):
    return {"name": name, "type": kind, "links": None}

class Graph:
    def __init__(self, name, original=None):
        self.name = name
        self.data = copy.deepcopy(original) if original else {
            "nodes": [], "links": [], "groups": [], "config": {}, "extra": {}, "version": 0.4,
        }
        self.data.update(id=str(uuid.uuid5(uuid.NAMESPACE_URL, "h3-max/" + name)), revision=0)
        self.data["extra"] = {"ds": {"scale": 0.6, "offset": [60, 60]},
                              "h3max": {"external_video_required": False, "gpu_tested": False,
                                        "date": "2026-09-23"}}

    def add(self, kind, widgets=None, *, inputs=None, outputs=None, title=None, pos=(0, 0), size=(360, 180)):
        node = copy.deepcopy(TEMPLATES.get(kind, {}))
        node.update(id=max((n["id"] for n in self.data["nodes"]), default=0) + 1,
                    type=kind, pos=list(pos), size=list(size), flags={}, order=0, mode=0)
        node["title"] = title or kind
        node["properties"] = {"Node name for S&R": kind}
        node["inputs"] = copy.deepcopy(inputs if inputs is not None else node.get("inputs", []))
        node["outputs"] = copy.deepcopy(outputs if outputs is not None else node.get("outputs", []))
        for port in node["inputs"]:
            port["link"] = None
        for port in node["outputs"]:
            port["links"] = None
        node.pop("widgets_values_named", None)
        node["widgets_values"] = widgets if widgets is not None else node.get("widgets_values", [])
        self.data["nodes"].append(node)
        return node

    def link(self, source, slot, target, name):
        idx = next(i for i, p in enumerate(target["inputs"]) if p["name"] == name)
        if target["inputs"][idx]["link"] is not None:
            self.unlink(target["inputs"][idx]["link"])
        link_id = max((v[0] for v in self.data["links"]), default=0) + 1
        self.data["links"].append([link_id, source["id"], slot, target["id"], idx, source["outputs"][slot]["type"]])
        source["outputs"][slot]["links"] = (source["outputs"][slot]["links"] or []) + [link_id]
        target["inputs"][idx]["link"] = link_id

    def unlink(self, link_id):
        self.data["links"] = [l for l in self.data["links"] if l[0] != link_id]
        for node in self.data["nodes"]:
            for port in node.get("inputs", []):
                if port.get("link") == link_id:
                    port["link"] = None
            for port in node.get("outputs", []):
                port["links"] = [l for l in (port.get("links") or []) if l != link_id] or None

    def remove(self, ids):
        for link in list(self.data["links"]):
            if link[1] in ids or link[3] in ids:
                self.unlink(link[0])
        self.data["nodes"] = [n for n in self.data["nodes"] if n["id"] not in ids]

    def save(self):
        # Topological order, independent of the visual arrangement.
        done = set()
        while len(done) < len(self.data["nodes"]):
            ready = [n for n in self.data["nodes"] if n["id"] not in done and
                     all(l[1] in done for l in self.data["links"] if l[3] == n["id"])]
            if not ready:
                raise ValueError("Cycle in workflow")
            for n in ready:
                n["order"] = len(done)
                done.add(n["id"])
        self.data["last_node_id"] = max(n["id"] for n in self.data["nodes"])
        self.data["last_link_id"] = max((l[0] for l in self.data["links"]), default=0)
        dest = ROOT / "workflows" / (self.name + ".json")
        dest.parent.mkdir(exist_ok=True)
        dest.write_text(json.dumps(self.data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def save_api(self):
        api = graph_to_api(self.data)
        dest = ROOT / "api_prompts" / (self.name + ".json")
        dest.parent.mkdir(exist_ok=True)
        dest.write_text(json.dumps(api, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def director(g, pos=(0, 0)):
    return g.add("H3MAXDirectorText", [PROMPT, False, 124/24, "16:9", 123456],
                 inputs=[], outputs=[out("prompt", "STRING")],
                 title="1 — Descreva a cena; diretor de texto opcional", pos=pos, size=(470, 420))

def preset(g, pos=(520, 0), second_pass=False):
    return g.add("H3MAXMotionPreset", ["natural", 0.25 / 0.9 if second_pass else 1.0, False, 0.65, False, 0.8],
                  inputs=[inp("model", "MODEL"), inp("prompt", "STRING")],
                  outputs=[out("model", "MODEL"), out("prompt", "STRING")],
                  title="Passe 2 — Motion Repair 0.25; mantenha o perfil do passe 1" if second_pass else "2 — Movimento; realismo e câmera opcionais", pos=pos, size=(380, 260))

def condition(g, references=False, pos=(520, 340)):
    kind = "MiniMaxH3ReferenceToVideo" if references else "MiniMaxH3ImageToVideo"
    inputs = [copy.deepcopy(i) for i in TEMPLATES[kind]["inputs"]
              if "widget" not in i or i["name"] == "prompt"]
    return g.add(kind, ["", 1280, 736, 124] + (["match"] if references else []),
                 inputs=inputs, pos=pos, size=(400, 370))

def basic(name, mode, refine=False):
    g = Graph(name)
    refs = mode in ("refs", "hybrid")
    prompt = director(g)
    if mode == "hybrid":
        model = g.add("MiniMaxH3HybridLoader", [FL, REF, "block_range_adaln", 25, 49, False, "", "", "default"],
                      inputs=[], outputs=[out("model", "MODEL")], title="Hybrid FL/REF — variante experimental", pos=(0, 480), size=(470, 300))
    else:
        model = g.add("UNETLoader", [REF if refs else FL, "default"], pos=(0, 480), size=(470, 120))
    clip = g.add("CLIPLoader", [TEXT, "minimax", "default"], pos=(0, 830), size=(470, 140))
    video = g.add("VAELoader", [VIDEO], pos=(0, 1020), size=(470, 90))
    audio = g.add("VAELoader", [AUDIO], pos=(0, 1160), size=(470, 90))
    profile = preset(g)
    g.link(model, 0, profile, "model")
    g.link(prompt, 0, profile, "prompt")
    cond = condition(g, refs)
    for src, key in [(clip, "clip"), (video, "vae"), (profile, "prompt")]:
        g.link(src, 1 if src is profile else 0, cond, key)
    if refs:
        g.link(audio, 0, cond, "audio_vae")
    if mode != "text":
        image = g.add("LoadImage", ["selecione_sua_imagem.png", "image"], pos=(0, 1330), size=(470, 350), title="Carregue a imagem / referência 1")
        g.link(image, 0, cond, "ref_images.ref_image_0" if refs else "first_frame")
    if refs:
        image2 = g.add("LoadImage", ["selecione_referencia_2.png", "image"], pos=(0, 1730), size=(470, 350), title="Carregue a referência 2; desconecte para usar só uma")
        g.link(image2, 0, cond, "ref_images.ref_image_1")
    noise = g.add("RandomNoise", [123456, "fixed"], pos=(520, 770))
    schedule = g.add("BasicScheduler", ["simple", 25, 1.0], inputs=[inp("model", "MODEL")], pos=(960, 0))
    sampler = g.add("KSamplerSelect", ["res_multistep"], pos=(960, 220))
    guider = g.add("BasicGuider", [], pos=(960, 430))
    sample = g.add("SamplerCustomAdvanced", [], pos=(960, 650), size=(340, 340))
    g.link(profile, 0, schedule, "model")
    g.link(profile, 0, guider, "model")
    g.link(cond, 0, guider, "conditioning")
    for src, slot, key in [(noise, 0, "noise"), (guider, 0, "guider"), (sampler, 0, "sampler"),
                            (schedule, 0, "sigmas"), (cond, 1, "latent_image")]:
        g.link(src, slot, sample, key)

    def output(latent, prefix, x, y):
        dv = g.add("VAEDecode", [], pos=(x, y))
        da = g.add("VAEDecodeAudio", [], pos=(x, y + 200))
        cv = g.add("CreateVideo", [24, 8], pos=(x, y + 400))
        sv = g.add("SaveVideo", ["H3_MAX/" + prefix, "auto", "auto"], pos=(x + 420, y), size=(520, 480))
        g.link(latent, 0, dv, "samples")
        g.link(video, 0, dv, "vae")
        g.link(latent, 0, da, "samples")
        g.link(audio, 0, da, "vae")
        g.link(dv, 0, cv, "images")
        g.link(da, 0, cv, "audio")
        g.link(cv, 0, sv, "video")
    output(sample, name + "_base", 1400, 0)
    if refine:
        refine_profile = preset(g, (520, 1110), second_pass=True)
        g.link(model, 0, refine_profile, "model")
        g.link(prompt, 0, refine_profile, "prompt")
        sch2 = g.add("BasicScheduler", ["simple", 25, 0.3], inputs=[inp("model", "MODEL")],
                      pos=(960, 1110), title="Refine parcial — denoise 0.30")
        g.link(refine_profile, 0, sch2, "model")
        up = g.add("MinimaxH3LatentUpscaler3DRefineHandoff",
                   [UPSCALE, "megapixels", 2.0, 1280, 736, 1.5, 32, True, True, 1.0, "cuda", "fp16", True],
                   inputs=[inp("latent", "LATENT"), inp("noise", "NOISE"), inp("sampler", "SAMPLER"),
                           inp("sigmas", "SIGMAS"), inp("audio_latent", "LATENT"),
                           inp("refine_state", "H3_CONTINUUM_REFINE_STATE"), inp("model", "MODEL"),
                           inp("positive", "CONDITIONING"), inp("negative", "CONDITIONING")],
                   outputs=[out("LATENT", "LATENT")], pos=(1400, 850), size=(400, 640),
                   title="3 — Upscale + sampling H3 parcial; preserva áudio")
        for src, slot, key in [(sample, 0, "latent"), (noise, 0, "noise"), (sampler, 0, "sampler"),
                              (sch2, 0, "sigmas"), (refine_profile, 0, "model"), (cond, 0, "positive")]:
            g.link(src, slot, up, key)
        output(up, name + "_refined", 1850, 850)
    g.save()
    g.save_api()

def derope(name, image=False):
    original = json.loads((SOURCE / "mainodes_motion_pipeline.json").read_text(encoding="utf-8"))
    g = Graph(name, original)
    n = {v["id"]: v for v in g.data["nodes"]}
    # Explicit fixed canvas/duration; retain MAINodes' own temporal construction.
    g.remove({115, 132, 133, 219})
    n[127]["widgets_values"] = [FL, "default"]
    n[128]["widgets_values"] = [TEXT, "minimax", "default"]
    n[119]["widgets_values"] = [VIDEO]
    n[120]["widgets_values"] = [AUDIO]
    for key in (131, 206):
        n[key]["widgets_values"] = ["", 1280, 736, 124]
        n[key]["inputs"].append(inp("prompt", "STRING", True))
    n[129]["widgets_values"] = [123456, "fixed"]
    n[205]["widgets_values"] = [123457, "fixed"]
    prompt = director(g, (60, 1160))
    motion = preset(g, (520, 1160))
    motion2 = preset(g, (960, 1160), second_pass=True)
    g.link(n[127], 0, motion, "model")
    g.link(prompt, 0, motion, "prompt")
    g.link(n[127], 0, motion2, "model")
    g.link(prompt, 0, motion2, "prompt")
    n[204]["widgets_values"] = ["simple", 25, 0.48, "custom"]
    # These widgets only estimate cost. Match H3InjectSchedule's actual
    # truncated pass (round(25 * 0.48) = 12), not the upstream 0.70 recipe.
    regen_steps = max(1, round(n[204]["widgets_values"][1] * n[204]["widgets_values"][2]))
    for node_id in (200, 201):
        index = WIDGET_NAMES[n[node_id]["type"]].index("est_steps")
        n[node_id]["widgets_values"][index] = regen_steps
    for node_id in (124, 126):
        g.link(motion, 0, n[node_id], "model")
    for node_id in (204, 207):
        g.link(motion2, 0, n[node_id], "model")
    g.link(motion, 1, n[131], "prompt")
    g.link(motion2, 1, n[206], "prompt")
    # Use pass-1 audio in the final recovered clip. Keep upstream audio seeding
    # for pass 2 but do not substitute its experimental recovered audio.
    g.link(n[121], 0, n[214], "audio")
    n[214]["title"] = "Vídeo recuperado + áudio original do passe 1"
    for node in g.data["nodes"]:
        node.pop("widgets_values_named", None)
        if node["type"] == "SaveVideo":
            suffix = {92: "base", 218: "oracle", 212: "dilatado", 215: "final"}[node["id"]]
            node["widgets_values"][0] = "H3_MAX/" + name + "_" + suffix
    if image:
        frame = g.add("LoadImage", ["selecione_sua_imagem.png", "image"], pos=(60, 1660),
                      title="Imagem inicial — não precisa de vídeo", size=(400, 350))
        for node_id in (131, 206):
            g.link(frame, 0, n[node_id], "first_frame")
    g.data["extra"]["h3max"]["upstream"] = "matlowai/ComfyUI-MAINodes/examples/motion_pipeline.json"
    g.data["extra"]["h3max"]["note"] = "De-rope on self-generated output; final audio retained from pass 1. Audio seeding branch remains experimental upstream code."
    g.save()
    g.save_api()

def main():
    basic("01_H3_MAX_TEXTO", "text")
    basic("02_H3_MAX_IMAGEM", "image")
    basic("03_H3_MAX_REFERENCIAS", "refs")
    basic("04_H3_MAX_HYBRID_REFERENCIAS", "hybrid")
    basic("05_H3_MAX_TEXTO_REFINE", "text", True)
    basic("06_H3_MAX_IMAGEM_REFINE", "image", True)
    derope("07_H3_MAX_TEXTO_DEROPE")
    derope("08_H3_MAX_IMAGEM_DEROPE", True)

if __name__ == "__main__":
    main()
