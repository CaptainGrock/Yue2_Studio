"""Setup contracts: no real network, pip, GPU or production model reads."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import subprocess

import pytest
from yue2_studio import artist_setup as setup


@pytest.fixture
def root(tmp_path,monkeypatch):
    monkeypatch.setattr(setup,'ROOT',tmp_path)
    return tmp_path


def test_explicit_confirmations_precede_any_changes(root,monkeypatch):
    monkeypatch.setattr(setup,'run_command',lambda *a,**k:pytest.fail('Must not install'))
    for kwargs in ({},{'confirmed':True},{'terms_accepted':True},{'confirmed':1,'terms_accepted':True}):
        with pytest.raises(ValueError):setup.download_models(**kwargs)
    with pytest.raises(ValueError):setup.install_runtime()
    assert not list(root.iterdir())


def test_checks_are_read_only_and_do_not_initialize_gpu(root,monkeypatch):
    monkeypatch.setattr(setup,'run_command',lambda *a,**k:pytest.fail('Missing runtime must not be launched'))
    result=setup.check_setup()
    assert not result['files_and_imports_ready'] and len(result['issues'])==6
    assert not list(root.iterdir())
    env=setup.cpu_env()
    assert env['CUDA_VISIBLE_DEVICES']=='' and env['HF_HUB_OFFLINE']=='1'
    assert 'PYTHONPATH' not in env


def test_model_reuse_and_download_are_pinned_and_verified_before_publication(root,monkeypatch):
    import huggingface_hub
    local=root/'existing';local.mkdir()
    calls=[];verified=[]
    def download(repo,**kwargs):
        kind=next(k for k,v in setup.ASSETS.items() if v['repo']==repo)
        assert kwargs['revision']==setup.ASSETS[kind]['revision']
        assert kwargs['token'] is False and 'cache_dir' not in kwargs
        assert 'scripts/*' not in kwargs['allow_patterns']
        calls.append(kind)
        return kwargs['local_dir']
    def verify(kind,folder):
        verified.append(kind)
        assert not (root/'training/artist-models.json').exists()
        return str(folder)
    monkeypatch.setattr(huggingface_hub,'snapshot_download',download)
    monkeypatch.setattr(setup,'verify_asset',verify)
    result=setup.download_models(confirmed=True,terms_accepted=True,paths={'model':str(local)})
    assert 'model' not in calls and len(calls)==4 and len(verified)==5
    assert result['paths']['model']==str(local)
    assert json.loads((root/'training/artist-models.json').read_text())==result


def test_bad_existing_model_is_not_overwritten_and_registry_survives(root,monkeypatch):
    import huggingface_hub
    local=root/'existing';local.mkdir()
    registry=root/'training/artist-models.json';registry.parent.mkdir()
    registry.write_text(json.dumps({'paths':{'model':str(local)}}))
    original=registry.read_bytes()
    monkeypatch.setattr(huggingface_hub,'snapshot_download',lambda *a,**k:pytest.fail('Do not repair local files'))
    with pytest.raises(ValueError):setup.download_models(confirmed=True,terms_accepted=True)
    assert registry.read_bytes()==original


def test_hash_mismatch_does_not_mutate_file(root,monkeypatch):
    path=root/'weight.pt';path.write_bytes(b'good')
    monkeypatch.setitem(setup.ASSETS,'encoder',{'files':{'weight.pt':hashlib.sha256(b'good').hexdigest()}})
    assert setup.verify_asset('encoder',root)==str(root)
    path.write_bytes(b'bad')
    with pytest.raises(ValueError,match='hash mismatch'):setup.verify_asset('encoder',root)
    assert path.read_bytes()==b'bad'


def test_failed_transfer_keeps_previous_registry(root,monkeypatch):
    import huggingface_hub
    registry=root/'training/artist-models.json';registry.parent.mkdir()
    registry.write_text('{"paths":{}}');before=registry.read_bytes()
    monkeypatch.setattr(huggingface_hub,'snapshot_download',lambda *a,**k:(_ for _ in ()).throw(OSError('offline')))
    with pytest.raises(OSError):setup.download_models(confirmed=True,terms_accepted=True)
    assert registry.read_bytes()==before


def test_runtime_uses_fresh_environment_and_publishes_only_after_probe(root,monkeypatch):
    calls=[]
    def run(args,**kwargs):
        calls.append([str(a) for a in args])
        assert not (root/'training/artist-runtime.json').exists()
        return SimpleNamespace(stdout=json.dumps({'cuda_initialized':False}))
    monkeypatch.setattr(setup,'run_command',run)
    result=setup.install_runtime(confirmed=True)
    assert '.artist-runtimes' in result['python']
    assert calls[0][1:3]==['-m','venv']
    assert all(call[0]==result['python'] for call in calls[1:])
    assert any('check' in call and 'pip' in call for call in calls)
    assert calls[-1][-1]==setup.PROBE
    assert (root/'training/artist-runtime.json').is_file()


def test_failed_runtime_install_preserves_previous_registration(root,monkeypatch):
    registry=root/'training/artist-runtime.json';registry.parent.mkdir()
    registry.write_text('{"python":"previous"}');before=registry.read_bytes()
    monkeypatch.setattr(setup,'run_command',lambda *a,**k:(_ for _ in ()).throw(subprocess.CalledProcessError(1,['mock-pip'])))
    with pytest.raises(subprocess.CalledProcessError):setup.install_runtime(confirmed=True)
    assert registry.read_bytes()==before
