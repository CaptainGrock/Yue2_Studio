"""Dataset preparation only; no model loading or GPU jobs."""
import json
import threading
import urllib.request

import numpy as np
import pytest
import soundfile as sf

from yue2_studio import trainer
from yue2_studio.jobs import JobManager
from yue2_studio.server import StudioServer


@pytest.fixture
def dataset(tmp_path, monkeypatch):
    monkeypatch.setattr(trainer,'ROOT',tmp_path)
    folder=tmp_path/'songs';folder.mkdir()
    sf.write(folder/'song.wav',np.zeros((48000*12,2)),48000)
    (folder/'song.txt').write_text('[Verse]\nOriginal words',encoding='utf-8')
    sf.write(folder/'short.wav',np.zeros(4000),8000)
    (folder/'broken.wav').write_bytes(b'broken audio')
    (folder/'collection_metadata.json').write_text(json.dumps({'singer_name':'Test singer','global_style_prompt':'Warm piano'}),encoding='utf-8')
    return folder


def setup(folder):
    result=trainer.scan({'folder':str(folder)})
    return {**result,'name':'First style','trigger':'test_style','default_caption':'Warm piano','goal':'production'}


def test_scan_ignores_sidecars_and_flags_unusable_audio(dataset):
    result=trainer.scan({'folder':str(dataset)})
    rows={row['name']:row for row in result['tracks']}
    assert rows['song.wav']['clips']==1 and rows['song.wav']['seconds']==12
    assert 'caption' not in rows['song.wav']
    assert 'source_text' not in rows['song.wav']
    assert 'text_kind' not in result
    assert isinstance(rows['song.wav']['mtime_ns'],str)  # JS-safe nanosecond identity.
    assert not rows['short.wav']['enabled'] and rows['short.wav']['warnings']
    assert not rows['broken.wav']['enabled'] and rows['broken.wav']['error']
    assert result['metadata']['style_prompt']=='Warm piano'
    # A malformed sidecar has no effect on training preparation.
    (dataset/'song.txt').write_bytes(b'\xff\xfe\x80')
    assert trainer.scan({'folder':str(dataset)})==result


def test_versioned_save_reload_does_not_touch_sources(dataset):
    original=(dataset/'song.txt').read_bytes()
    payload=setup(dataset)
    payload['default_caption']='Intimate piano ballad'
    first=trainer.save_project(payload);second=trainer.save_project(payload)
    assert first['id']!=second['id'] and len(trainer.projects())==2
    assert trainer.load_project(first['id'])==first
    assert (dataset/'song.txt').read_bytes()==original
    assert first['status']=='prepared'
    assert first['default_caption']=='Intimate piano ballad'
    assert all('caption' not in row and 'source_text' not in row for row in first['tracks'])


def test_changed_file_empty_selection_and_missing_caption_fail(dataset):
    data=setup(dataset)
    data['default_caption']=''
    with pytest.raises(ValueError,match='caption'):
        trainer.save_project(data)
    data=setup(dataset)
    for row in data['tracks']:row['enabled']=False
    with pytest.raises(ValueError,match='at least one'):
        trainer.save_project(data)
    data=setup(dataset)
    (dataset/'song.wav').write_bytes(b'changed')
    with pytest.raises(ValueError,match='changed'):
        trainer.save_project(data)


def test_reject_extra_tracks_and_bad_ids(dataset):
    data=setup(dataset)
    data['tracks'].append({'name':'../outside.wav'})
    with pytest.raises(ValueError,match='contents changed'):
        trainer.save_project(data)
    with pytest.raises(ValueError,match='ID'):
        trainer.load_project('../../outside')
    for clip in [0,float('nan'),True,31]:
        with pytest.raises(ValueError):trainer.scan({'folder':str(dataset),'clip_seconds':clip})


def test_http_scan_save_open_and_no_render_jobs(dataset,tmp_path):
    manager=JobManager(tmp_path/'runs',start=False)
    server=StudioServer(('127.0.0.1',0),manager=manager)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    base=f'http://127.0.0.1:{server.server_port}'
    def post(path,data):
        req=urllib.request.Request(base+path,data=json.dumps(data).encode(),headers={'Content-Type':'application/json','X-Studio-Token':server.token})
        with urllib.request.urlopen(req) as response:return json.load(response)
    try:
        scanned=post('/api/trainer/scan',{'folder':str(dataset)})
        saved=post('/api/trainer/projects',{**scanned,'name':'Test','trigger':'test','default_caption':'Piano'})
        with urllib.request.urlopen(base+'/api/trainer/projects/'+saved['id']) as response:
            assert json.load(response)['name']=='Test'
        with urllib.request.urlopen(base+'/trainer.js') as response:
            assert b'function bindTrainer' in response.read()
        assert manager.list()==[]
        for name in ('YuE2-3B','YuE2-Vae'):
            model=tmp_path/'models'/name;model.mkdir(parents=True)
            (model/'config.json').write_text(json.dumps({'model_type':'yue2' if name=='YuE2-3B' else 'yue2_vae'}))
            (model/'model.safetensors').write_bytes(b'not loaded by this test')
            (model/'qwen.tiktoken').write_text('placeholder')
        from unittest.mock import patch
        with patch('yue2_studio.trainer_setup.readiness',return_value={'ready':True}):
            job=post('/api/trainer/train',{'project_id':saved['id']})
        assert job['kind']=='training' and job['status']=='queued'
        assert manager.detail(job['id'])['input']['project']['default_caption']=='Piano'
        assert manager.detail(job['id'])['input']['controls']['steps']==2000
        assert manager.detail(job['id'])['input']['controls']['checkpoint_every']==500
    finally:
        server.shutdown();server.server_close();thread.join(timeout=5)
