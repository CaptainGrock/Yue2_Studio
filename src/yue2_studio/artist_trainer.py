"""Artist setup only: CPU header/text checks, no encoder, training, or jobs."""
import hashlib
import json
from pathlib import Path
import re
import uuid
from datetime import datetime, timezone

from .settings import ROOT
from .trainer import _text, scan as audio_scan


def scan(payload):
    convention = payload.get('lyrics_suffix','.lyrics.txt')
    if convention not in ('.lyrics.txt','.txt'):
        raise ValueError('Choose song.lyrics.txt or song.txt for the lyric filenames.')
    data = audio_scan({'folder':payload.get('folder',''),'clip_seconds':2})
    folder = Path(data['folder'])
    total_text = 0
    stems = {}
    for row in data['tracks']:
        stem = Path(row['name']).stem.casefold()
        stems[stem] = stems.get(stem,0)+1
    for row in data['tracks']:
        row.pop('clips',None)
        row['warnings'] = [w for w in row['warnings'] if w!='Shorter than one training clip.']
        row.update(lyrics_name=Path(row['name']).stem+convention,lyrics='',lyrics_sha256='',lyrics_bytes=0,lyrics_mtime_ns='')
        try:
            if stems[Path(row['name']).stem.casefold()]>1:
                raise ValueError('Multiple audio files share this name; make each audio/lyrics pair uniquely named.')
            path = (folder/row['lyrics_name']).resolve()
            if path.parent!=folder or not path.is_file():
                raise ValueError('Missing matching lyrics file: '+row['lyrics_name'])
            with path.open('rb') as handle:
                raw = handle.read(65537)
            if len(raw)>65536:
                raise ValueError('Lyrics file exceeds 64 KB.')
            text = raw.decode('utf-8-sig')
            if '\0' in text or not re.sub(r'\[[^\]]*\]|\s','',text):
                raise ValueError('Lyrics must contain sung words, not just section tags.')
            total_text += len(raw)
            if total_text>1000000:
                raise ValueError('Combined lyrics exceed 1 MB; use a smaller dataset.')
            stat = path.stat()
            row.update(lyrics=text,lyrics_sha256=hashlib.sha256(raw).hexdigest(),lyrics_bytes=len(raw),lyrics_mtime_ns=str(stat.st_mtime_ns))
            if not re.search(r'\[(?:verse|chorus|bridge|intro|outro|pre.chorus|hook)\b',text,re.I):
                row['warnings'].append('No familiar section tags found. Review that this is full lyrics, not a style caption.')
            if row['seconds']<2:
                raise ValueError('Recording is too short for this setup (under 2 seconds).')
        except (OSError,UnicodeError,ValueError) as exc:
            row['error'] = '; '.join(filter(None,[row['error'],str(exc)]))
        row['enabled'] = not bool(row['error'])
    if total_text>1000000:
        raise ValueError('Combined lyrics exceed 1 MB; use a smaller dataset.')
    return dict(folder=data['folder'],lyrics_suffix=convention,tracks=data['tracks'],metadata=data['metadata'],
                note='CPU checks only. No audio encoding or lyric alignment has run. Review complete lyrics against each recording; filenames do not prove a correct match.')


def project_root():
    return ROOT/'training'/'artist_projects'


def runtime_status():
    """Read historical verification receipts; never launch a model or process."""
    gpu=ROOT/'training/artist-gpu-verification.json'
    if gpu.is_file():
        data=json.loads(gpu.read_text(encoding='utf-8'))
        if data.get('status')=='gpu_smoke_passed':return data
    path=ROOT/'training/artist-preflight.json'
    if not path.is_file():
        return {'status':'not_checked','note':'Encoder preparation has not been verified.'}
    data=json.loads(path.read_text(encoding='utf-8'))
    data['checked_at']=datetime.fromtimestamp(path.stat().st_mtime,timezone.utc).isoformat()
    data['note']='Last CPU verification only. Artist training still requires a separately approved GPU smoke test.'
    return data


def save_project(payload):
    name = _text(payload.get('name',''),'project name',120)
    trigger = _text(payload.get('trigger',''),'trigger phrase',200)
    style = _text(payload.get('shared_style',''),'shared style')
    if not name or not trigger or not style:
        raise ValueError('Enter a project name, trigger phrase, and shared style.')
    if payload.get('lyrics_reviewed') is not True:
        raise ValueError('Confirm you reviewed the selected lyrics against their recordings.')
    data = scan(payload)
    supplied = payload.get('tracks')
    if not isinstance(supplied,list) or any(not isinstance(r,dict) or not isinstance(r.get('name'),str) for r in supplied):
        raise ValueError('Scan the folder before saving.')
    choices = {r['name']:r for r in supplied}
    if len(choices)!=len(supplied) or set(choices)!={r['name'] for r in data['tracks']}:
        raise ValueError('Dataset contents changed. Scan again.')
    for row in data['tracks']:
        choice = choices[row['name']]
        if any(choice.get(k)!=row[k] for k in ('bytes','mtime_ns','lyrics_name','lyrics_sha256','lyrics_bytes','lyrics_mtime_ns')):
            raise ValueError('Audio or lyrics changed since scanning. Scan again before saving.')
        if type(choice.get('enabled')) is not bool or (choice['enabled'] and row['error']):
            raise ValueError('Exclude songs with errors before saving.')
        row['enabled'] = choice['enabled']
    if not any(r['enabled'] for r in data['tracks']):
        raise ValueError('Select at least one valid audio/lyrics pair.')
    value = dict(schema=1,kind='artist_setup',id=uuid.uuid4().hex,status='setup_only',
                 created=datetime.now(timezone.utc).isoformat(),name=name,trigger=trigger,shared_style=style,
                 lyrics_reviewed=True,encoder='Mothersuperior/yue2-mothersuperior-realaudio-tokenizer-v4',**data)
    project_root().mkdir(parents=True,exist_ok=True)
    with (project_root()/(value['id']+'.json')).open('x',encoding='utf-8') as handle:
        json.dump(value,handle,ensure_ascii=False,indent=2)
    return value


def load_project(project_id):
    if not re.fullmatch(r'[a-f0-9]{32}',project_id):
        raise ValueError('Invalid artist project ID.')
    return json.loads((project_root()/(project_id+'.json')).read_text(encoding='utf-8'))


def projects():
    items=[]
    for path in project_root().glob('*.json'):
        try:
            value=load_project(path.stem)
            items.append({k:value[k] for k in ('id','name','created','status')})
        except (ValueError,KeyError,OSError):
            continue
    return sorted(items,key=lambda r:r['created'],reverse=True)
