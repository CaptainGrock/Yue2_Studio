"""Explicit setup actions in the serial Studio queue; never starts training."""
import json
from pathlib import Path
import sys
from . import artist_setup

def setup_spec(payload):
    if set(payload)-{'action','confirmed','terms_accepted','paths'}:raise ValueError('Unknown Artist setup options.')
    action=payload.get('action')
    if action not in ('check','download-models','install-runtime'):raise ValueError('Unknown Artist setup action.')
    paths=payload.get('paths',{})
    if not isinstance(paths,dict) or set(paths)-set(artist_setup.ASSETS) or any(not isinstance(v,str) for v in paths.values()):raise ValueError('Choose local Artist model paths.')
    if action!='check' and payload.get('confirmed') is not True:raise ValueError('Confirm Artist setup changes first.')
    if action=='download-models' and payload.get('terms_accepted') is not True:raise ValueError('Review and accept model terms first.')
    return dict(title='Artist setup: '+action,stage='artist_setup',mode='artist_trainer',action=action,paths=dict(paths),confirmed=payload.get('confirmed') is True,terms_accepted=payload.get('terms_accepted') is True)

def run(spec,directory):
    action=spec['action']
    print('Artist setup starting: '+action+'. No GPU work.',flush=True)
    if action=='check':result=artist_setup.check_setup(spec['paths'])
    elif action=='download-models':result=artist_setup.download_models(confirmed=spec['confirmed'],terms_accepted=spec['terms_accepted'],paths=spec['paths'])
    elif action=='install-runtime':result=artist_setup.install_runtime(confirmed=spec['confirmed'])
    else:raise ValueError('Unknown setup action.')
    artist_setup.write_record(directory/'result/artist_setup.json',result)
    if action=='check' and not result['files_and_imports_ready']:raise ValueError('Artist setup incomplete: '+'; '.join(result['issues']))
    print('Artist setup finished. No training started.',flush=True)

if __name__=='__main__':
    path=Path(sys.argv[1]).resolve()
    run(json.loads(path.read_text(encoding='utf-8')),path.parent)
