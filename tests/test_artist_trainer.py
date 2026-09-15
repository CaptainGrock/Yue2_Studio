"""Artist setup tests: no model loading, GPU, or live server."""
import json
import threading
import urllib.request

import numpy as np
import pytest
import soundfile as sf

from yue2_studio import artist_trainer as artist
from yue2_studio.jobs import JobManager
from yue2_studio.server import StudioServer


@pytest.fixture
def dataset(tmp_path,monkeypatch):
    monkeypatch.setattr(artist,'ROOT',tmp_path)
    folder=tmp_path/'songs';folder.mkdir()
    sf.write(folder/'song.wav',np.zeros((48000*3,2)),48000)
    (folder/'song.txt').write_text('[Verse]\nThese are the complete words',encoding='utf-8')
    return folder


def payload(folder):
    return {**artist.scan({'folder':str(folder),'lyrics_suffix':'.txt'}),
            'name':'Artist test','trigger':'test_artist','shared_style':'Warm guitar','lyrics_reviewed':True}


def test_explicit_sidecar_choice_and_preview(dataset):
    strict=artist.scan({'folder':str(dataset)})
    assert not strict['tracks'][0]['enabled']
    assert 'Missing' in strict['tracks'][0]['error']
    data=payload(dataset)
    row=data['tracks'][0]
    assert row['enabled'] and row['lyrics'].startswith('[Verse]')
    assert row['lyrics_name']=='song.txt' and len(row['lyrics_sha256'])==64
    assert 'clips' not in row and 'clip_seconds' not in data


def test_save_is_separate_versioned_and_rechecks_text(dataset,tmp_path):
    data=payload(dataset)
    original=(dataset/'song.txt').read_bytes()
    first=artist.save_project(data);second=artist.save_project(data)
    assert first['id']!=second['id'] and len(artist.projects())==2
    assert artist.load_project(first['id'])==first
    assert first['status']=='setup_only' and first['kind']=='artist_setup'
    assert (dataset/'song.txt').read_bytes()==original
    assert not (tmp_path/'training/projects').exists()
    assert not (tmp_path/'runs').exists()
    (dataset/'song.txt').write_text('[Verse]\nDifferent words',encoding='utf-8')
    with pytest.raises(ValueError,match='changed'):artist.save_project(data)


def test_invalid_selection_review_and_text(dataset):
    data=payload(dataset);data['lyrics_reviewed']=False
    with pytest.raises(ValueError,match='Confirm'):artist.save_project(data)
    data=payload(dataset);data['tracks'][0]['enabled']=False
    with pytest.raises(ValueError,match='at least one'):artist.save_project(data)
    for contents in (b'\xff\xfe\x80',b'[Verse]\n[Chorus]',b'x'*65537):
        (dataset/'song.txt').write_bytes(contents)
        assert payload(dataset)['tracks'][0]['error']
    with pytest.raises(ValueError):artist.load_project('../outside')
    with pytest.raises(ValueError):artist.scan({'folder':str(dataset),'lyrics_suffix':'../../other'})


def test_duplicate_audio_stems_and_style_only_warning(dataset):
    (dataset/'song.txt').write_text('Warm piano, soft drums',encoding='utf-8')
    assert any('section tags' in w for w in payload(dataset)['tracks'][0]['warnings'])
    sf.write(dataset/'song.flac',np.zeros((48000*3,2)),48000)
    assert all('Multiple audio' in row['error'] for row in payload(dataset)['tracks'])


def test_http_setup_never_queues_training(dataset,tmp_path):
    manager=JobManager(tmp_path/'runs',start=False)
    server=StudioServer(('127.0.0.1',0),manager=manager)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    base=f'http://127.0.0.1:{server.server_port}'
    def post(path,data):
        request=urllib.request.Request(base+path,data=json.dumps(data).encode(),headers={'Content-Type':'application/json','X-Studio-Token':server.token})
        with urllib.request.urlopen(request) as response:return json.load(response)
    try:
        scanned=post('/api/artist-trainer/scan',{'folder':str(dataset),'lyrics_suffix':'.txt'})
        saved=post('/api/artist-trainer/projects',{**scanned,'name':'Test','trigger':'test','shared_style':'Guitar','lyrics_reviewed':True})
        with urllib.request.urlopen(base+'/api/artist-trainer/projects/'+saved['id']) as response:
            assert json.load(response)['shared_style']=='Guitar'
        with urllib.request.urlopen(base+'/api/artist-trainer/projects') as response:
            assert len(json.load(response)['projects'])==1
        assert manager.list()==[] and manager.queue.empty()
    finally:
        server.shutdown();server.server_close();thread.join(timeout=5)
