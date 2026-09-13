"""CPU-only structural image validation; does not claim GPU inference works."""
import ast
import importlib.util
import json
from pathlib import Path
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
url = f'https://raw.githubusercontent.com/Comfy-Org/workflow_templates/{bootstrap.WORKFLOW_COMMIT}/templates/video_minimax_h3_i2v.json'
with urllib.request.urlopen(url, timeout=60) as response:
    workflow = json.load(response)
serialized = json.dumps(workflow)
assert len(bootstrap.MODELS) == 5
for repo, revision, source, folder, size, digest in bootstrap.MODELS:
    assert Path(source).name in serialized, source
    assert size > 0 and len(digest) == 64
source_text = '\n'.join(p.read_text(errors='replace') for p in (root / 'comfy_extras').glob('nodes*.py'))
assert 'MiniMaxH3' in source_text, 'Native H3 nodes absent from base image'
print('PASS: official ComfyUI bundle, native H3 source, bootstrap syntax, five exact workflow model names.')
print('PyTorch:', torch.__version__, 'CUDA build:', torch.version.cuda)
print('GPU generation is not tested by this CPU-only check.')
