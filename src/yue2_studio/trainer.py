"""CPU-only dataset inspection and versioned training-project preparation."""
import json
import math
from pathlib import Path
import re
import uuid
from datetime import datetime, timezone

from .settings import ROOT

AUDIO_EXTENSIONS = {'.wav', '.flac', '.mp3', '.ogg', '.m4a', '.aac', '.aiff', '.aif', '.opus'}


def _text(value, name, limit=20000):
    if not isinstance(value, str) or len(value) > limit or '\0' in value:
        raise ValueError(f'Invalid {name}.')
    return value.strip()


def scan(payload):
    import soundfile as sf
    folder = Path(_text(payload.get('folder',''), 'dataset folder',4096)).expanduser().resolve()
    if not payload.get('folder') or not folder.is_dir():
        raise ValueError('Choose an existing dataset folder on this PC.')
    clip = payload.get('clip_seconds',10)
    if type(clip) not in (int,float) or not math.isfinite(clip) or not 2 <= clip <= 30 or clip != int(clip):
        raise ValueError('Clip length must be a whole number between 2 and 30 seconds.')
    rows = []
    # Deliberately one folder: avoids silently including unrelated subfolders.
    for path in sorted(folder.iterdir()):
        if path.suffix.lower() not in AUDIO_EXTENSIONS or not path.is_file():
            continue
        if len(rows) >= 1000:
            raise ValueError('This folder has over 1,000 songs. Use a smaller dataset folder.')
        stat = path.stat()
        row = dict(name=path.name, bytes=stat.st_size, mtime_ns=str(stat.st_mtime_ns),
                   seconds=0, sample_rate=None, channels=None, clips=0,
                   warnings=[], error='', enabled=True)
        try:
            info = sf.info(path)
            row.update(seconds=info.duration, sample_rate=info.samplerate, channels=info.channels,
                       clips=int(info.duration//clip))
            if info.duration < clip:
                row['warnings'].append('Shorter than one training clip.')
                row['enabled'] = False
            if info.channels == 1:
                row['warnings'].append('Mono recording; stereo conversion will be needed.')
            elif info.channels != 2:
                row['warnings'].append('More than two channels; channel conversion will be needed.')
            if info.samplerate != 48000:
                row['warnings'].append('Will need resampling to 48 kHz.')
        except (RuntimeError, OSError) as exc:
            row.update(error='Cannot inspect audio: '+str(exc), enabled=False)
        rows.append(row)
    metadata = {}
    metadata_path = folder/'collection_metadata.json'
    if metadata_path.is_file() and metadata_path.stat().st_size <= 100000:
        try:
            value = json.loads(metadata_path.read_text(encoding='utf-8-sig'))
            if isinstance(value,dict):
                metadata = {key:value[key] for key in ('singer_name','singer_trigger','style_trigger','style_prompt')
                            if isinstance(value.get(key),str)}
                if not metadata.get('style_prompt') and isinstance(value.get('global_style_prompt'),str):
                    metadata['style_prompt'] = value['global_style_prompt']
        except (ValueError, OSError):
            pass
    return dict(folder=str(folder), clip_seconds=clip, tracks=rows, metadata=metadata,
                note='Header checks only: silence, clipping, and musical quality have not been measured. Subfolders are not scanned.')


def project_root():
    return ROOT/'training'/'projects'


def save_project(payload):
    name = _text(payload.get('name',''), 'project name',120)
    trigger = _text(payload.get('trigger',''), 'trigger phrase',200)
    caption = _text(payload.get('default_caption',''), 'default style caption')
    if not name or not trigger:
        raise ValueError('Give the project a name and a trigger phrase.')
    if not caption:
        raise ValueError('Add a shared style caption for this dataset.')
    goal = payload.get('goal','production')
    if goal not in ('production','singer_style'):
        raise ValueError('Unsupported training goal.')
    inspected = scan(payload)
    supplied = payload.get('tracks')
    if not isinstance(supplied,list):
        raise ValueError('Scan the dataset before saving.')
    choices = {}
    for item in supplied:
        if not isinstance(item,dict) or not isinstance(item.get('name'),str) or item['name'] in choices:
            raise ValueError('Invalid or duplicate song selection.')
        choices[item['name']] = item
    if set(choices) != {row['name'] for row in inspected['tracks']}:
        raise ValueError('Dataset contents changed. Scan the folder again.')
    selected = 0
    for row in inspected['tracks']:
        choice = choices[row['name']]
        if choice.get('bytes') != row['bytes'] or choice.get('mtime_ns') != row['mtime_ns']:
            raise ValueError('A song changed since scanning. Scan the folder again.')
        if type(choice.get('enabled')) is not bool:
            raise ValueError('Invalid song selection.')
        row['enabled'] = choice['enabled']
        if row['enabled']:
            if row['error'] or not row['clips']:
                raise ValueError('Exclude unreadable or too-short songs before saving.')
            selected += 1
    if not selected:
        raise ValueError('Select at least one usable song.')
    project = dict(schema=2,id=uuid.uuid4().hex,status='prepared',created=datetime.now(timezone.utc).isoformat(),
                   name=name,trigger=trigger,goal=goal,default_caption=caption,**inspected)
    root = project_root()
    root.mkdir(parents=True,exist_ok=True)
    # Each save is an independent version; never overwrite an earlier project.
    with (root/(project['id']+'.json')).open('x',encoding='utf-8') as handle:
        json.dump(project,handle,ensure_ascii=False,indent=2)
    return project


def load_project(project_id):
    if not re.fullmatch(r'[a-f0-9]{32}', project_id):
        raise ValueError('Invalid training project ID.')
    data = json.loads((project_root()/(project_id+'.json')).read_text(encoding='utf-8'))
    # Old saved versions remain on disk, but no longer expose per-song text.
    data.pop('text_kind',None)
    for row in data.get('tracks',[]):
        row.pop('source_text',None)
        row.pop('caption',None)
    return data


def projects():
    items = []
    for path in project_root().glob('*.json'):
        try:
            data = load_project(path.stem)
            items.append({key:data[key] for key in ('id','name','created','status')})
        except (OSError,ValueError,KeyError):
            continue
    return sorted(items,key=lambda item:item['created'],reverse=True)


def training_spec(payload):
    """Freeze a saved project and validate controls without loading the GPU."""
    if set(payload)-{'project_id','steps','learning_rate','rank','checkpoint_every','model','vae'}:
        raise ValueError('Unknown training controls.')
    project = load_project(str(payload.get('project_id','')))
    if not project.get('default_caption','').strip():
        raise ValueError('Save a project with a shared style before training.')
    validate_sources(project)
    controls = {}
    for name, default, low, high in [('steps',20,1,10000),('rank',8,2,64),('checkpoint_every',20,1,1000)]:
        value = payload.get(name,default)
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f'{name} must be an integer between {low} and {high}.')
        controls[name] = value
    lr = payload.get('learning_rate',0.0001)
    if type(lr) not in (int,float) or not math.isfinite(lr) or not 0.000001 <= lr <= 0.001:
        raise ValueError('Learning rate must be between 0.000001 and 0.001.')
    controls['learning_rate'] = lr
    paths = {}
    for key, default in [('model','YuE2-3B'),('vae','YuE2-Vae')]:
        from .trainer_setup import validate_model_folder
        paths[key] = validate_model_folder(_text(payload.get(key,str(ROOT/'models'/default)),key,4096),key)
    return dict(title=project['name']+' · LoRA training',stage='train',mode='trainer',
                project=project,controls=controls,**paths)


def validate_sources(project):
    folder = Path(project['folder']).resolve()
    selected = [row for row in project['tracks'] if row['enabled']]
    if not selected:
        raise ValueError('Select at least one song in a saved project.')
    for row in selected:
        path = (folder/row['name']).resolve()
        if path.parent != folder:
            raise ValueError('Training songs must be directly inside the dataset folder.')
        stat = path.stat()
        if stat.st_size != row['bytes'] or str(stat.st_mtime_ns) != row['mtime_ns']:
            raise ValueError('A training song changed. Rescan and save a fresh project.')
    return selected
