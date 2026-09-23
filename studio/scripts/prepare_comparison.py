#!/usr/bin/env python3
"""Prepare matched H3 base/preset prompts and blank scores; never submit GPU jobs."""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def make_prompt(template, case, profile, seed):
    prompt = copy.deepcopy(template)
    for node in prompt.values():
        kind, inputs = node['class_type'], node['inputs']
        if kind == 'H3MAXDirectorText':
            inputs.update(prompt=case['prompt'], enabled=False, seed=seed)
        elif kind == 'H3MAXMotionPreset':
            inputs.update(profile=profile, motion_multiplier=1.0,
                          people_realism=False, camera_motion=False)
        elif kind == 'RandomNoise':
            inputs['noise_seed'] = seed
        elif kind == 'SaveVideo':
            inputs['filename_prefix'] = f'H3_MAX/COMPARISON/{case["id"]}/{profile}_{seed}'
    return prompt


def prepare(destination, seeds=None):
    if destination.exists():
        raise FileExistsError(f'Refusing to overwrite comparison data: {destination}')
    cases = json.loads((ROOT / 'docs/benchmark-cases.json').read_text(encoding='utf-8'))
    source = ROOT / 'api_prompts/01_H3_MAX_TEXTO.json'
    template = json.loads(source.read_text(encoding='utf-8'))
    seeds = seeds or cases['protocol']['first_pass_seeds']
    if len(seeds) != len(set(seeds)) or any(s < 0 or s > 2**63 - 1 for s in seeds):
        raise ValueError('Seeds must be distinct integers between 0 and 2**63-1.')
    destination.mkdir(parents=True)
    manifest = {
        'status': 'prepared_not_submitted', 'gpu_jobs_submitted': 0,
        'template_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
        'models_lock_sha256': hashlib.sha256((ROOT / 'models.lock.json').read_bytes()).hexdigest(),
        'sources_lock_sha256': hashlib.sha256((ROOT / 'sources.lock.json').read_bytes()).hexdigest(),
        'protocol': cases['protocol'], 'runs': [], 'seedance_cases': [],
    }
    for case in cases['cases']:
        for seed in seeds:
            for profile in ('base', case['recommended_profile']):
                run_id = f'{case["id"]}__{profile}__{seed}'
                path = destination / (run_id + '.json')
                path.write_text(json.dumps(make_prompt(template, case, profile, seed), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
                manifest['runs'].append({
                    'id': run_id, 'case': case['id'], 'domain': case['domain'],
                    'prompt_file': path.name, 'profile': profile, 'seed': seed,
                    'status': 'not_run', 'output_file': None,
                    'render_seconds': None, 'peak_vram_gb': None,
                    'critical_failure': None, 'blind_label': None,
                    'physics_scores': {criterion: None for criterion in case['checks']},
                    'appearance_score': None, 'notes': '',
                })
        manifest['seedance_cases'].append({
            'case': case['id'], 'prompt': case['prompt'], 'requested_version': 'Seedance 2.5',
            'actual_version': None, 'actual_settings': None, 'status': 'not_run',
            'output_file': None, 'critical_failure': None,
            'physics_scores': {criterion: None for criterion in case['checks']},
            'appearance_score': None, 'notes': '',
        })
    (destination / 'comparison.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seeds', type=int, nargs='+')
    args = parser.parse_args()
    manifest = prepare(args.output, args.seeds)
    print(json.dumps({'h3_prompts_prepared': len(manifest['runs']),
                      'seedance_scenes': len(manifest['seedance_cases']),
                      'gpu_jobs_submitted': 0, 'output': str(args.output)}))


if __name__ == '__main__':
    main()
