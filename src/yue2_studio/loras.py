"""Local acoustic adapter discovery and immutable queued identity."""
from pathlib import Path

from .settings import ROOT


def inspect_adapter(path):
    from safetensors import SafetensorError
    from yue2.lora import AcousticLoRA
    if not isinstance(path, str) or not path.strip():
        raise ValueError('Enter a local YuE2 LoRA file path.')
    try:
        adapter = AcousticLoRA.read(path)
    except SafetensorError as exc:
        raise ValueError('Invalid safetensors adapter: '+str(exc)) from exc
    return adapter.info(1.0)


def catalogue():
    from safetensors import safe_open, SafetensorError
    from yue2.lora import _targets
    folder = ROOT / 'models' / 'loras'
    items, rejected = [], []
    for path in sorted(folder.glob('*.safetensors')):
        try:
            # Inspect headers only; listing never loads all adapter tensors.
            with safe_open(path, framework='pt', device='cpu') as handle:
                metadata = handle.metadata() or {}
                if metadata.get('format') not in (None, 'comfyui-native-lora', 'yue2-lora-v1'):
                    raise ValueError('Unsupported adapter format')
                keys = set(handle.keys())
                downs = [k for k in keys if k.endswith('.lora_down.weight')]
                if not downs:
                    raise ValueError('No acoustic LoRA matrices')
                used = set()
                for key in downs:
                    name = key[:-len('.lora_down.weight')]
                    _targets(name)
                    up = name + '.lora_up.weight'
                    if up not in keys:
                        raise ValueError('Missing LoRA up matrix')
                    used.update((key, up))
                    if name + '.alpha' in keys:
                        used.add(name + '.alpha')
                if used != keys:
                    raise ValueError('Unsupported adapter tensors')
            items.append({'path':str(path.resolve()), 'name':path.stem,
                          'trigger_word':metadata.get('trigger_word','')})
        except (OSError, ValueError, RuntimeError, SafetensorError) as exc:
            rejected.append({'name':path.name, 'error':str(exc)})
    return {'folder':str(folder), 'loras':items, 'rejected':rejected}


def prepare(settings, request, expected=None):
    if expected is not None and not isinstance(expected, dict):
        raise ValueError('Invalid saved LoRA identity.')
    selection = settings['lora']
    if not selection['path'].strip():
        return None
    if settings['runtime']['backend'] == 'audio.cpp':
        raise ValueError('Style LoRAs require the Python engine. Select Torch or choose None for LoRA.')
    info = inspect_adapter(selection['path'])
    if expected and expected.get('sha256') != info['sha256']:
        raise ValueError('The LoRA file changed since this run was saved. Select it again for a new song.')
    selection['path'] = info['path']
    info['strength'] = selection['strength']
    trigger = info['trigger_word'].strip()
    if not isinstance(request.get('style',''), str):
        raise ValueError('Style must be text.')
    if selection['auto_trigger'] and trigger and trigger.casefold() not in request.get('style','').casefold():
        request['style'] = trigger + ', ' + request.get('style','')
    return info
