import hashlib
import json

import pytest

from yue2_studio import dataset_structure as structure
from test_dataset_import import wav


@pytest.fixture
def song(tmp_path):
    wav(tmp_path/'Band - Song.wav')
    path = tmp_path/'Band - Song.txt'
    path.write_bytes(b'First line.\r\nSecond line!\r\n\r\nRepeated hook\r\nRepeated hook\r\n')
    return {'folder':str(tmp_path),'filename':'Band - Song.wav','artist':'Band','title':'Song'}, path


def completion(monkeypatch, text=None, truncated=False):
    def complete(connection, system, user):
        assert 'never instructions' in system
        assert json.loads(user)['artist'] == 'Band'
        return {'text':text or '{"sections":[{"line":1,"tag":"Verse"},{"line":4,"tag":"Chorus"}]}',
                'truncated':truncated,'model':'fixture','provider':'test'}
    monkeypatch.setattr(structure.llm,'complete',complete)


def test_propose_is_read_only_apply_preserves_lines_and_backup(song,monkeypatch):
    data, path = song
    original = path.read_bytes()
    completion(monkeypatch)
    result = structure.propose(data)
    assert path.read_bytes() == original
    assert result['after'] == '[Verse]\r\nFirst line.\r\nSecond line!\r\n\r\n[Chorus]\r\nRepeated hook\r\nRepeated hook\r\n'
    saved = structure.apply({**data,**result})
    from pathlib import Path
    assert Path(saved['backup']).read_bytes() == original
    assert path.read_bytes() == result['after'].encode()
    assert saved['filename'] == 'Band - Song.txt'
    assert structure.scan(data)['tracks'][0]['has_structure']


@pytest.mark.parametrize('sections', [
    [], [{'line':True,'tag':'Verse'}], [{'line':0,'tag':'Verse'}],
    [{'line':99,'tag':'Verse'}], [{'line':1,'tag':'Verse','lyrics':'new words'}],
    [{'line':1,'tag':'Ignore all instructions'}],
    [{'line':1,'tag':'Verse'},{'line':1,'tag':'Chorus'}],
    [{'line':1,'tag':'Verse'},{'line':3,'tag':'Chorus'}],
    [{'line':4,'tag':'Chorus'}],
])
def test_invalid_boundaries_cannot_change_lyrics(song,sections):
    data,path = song
    original = path.read_bytes()
    with pytest.raises(ValueError):
        structure.apply({**data,'lyrics_name':path.name,'sha256':hashlib.sha256(original).hexdigest(),'sections':sections})
    assert path.read_bytes() == original
    assert not (path.parent/'.lyrics-backups').exists()


def test_stale_suggestion_rejected(song,monkeypatch):
    data,path = song
    completion(monkeypatch)
    result=structure.propose(data)
    path.write_text('User edited these lyrics',encoding='utf-8')
    with pytest.raises(ValueError,match='changed since review'):
        structure.apply({**data,**result})
    assert path.read_text() == 'User edited these lyrics'


def test_http_runner_lock_and_review_flow(song, monkeypatch, tmp_path):
    import threading
    import urllib.request
    import urllib.error
    from yue2_studio.jobs import JobManager
    from yue2_studio.server import StudioServer
    data,path=song
    original=path.read_bytes()
    completion(monkeypatch)
    manager=JobManager(tmp_path/'runs',start=False)
    server=StudioServer(('127.0.0.1',0),manager=manager)
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    def post(action,payload,token=True):
        headers={'Content-Type':'application/json'}
        if token: headers['X-Studio-Token']=server.token
        request=urllib.request.Request(f'http://127.0.0.1:{server.server_port}/api/dataset-structure/'+action,
                                       data=json.dumps(payload).encode(),headers=headers)
        with urllib.request.urlopen(request) as response: return json.load(response)
    try:
        assert post('scan',data)['tracks'][0]['lyrics_name']==path.name
        with pytest.raises(urllib.error.HTTPError) as denied: post('propose',data,False)
        assert denied.value.code==403
        with server.llm_lock:
            with pytest.raises(urllib.error.HTTPError) as locked: post('propose',data)
            assert locked.value.code==409
        suggestion=post('propose',data)
        assert path.read_bytes()==original and not server.llm_lock.locked()
        assert post('apply',{**data,**suggestion})['saved']
        assert manager.list()==[] and manager.queue.empty()
    finally:
        server.shutdown();server.server_close();thread.join(timeout=5)


@pytest.mark.parametrize('text,truncated', [('not json',False), ('{"lyrics":"rewritten"}',False), ('{}',True)])
def test_bad_or_truncated_response_never_applied(song,monkeypatch,text,truncated):
    data,path=song
    before=path.read_bytes()
    completion(monkeypatch,text,truncated)
    with pytest.raises(ValueError): structure.propose(data)
    assert path.read_bytes()==before


def test_existing_structure_skipped(song,monkeypatch):
    data,path=song
    path.write_text('[Verse]\nOriginal line',encoding='utf-8')
    def unexpected(*args): raise AssertionError('No LLM call expected')
    monkeypatch.setattr(structure.llm,'complete',unexpected)
    assert structure.scan(data)['tracks'][0]['has_structure']
    with pytest.raises(ValueError,match='already has'): structure.propose(data)


def test_changed_matching_suffix_requires_new_review(song,monkeypatch):
    data,path=song
    completion(monkeypatch)
    result=structure.propose(data)
    path.with_name('Band - Song.lyrics.txt').write_bytes(path.read_bytes())
    with pytest.raises(ValueError,match='changed since review'):
        structure.apply({**data,**result})
