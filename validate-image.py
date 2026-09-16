"""CPU-only structural image validation; does not claim GPU inference works."""
import ast
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import urllib.request
import huggingface_hub
import torch

root = Path('/opt/comfyui-baked')
assert (root / 'main.py').is_file()
assert Path('/start.sh').is_file()
ast.parse(Path('/opt/h3-bootstrap.py').read_text())
spec = importlib.util.spec_from_file_location('bootstrap', '/opt/h3-bootstrap.py')
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)
assert len(bootstrap.MODELS) == (7 if bootstrap.PROFILE == 'both' else 5)
destinations = [(m[3], Path(m[2]).name) for m in bootstrap.MODELS]
assert len(destinations) == len(set(destinations)), 'Duplicate model downloads'
with tempfile.TemporaryDirectory() as directory:
    output = Path(directory)
    bootstrap.install_workflows(output)
    for profile in bootstrap.PROFILES:
        workflow_file = output / f'user/default/workflows/MiniMax H3 - Official {profile.upper()}.json'
        workflow = json.loads(workflow_file.read_text())
        serialized = json.dumps(workflow)
        for repo, revision, source, folder, size, digest in bootstrap.PROFILE_MODELS[profile]:
            assert Path(source).name in serialized, source
            assert size > 0 and len(digest) == 64
        print('PASS: downloaded official workflow and checked its five model names:', profile)
source_text = '\n'.join(p.read_text(errors='replace') for p in (root / 'comfy_extras').glob('nodes*.py'))
assert 'MiniMaxH3' in source_text, 'Native H3 nodes absent from base image'
print('PASS: official ComfyUI bundle, native H3 source, bootstrap syntax, deduplicated models.')
print('PyTorch:', torch.__version__, 'CUDA build:', torch.version.cuda)
print('GPU generation is not tested by this CPU-only check.')
