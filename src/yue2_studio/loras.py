"""Local acoustic adapter discovery and immutable queued identity."""
from pathlib import Path
import json
import re

from .settings import ROOT


def _canonical_target(name):
    # Keep diffusion_model. intact: _targets maps native branch names
    # (mlp -> nar_mlp) only when it sees the native prefix itself.
    # Community files sometimes omit the model. prefix on native targets.
    if name.startswith('layers.'):
        name = 'model.' + name
    return name


def _pair_convention(keys):
    """Return (down_suffix, up_suffix) for ComfyUI or PEFT LoRA naming."""
    down_suffix = next((s for s in ('.lora_down.weight', '.lora_A')
                        if any(k.endswith(s) for k in keys)), None)
    return (down_suffix, '.lora_up.weight' if down_suffix == '.lora_down.weight' else '.lora_B') if down_suffix else (None, None)


def training_style(metadata):
    style=metadata.get('training_style','')
    if isinstance(style,str) and style.strip() and len(style)<=12000:
        return style
    # Legacy Style adapters reference an immutable, versioned local setup.
    # Never rewrite adapter bytes (queued jobs rely on their hash).
    project_id=metadata.get('project_id','')
    if metadata.get('format')=='yue2-lora-v1' and isinstance(project_id,str) and re.fullmatch(r'[a-f0-9]{32}',project_id):
        try:
            project=json.loads((ROOT/'training/projects'/f'{project_id}.json').read_text(encoding='utf-8'))
            style=project.get('default_caption','')
            if project.get('id')==project_id and isinstance(style,str) and style.strip() and len(style)<=12000:
                return style
        except (OSError,ValueError,AttributeError):
            pass
    return ''


def inspect_adapter(path,folder=None):
    from safetensors import SafetensorError
    from yue2.artist_lora import read_adapter
    if not isinstance(path, str) or not path.strip():
        raise ValueError('Enter a local YuE2 LoRA file path.')
    if folder:
        from .loras import scan_folder
        return scan_folder(path,folder)
    try:
        adapter = read_adapter(path)
    except SafetensorError as exc:
        raise ValueError('Invalid safetensors adapter: '+str(exc)) from exc
    return {**adapter.info(1.0), 'training_style':training_style(adapter.metadata)}


def _finalize(path,info,folder_root):
    info['name']=path.stem
    info['relative']=path.relative_to(folder_root).as_posix()
    info['parent']=path.parent.relative_to(folder_root).as_posix() or '.'
    return info


def _clean_entry(entry):
    if not isinstance(entry,str):return ''
    return entry.strip().strip('"').strip("'").strip()


def _iter_adapter_files(folder,max_depth=6):
    folder=folder.resolve()
    stack=[(folder,0)]
    while stack:
        current,depth=stack.pop()
        try:
            entries=sorted(current.iterdir(),key=lambda p:p.name.casefold())
        except OSError:
            continue
        for path in entries:
            try:
                if path.is_dir():
                    if depth<max_depth:stack.append((path,depth+1))
                elif path.suffix.lower() in ('.safetensors','.sft','.pt','.pth','.ckpt'):
                    yield path
            except OSError:
                continue


def scan_folder(raw,folder):
    folder=_clean_entry(folder)
    if not folder or not Path(folder).is_dir():
        raise ValueError('The selected LoRA folder no longer exists. Re-add it in Studio settings.')
    raw=_clean_entry(raw)
    if not raw:
        raise ValueError('Select a folder from your saved list first.')
    target=Path(raw)
    if not target.is_dir():
        raise ValueError('That folder was removed or renamed. Refresh your LoRA folders and try again.')
    try:target=target.resolve()
    except OSError:pass
    folder_root=Path(folder).resolve()
    try:
        if not target.is_relative_to(folder_root):
            raise ValueError('Choose a subfolder of the saved LoRA folder.')
    except OSError:
        pass
    found={}
    errors=[]
    for path in _iter_adapter_files(target):
        try:
            info=inspect_adapter(str(path))
        except (OSError,ValueError,RuntimeError) as exc:
            errors.append({'name':str(path.relative_to(folder_root)),'error':str(exc)})
            continue
        except Exception as exc:  # malformed safetensors headers surface as arbitrary types
            errors.append({'name':str(path.relative_to(folder_root)),'error':str(exc)})
            continue
        found[str(path)]=_finalize(path,info,folder_root)
    return {'folder':str(folder_root),'base':str(target),'files':sorted(found.values(),key=lambda i:(i.get('parent',''),i.get('name',''))),
            'errors':errors,'folders':sorted({i['parent'] for i in found.values()})}


def scan_folders(folders):
    if isinstance(folders,str):folders=[folders]
    if not isinstance(folders,list) or any(not isinstance(item,str) for item in folders):
        raise ValueError('LoRA folders must be a list of paths.')
    results=[];errors=[]
    for raw in folders:
        path=_clean_entry(raw)
        if not path:continue
        try:
            folder_root=Path(path).resolve()
            if not folder_root.is_dir():raise OSError('missing')
        except OSError:
            errors.append({'folder':path,'error':'Folder not found.'});continue
        files=[];folder_errors=[]
        for adapter in _iter_adapter_files(folder_root):
            try:
                info=inspect_adapter(str(adapter))
            except (OSError,ValueError,RuntimeError) as exc:
                folder_errors.append({'name':str(adapter.relative_to(folder_root)),'error':str(exc)});continue
            except Exception as exc:
                folder_errors.append({'name':str(adapter.relative_to(folder_root)),'error':str(exc)});continue
            files.append(_finalize(adapter,info,folder_root))
        results.append({'path':str(folder_root),'files':sorted(files,key=lambda i:(i.get('parent',''),i.get('name',''))),
            'folders':sorted({i['parent'] for i in files}),'errors':folder_errors})
    return {'folders':results,'errors':errors}


