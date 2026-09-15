"""No network or CUDA initialization: test a fresh user's setup paths."""
import json
from pathlib import Path
from unittest.mock import patch

import pytest
import torch

from yue2_studio import trainer_setup as setup
from yue2_studio.jobs import JobManager


def model_folder(root, kind):
    folder = root/kind;folder.mkdir()
    (folder/'config.json').write_text(json.dumps({'model_type':'yue2' if kind=='model' else 'yue2_vae'}))
    (folder/'model.safetensors').write_bytes(b'fixture not loaded')
    (folder/'qwen.tiktoken').write_text('fixture')
    return str(folder)


def test_local_checks_reject_partial_and_wrong_weights(tmp_path):
    path = Path(model_folder(tmp_path,'model'))
    assert setup.validate_model_folder(str(path),'model')==str(path.resolve())
    with pytest.raises(ValueError):setup.validate_model_folder(str(path),'vae')
    (path/'weights_manifest.json').write_text(json.dumps({'files':{'model.safetensors':{'bytes':999}}}))
    with pytest.raises(ValueError,match='Incomplete'):setup.validate_model_folder(str(path),'model')
    (path/'weights_manifest.json').unlink()
    (path/'model.safetensors.index.json').write_text(json.dumps({'weight_map':{'a':'../escape.safetensors'}}))
    with pytest.raises(ValueError):setup.validate_model_folder(str(path),'model')
    with pytest.raises(ValueError):setup.validate_model_folder('model.gguf','model')


def test_readiness_never_initializes_cuda_or_downloads(tmp_path,monkeypatch):
    monkeypatch.setattr(setup,'ROOT',tmp_path)
    monkeypatch.setattr(setup,'gpu_info',lambda:{'name':'Test GPU','memory_mib':32768,'bf16':True})
    monkeypatch.setattr(setup.shutil,'which',lambda name:None)
    monkeypatch.setattr(torch.version,'cuda','test-cuda-build')
    paths={key:model_folder(tmp_path,key) for key in setup.MODELS}
    with patch.object(torch.cuda,'_lazy_init',side_effect=AssertionError('No GPU allocation')):
        result=setup.readiness(paths)
    assert result['ready'] and result['prepared']=={}
    assert any('FFmpeg' in warning for warning in result['warnings'])
    assert not (tmp_path/'models').exists()
    monkeypatch.setattr(setup,'gpu_info',lambda:None)
    assert not setup.readiness(paths)['ready']


def test_download_is_pinned_verified_and_only_publishes_on_success(tmp_path,monkeypatch):
    from yue2 import storage
    monkeypatch.setattr(setup,'ROOT',tmp_path)
    paths={key:model_folder(tmp_path,key) for key in setup.MODELS}
    calls=[]
    def resolve(repo,**kwargs):
        key=next(k for k,v in setup.MODELS.items() if v['repo']==repo)
        assert kwargs['revision']==setup.MODELS[key]['revision']
        assert kwargs['token'] is False
        assert str(tmp_path/'models/style-trainer-cache')==kwargs['cache_dir']
        calls.append(key)
        return Path(paths[key])
    monkeypatch.setattr(storage,'resolve_model',resolve)
    verified=[]
    monkeypatch.setattr(storage,'model_identity',lambda path,verify:verified.append((str(path),verify)))
    run=tmp_path/'run';run.mkdir()
    setup.download_models(run)
    assert calls==['model','vae'] and all(flag for _,flag in verified)
    assert setup.prepared_models()==paths
    original=(tmp_path/'training/models.json').read_bytes()
    monkeypatch.setattr(storage,'model_identity',lambda *args:(_ for _ in ()).throw(ValueError('bad hash')))
    with pytest.raises(ValueError,match='bad hash'):setup.download_models(run)
    assert (tmp_path/'training/models.json').read_bytes()==original


def test_download_queue_is_separate_from_gpu_training(tmp_path):
    manager=JobManager(tmp_path,start=False)
    job=manager.download_training_models()
    assert job['kind']=='trainer_setup'
    spec=manager.detail(job['id'])['input']
    assert 'yue2_studio.trainer_setup' in manager._command(job['id'],spec)
    assert 'project' not in spec
    with pytest.raises(ValueError,match='already'):manager.download_training_models()
    manager.cancel(job['id'])
    assert manager.jobs[job['id']]['status']=='cancelled'
    assert manager.download_training_models()['id']!=job['id']
