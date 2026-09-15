"""Read-only readiness checks and explicitly queued, CPU-only model downloads."""
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from .settings import ROOT

# Revisions used for the original acoustic trainer validation. Never execute
# downloaded model code; the installed YuE2 classes load these weights locally.
MODELS = {
    'model': {'repo':'m-a-p/YuE2-3B', 'revision':'1a96eca688d6ae5d7f0feb88573fec89920fcd19'},
    'vae': {'repo':'m-a-p/YuE2-Vae', 'revision':'95535e72a97bc0f09b8ada125d26b4009428c0e8'},
}


def validate_model_folder(value, kind):
    if not isinstance(value,str) or not value.strip():
        raise ValueError(f'Choose a local {kind} folder, not a GGUF file.')
    path = Path(value).expanduser().resolve()
    try:
        config = json.loads((path/'config.json').read_text(encoding='utf-8'))
        expected = 'yue2' if kind=='model' else 'yue2_vae'
        if config.get('model_type') != expected:
            raise ValueError(f'{kind} config must have model_type={expected}.')
        index = path/'model.safetensors.index.json'
        if index.is_file():
            names = set(json.loads(index.read_text(encoding='utf-8'))['weight_map'].values())
        else:
            names = {'model.safetensors'}
        if not names:
            raise ValueError('Empty weight index.')
        for name in names:
            weight = (path/name).resolve()
            if not weight.is_relative_to(path) or not weight.is_file() or weight.stat().st_size<8:
                raise ValueError(f'Missing or incomplete {kind} weight file: {name}')
        manifest = path/'weights_manifest.json'
        if manifest.is_file():
            entries = json.loads(manifest.read_text(encoding='utf-8'))['files']
            for name in names:
                if name not in entries or (path/name).stat().st_size != entries[name]['bytes']:
                    raise ValueError(f'Incomplete {kind} weights: {name}')
        if kind=='model' and not (path/'qwen.tiktoken').is_file():
            raise ValueError('Missing qwen.tiktoken tokenizer.')
    except (OSError,KeyError,TypeError) as exc:
        raise ValueError(f'Training needs a complete local {kind} folder. Use Download training models or choose existing full weights. {exc}') from exc
    return str(path)


def prepared_models():
    try:
        data = json.loads((ROOT/'training/models.json').read_text(encoding='utf-8'))
        return {key:validate_model_folder(data[key],key) for key in MODELS}
    except (OSError,ValueError,KeyError,TypeError):
        return {}


def gpu_info():
    # Query driver metadata only: no Torch CUDA context or model allocation.
    try:
        result = subprocess.run(['nvidia-smi','--query-gpu=name,memory.total,compute_cap','--format=csv,noheader,nounits'],
            capture_output=True,text=True,timeout=4,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        name, memory, capability = result.stdout.splitlines()[0].rsplit(',',2)
        return {'name':name.strip(),'memory_mib':int(memory.strip()),'bf16':float(capability.strip())>=8.0}
    except (OSError,ValueError,IndexError,subprocess.TimeoutExpired):
        return None


def readiness(payload):
    if set(payload)-{'model','vae','project_id'}:
        raise ValueError('Unknown setup-check fields.')
    from .trainer import load_project, validate_sources
    issues, warnings, paths = [], [], {}
    for key in MODELS:
        try:
            paths[key] = validate_model_folder(payload.get(key,''),key)
        except (ValueError,OSError) as exc:
            issues.append(str(exc))
    for package in ('torch','transformers','numpy','soundfile','safetensors','huggingface-hub'):
        try:
            importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            issues.append(f'Missing {package}. Repair the base YuE2 environment with its normal installer.')
    gpu = gpu_info()
    if not gpu or not gpu['bf16']:
        issues.append('Training requires a BF16-capable NVIDIA GPU visible to nvidia-smi (CUDA device 0).')
    elif gpu['memory_mib']<24*1024:
        warnings.append('Less than 24 GiB VRAM detected. Training memory is experimental; a short smoke test may still run out of memory.')
    try:
        import torch
        if torch.version.cuda is None:
            issues.append('This environment has CPU-only PyTorch. Install the CUDA build required by YuE2.')
    except ImportError:
        issues.append('PyTorch could not be imported. Repair the base YuE2 environment.')
    ffmpeg = shutil.which('ffmpeg')
    if payload.get('project_id'):
        project = load_project(payload['project_id'])
        selected = validate_sources(project)
        if not ffmpeg and any(row['sample_rate']!=48000 or row['channels'] not in (1,2) for row in selected):
            issues.append('Selected audio needs FFmpeg. Install it on PATH, or supply 48 kHz mono/stereo WAV or FLAC and rescan.')
    elif not ffmpeg:
        warnings.append('FFmpeg not found: use 48 kHz mono/stereo WAV or FLAC, or install FFmpeg for conversion.')
    warnings.append('File checks do not prove enough free VRAM or musical quality. Training rechecks CUDA/BF16 in its isolated worker. Other applications are not managed by Studio.')
    return {'ready':not issues,'issues':issues,'warnings':warnings,'paths':paths,
            'gpu':gpu,'ffmpeg':bool(ffmpeg),'prepared':prepared_models()}


def download_models(directory):
    from yue2.storage import resolve_model, model_identity
    from .jobs import write_json
    paths = {}
    for key, info in MODELS.items():
        print(f'[YuE2] Starting Download {key}: {info["repo"]} at {info["revision"]}',flush=True)
        path = resolve_model(info['repo'],revision=info['revision'],token=False,cache_dir=str(ROOT/'models/style-trainer-cache'))
        validate_model_folder(str(path),key)
        model_identity(path,True)  # Verify released weight hashes before publication.
        paths[key] = str(path)
        print(f'[YuE2] Completed Download {key}: verified local weights',flush=True)
    record = {**paths,'sources':MODELS}
    (ROOT/'training').mkdir(parents=True,exist_ok=True)
    write_json(ROOT/'training/models.json',record)
    result = directory/'result';result.mkdir(exist_ok=True)
    write_json(result/'training_models.json',record)
    print('Studio: models downloaded. Choose Use downloaded model paths, then Check setup. No training was started.',flush=True)


if __name__=='__main__':
    download_models(Path(sys.argv[1]).resolve().parent)