def catalogue(custom_folders=None):
    from safetensors import safe_open, SafetensorError
    from yue2.lora import _targets
    folder = ROOT / 'models' / 'loras'
    items, rejected = [], []
    for path in sorted(folder.glob('*.safetensors')):
        try:
            # Inspect headers only; listing never loads all adapter tensors.
            with safe_open(path, framework='pt', device='cpu') as handle:
                metadata = handle.metadata() or {}
                if metadata.get('format') not in (None, 'comfyui-native-lora', 'yue2-lora-v1', 'pt'):
                    raise ValueError('Unsupported adapter format')
                keys = set(handle.keys())
                down_suffix, up_suffix = _pair_convention(keys)
                if not down_suffix:
                    raise ValueError('No acoustic LoRA matrices')
                used = set()
                for key in (k for k in keys if k.endswith(down_suffix)):
                    name = key[:-len(down_suffix)]
                    up = name + up_suffix
                    if up not in keys:
                        raise ValueError('Missing LoRA up matrix')
                    try:
                        _targets(_canonical_target(name))
                    except ValueError as exc:
                        if re.search(r'\.(mlp|self_attn)\.', _canonical_target(name)):
                            raise ValueError('Targets the AR composer branch, which the acoustic style engine cannot apply') from exc
                        raise
                    used.update((key, up))
                    if name + '.alpha' in keys:
                        used.add(name + '.alpha')
                if used != keys:
                    raise ValueError('Unsupported adapter tensors')
            items.append({'path':str(path.resolve()), 'name':path.stem,
                          'trigger_word':metadata.get('trigger_word',''),'training_style':training_style(metadata)})
        except (OSError, ValueError, RuntimeError, SafetensorError) as exc:
            rejected.append({'name':path.name, 'error':str(exc)})
    # Completed Artist runs remain in their original artifact folders alongside
    # their manifest. Do not copy them into the acoustic-only adapter folder.
    for job_path in sorted((ROOT/'runs/studio').glob('*/job.json')):
        try:
            job=json.loads(job_path.read_text(encoding='utf-8'))
            if job.get('kind')!='artist_training' or job.get('status')!='complete':continue
            path=job_path.parent/'result/final.safetensors'
            with safe_open(str(path),framework='pt') as handle:
                metadata=handle.metadata() or {}
                if metadata.get('format')!='yue2-artist-ar-v1':raise ValueError('Invalid Artist adapter format.')
            if not (path.parent/'manifest.json').is_file():raise ValueError('Artist companion manifest missing.')
            items.append({'path':str(path.resolve()),'name':job['title']+' · '+metadata.get('step','?')+' steps',
                          'kind':'artist','trigger_word':metadata.get('trigger_word',''),'training_style':training_style(metadata)})
        except (OSError,ValueError,KeyError,RuntimeError,SafetensorError) as exc:
            rejected.append({'name':job_path.parent.name,'error':str(exc)})
    # Recursively list the user's saved custom folders. Broken or missing
    # folders stay in the list (shown as unavailable) so the user can fix or remove them.
    for raw in (custom_folders or []):
        path=_clean_entry(raw)
        if not path:continue
        try:
            folder_root=Path(path).resolve()
            if not folder_root.is_dir():raise OSError('missing')
            for adapter in _iter_adapter_files(folder_root):
                try:
                    info=inspect_adapter(str(adapter))
                except (OSError,ValueError,RuntimeError,SafetensorError) as exc:
                    rejected.append({'name':str(adapter.relative_to(folder_root)),'error':str(exc)});continue
                items.append(_finalize(adapter,info,folder_root))
        except OSError:
            items.append({'path':path,'name':Path(path).name or path,'kind':'unavailable','missing':True})
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
    if info.get('kind')=='artist':
        runtime=settings['runtime']
        if runtime['backend'] not in ('torch','torch-eager') or runtime['quantization']!='none' or runtime['offload_ar']:
            raise ValueError('Artist LoRA requires Torch, quantization None, and AR offloading disabled.')
        if request.get('cot','full')!='off' or request.get('abc'):
            raise ValueError('Artist LoRA requires No score generation mode and no ABC score. Your settings were not changed.')
        if expected and any(expected.get(key)!=info.get(key) for key in ('companion_sha256','base_identity')):
            raise ValueError('Artist companion or base-model identity changed since queueing.')
    selection['path'] = info['path']
    info['strength'] = selection['strength']
    if info.get('kind')=='artist':info['companion_strength']=1. if selection['strength']!=0 else 0.
    trigger = info['trigger_word'].strip()
    if not isinstance(request.get('style',''), str):
        raise ValueError('Style must be text.')
    if selection['auto_trigger'] and trigger and trigger.casefold() not in request.get('style','').casefold():
        request['style'] = trigger + ', ' + request.get('style','')
    return info
