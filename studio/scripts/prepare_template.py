#!/usr/bin/env python3
"""Write a Runpod v2 template payload from a real published image digest. No API calls."""
from __future__ import annotations
import argparse
import json
from pathlib import Path, PurePosixPath
import re

from runtime_env import default_environment


def make_template(image, registry=None):
    if not re.fullmatch(r'[a-z0-9][a-z0-9._:/-]*@sha256:[0-9a-f]{64}', image):
        raise ValueError('Use the published linux/amd64 image reference with @sha256 and its 64-character digest.')
    payload = {
        'name': 'H3 Studio - candidato integrado 2026-09-23',
        'image': image, 'category': 'NVIDIA', 'disk': 60,
        'mounts': {'persistent': {'path': '/workspace', 'size': 300}},
        'allowedCudaVersions': ['13.0', '13.2'],
        'ports': ['8188/http'], 'public': False, 'serverless': False,
        'startJupyter': False, 'startSsh': False,
        'env': {'H3MAX_ROOT': '/workspace/h3max', 'H3MAX_MODEL_GROUPS': 'h3',
                'H3MAX_DOWNLOAD_MODELS': '1', 'H3MAX_COMFY_ARGS': '[]',
                **default_environment(PurePosixPath('/workspace/h3max')),
                # The user supplies this at Pod creation. Never copy the build environment.
                'HF_TOKEN': ''},
    }
    if registry:
        payload['registry'] = registry
    # Host-local persistence is the safe default; a network volume can replace it at Pod creation.
    return payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True)
    parser.add_argument('--registry', help='Existing Runpod registry credential ID for a private GHCR package')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    payload = make_template(args.image, args.registry)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + '\n', encoding='utf-8')
    print(f'Template payload written to {args.output}; no template or Pod was created.')


if __name__ == '__main__':
    main()
