"""Artist setup/queue integration without installing or starting workers."""
import json
import threading
import urllib.request
import pytest
from yue2_studio.jobs import JobManager
from yue2_studio.server import StudioServer
from yue2_studio import artist_setup_worker as worker


def test_setup_confirmation_deduplication_and_serial_queue(tmp_path):
    manager=JobManager(tmp_path/'runs',start=False)
    existing=manager._add('training',{'title':'Existing run'})
    for data in ({'action':'install-runtime'},{'action':'download-models','confirmed':True},{'action':'check','paths':{'bogus':'x'}}):
        with pytest.raises(ValueError):manager.prepare_artist(data)
    job=manager.prepare_artist({'action':'check','paths':{'model':'custom'}})
    assert manager.queue.get_nowait()==existing['id']
    assert manager.queue.get_nowait()==job['id']
    assert 'yue2_studio.artist_setup_worker' in manager._command(job['id'],manager.detail(job['id'])['input'])
    with pytest.raises(ValueError,match='already'):manager.prepare_artist({'action':'check'})
    manager.cancel(job['id'])
    assert manager.jobs[existing['id']]['status']=='queued'
    assert manager.process is None


def test_check_failure_retains_receipt_and_never_installs(tmp_path,monkeypatch):
    monkeypatch.setattr(worker.artist_setup,'check_setup',lambda paths:{'files_and_imports_ready':False,'issues':['Missing models']})
    monkeypatch.setattr(worker.artist_setup,'install_runtime',lambda **kw:pytest.fail('Check cannot install'))
    with pytest.raises(ValueError,match='incomplete'):worker.run(worker.setup_spec({'action':'check'}),tmp_path)
    assert json.loads((tmp_path/'result/artist_setup.json').read_text())['issues']==['Missing models']


def test_http_setup_routes_and_static_script(tmp_path,monkeypatch):
    manager=JobManager(tmp_path/'runs',start=False)
    server=StudioServer(('127.0.0.1',0),manager=manager)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    base=f'http://127.0.0.1:{server.server_port}'
    try:
        with urllib.request.urlopen(base+'/artist.js') as response:assert b'bindArtistSetup' in response.read()
        request=urllib.request.Request(base+'/api/artist-trainer/setup',data=b'{"action":"check"}',headers={'Content-Type':'application/json','X-Studio-Token':server.token})
        with urllib.request.urlopen(request) as response:
            assert response.status==202
            job=json.load(response)
        assert job['kind']=='artist_setup' and job['status']=='queued' and manager.process is None
    finally:server.shutdown();server.server_close();thread.join(timeout=5)
