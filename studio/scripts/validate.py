#!/usr/bin/env python3
"""Static graph and package checks. Does not imply GPU inference compatibility."""
from __future__ import annotations
import ast
import hashlib
import json
from pathlib import Path
import re

from build_workflows import graph_to_api

ROOT = Path(__file__).resolve().parents[1]
if not __debug__:
    raise RuntimeError("Do not disable assertions when running package validation")

def check_graph(path):
    g = json.loads(path.read_text(encoding="utf-8"))
    nodes = {n["id"]: n for n in g["nodes"]}
    links = {l[0]: l for l in g["links"]}
    assert len(nodes) == len(g["nodes"]), f"{path.name}: duplicate node ids"
    assert len(links) == len(g["links"]), f"{path.name}: duplicate link ids"
    seen_targets = set()
    for lid, src, so, dst, di, kind in links.values():
        assert src in nodes and dst in nodes, (path.name, lid, "missing node")
        assert type(so) is int and 0 <= so < len(nodes[src]["outputs"]), (path.name, lid, "invalid output slot")
        assert type(di) is int and 0 <= di < len(nodes[dst]["inputs"]), (path.name, lid, "invalid input slot")
        output = nodes[src]["outputs"][so]
        input_ = nodes[dst]["inputs"][di]
        assert input_["link"] == lid, (path.name, lid, "input backlink")
        assert lid in (output["links"] or []), (path.name, lid, "output backlink")
        assert kind == output["type"], (path.name, lid, "link type")
        assert input_["type"] == kind or "*" in (input_["type"], kind), (path.name, lid, kind, input_["type"])
        assert (dst, di) not in seen_targets, (path.name, lid, "multiple input producers")
        seen_targets.add((dst, di))
        assert nodes[src]["order"] < nodes[dst]["order"], (path.name, lid, "cycle/order")
    for node in nodes.values():
        for i, port in enumerate(node.get("inputs", [])):
            if port.get("link") is not None:
                link = links[port["link"]]
                assert (link[3], link[4]) == (node["id"], i)
        for i, port in enumerate(node.get("outputs", [])):
            for lid in port.get("links") or []:
                assert (links[lid][1], links[lid][2]) == (node["id"], i)
        assert "LoadVideo" not in node["type"], f"{path.name}: unexpected required external video"
        if node["type"] in ("MiniMaxH3ImageToVideo", "MiniMaxH3ReferenceToVideo"):
            _, width, height, frames, *_ = node["widgets_values"]
            assert width % 32 == height % 32 == 0
            assert (frames - 5) % 17 == 0
        if node["type"] == "MinimaxH3LatentUpscaler3DRefineHandoff":
            sigma_port = next(p for p in node["inputs"] if p["name"] == "sigmas")
            schedule = nodes[links[sigma_port["link"]][1]]
            assert schedule["type"] == "BasicScheduler"
            assert 0 < schedule["widgets_values"][2] < 1, "Refine must use partial denoise"
    assert g["extra"]["h3max"]["external_video_required"] is False
    return {"name": path.name, "nodes": len(nodes), "links": len(links),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

def check_api(path, workflow):
    actual = json.loads(path.read_text(encoding="utf-8"))
    expected = graph_to_api(json.loads(workflow.read_text(encoding="utf-8")))
    if actual != expected:
        raise ValueError(f"{path.name}: API prompt differs from its editable workflow; regenerate both")
    for node in actual.values():
        if node["class_type"] == "SaveVideo":
            if "format.codec" not in node["inputs"]:
                raise ValueError(f"{path.name}: pinned SaveVideo requires format.codec")
    return {"name": path.name, "nodes": len(actual),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

def main():
    workflows = sorted((ROOT / "workflows").glob("*.json"))
    assert len(workflows) == 8, "Expected eight assembled workflows"
    checks = [check_graph(p) for p in workflows]
    api_paths = sorted((ROOT / "api_prompts").glob("*.json"))
    assert {p.name for p in workflows} == {p.name for p in api_paths}, "Every workflow needs a matching API prompt"
    api_checks = [check_api(ROOT / "api_prompts" / p.name, p) for p in workflows]
    manifest = json.loads((ROOT / "models.lock.json").read_text(encoding="utf-8"))
    models = manifest["models"]
    destinations = [m["destination"] for m in models]
    assert len(set(destinations)) == len(destinations)
    allowed_names = {Path(p).name for p in destinations}
    for m in models:
        assert re.fullmatch(r"[0-9a-f]{64}", m["sha256_published"])
        assert re.fullmatch(r"[0-9a-f]{40}", m["revision"])
        assert m["size_bytes"] > 0
        p = Path(m["destination"])
        assert not p.is_absolute() and ".." not in p.parts
    for path in workflows:
        graph = json.loads(path.read_text(encoding="utf-8"))
        for node in graph["nodes"]:
            for value in node.get("widgets_values", []):
                if isinstance(value, str) and value.endswith(".safetensors"):
                    assert value in allowed_names, (path.name, "unmanifested model", value)
    for path in ROOT.rglob("*.py"):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    # Preset filenames are inside Python, not workflow widgets. Check those too.
    preset_tree = ast.parse((ROOT / "custom_nodes/ComfyUI-H3MAX/__init__.py").read_text(encoding="utf-8"))
    for node in ast.walk(preset_tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.endswith(".safetensors"):
            assert node.value in allowed_names, ("unmanifested preset model", node.value)
    lock = json.loads((ROOT / "sources.lock.json").read_text(encoding="utf-8"))
    for source in [lock["core"], lock["compiler"], *lock["custom_nodes"], lock["templates"]]:
        assert re.fullmatch(r"[0-9a-f]{40}", source["commit"])
    report = {"static_validation": "passed", "workflow_checks": checks,
              "api_prompt_checks": api_checks,
              "model_entries": len(models), "docker_build_executed": False,
              "gpu_render_executed": False, "seedance_comparison_executed": False,
              "limitations": ["Requires image build, actual /object_info check and GPU render.",
                              "Pinned source does not guarantee compatible runtime dependencies."]}
    (ROOT / "verification-local.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"static_validation": "passed", "workflows": len(checks),
                      "nodes": sum(x["nodes"] for x in checks),
                      "links": sum(x["links"] for x in checks),
                      "gpu_tested": False}))

if __name__ == "__main__":
    main()
