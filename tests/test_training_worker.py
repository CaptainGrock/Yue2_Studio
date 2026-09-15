"""Small CPU checks only: never load production weights or submit a GPU run."""
import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
import torch

from yue2.modeling_yue2 import YuE2Config, YuE2ForCausalLM
from yue2.lora import AcousticLoRA
from yue2_studio import trainer, training_worker as worker
from yue2_studio.jobs import JobManager


@pytest.fixture
def tiny():
    old = torch.get_num_threads()
    torch.set_num_threads(1)
    torch.manual_seed(73)
    model = YuE2ForCausalLM(YuE2Config(hidden_size=16,intermediate_size=32,num_hidden_layers=2,
        num_attention_heads=4,num_key_value_heads=2,head_dim=4,vocab_size=32,
        max_position_embeddings=128,latent_dim=64,vae_latent_dim=64,max_latent_frames=128)).eval()
    yield model
    torch.set_num_threads(old)


def test_gradients_frozen_base_export_and_inference_roundtrip(tiny,tmp_path):
    base = {name:value.clone() for name,value in tiny.state_dict().items()}
    seq = worker.sequence([1,2],3,'cpu',(3,4,5))
    clean, noise = torch.randn(3,64),torch.randn(3,64)
    initial = worker.training_loss(tiny,seq,clean,0.,noise)
    adapters = worker.install_adapters(tiny,2)
    assert len(adapters)==8
    assert torch.equal(initial,worker.training_loss(tiny,seq,clean,0.,noise))
    params = [p for module in adapters.values() for p in (module.down,module.up)]
    optimizer = torch.optim.AdamW(params,lr=0.001)
    for _ in range(2):
        optimizer.zero_grad()
        loss = worker.training_loss(tiny,seq,clean,0.,noise)
        loss.backward()
        assert all(p.grad is not None and torch.isfinite(p.grad).all() for p in params)
        assert any(p.grad.abs().sum()>0 for p in params)
        optimizer.step()
    for name,value in base.items():
        parent,key = name.rsplit('.',1)
        actual = tiny.get_submodule(parent)
        if isinstance(actual,worker.TrainLinear):actual=actual.base
        assert torch.equal(getattr(actual,key),value),name
    path = tmp_path/'trained.safetensors'
    worker.export_adapter(adapters,path,{'trigger_word':'test','alpha':'2','step':'2'})
    adapter = AcousticLoRA.read(path)
    trained = type(tiny).nar_velocity.__wrapped__(tiny,*seq,clean,0.).detach()
    for name,module in adapters.items():
        parent,key=name.rsplit('.',1)
        setattr(tiny.get_submodule(parent),key,module.base)
    adapter.validate_model(tiny)
    with adapter.applied(tiny,1):
        merged = tiny.nar_velocity(*seq,clean,0.)
    torch.testing.assert_close(trained,merged,atol=1e-5,rtol=1e-5)


def saved_project(tmp_path,monkeypatch):
    monkeypatch.setattr(trainer,'ROOT',tmp_path)
    folder=tmp_path/'songs';folder.mkdir()
    sf.write(folder/'test.wav',np.zeros((96000,2),dtype=np.float32),48000)
    project=trainer.save_project({**trainer.scan({'folder':str(folder),'clip_seconds':2}),
        'name':'Test','trigger':'test_sound','default_caption':'Warm guitar'})
    for name in ('YuE2-3B','YuE2-Vae'):
        model=tmp_path/'models'/name;model.mkdir(parents=True)
        (model/'config.json').write_text(json.dumps({'model_type':'yue2' if name=='YuE2-3B' else 'yue2_vae'}))
        (model/'model.safetensors').write_bytes(b'test placeholder, never loaded')
        (model/'qwen.tiktoken').write_text('placeholder')
    return project


def test_queue_snapshot_validation_and_cooperative_cancel(tmp_path,monkeypatch):
    project=saved_project(tmp_path,monkeypatch)
    manager=JobManager(tmp_path/'runs',start=False)
    first=manager._add('generation',{'title':'Existing render','settings':{'runtime':{'backend':'torch'}}})
    job=manager.train({'project_id':project['id']})
    assert manager.queue.get_nowait()==first['id']
    assert manager.queue.get_nowait()==job['id']
    spec=manager.detail(job['id'])['input']
    assert spec['project']['default_caption']=='Warm guitar'
    assert spec['controls']['steps']==20
    assert 'yue2_studio.training_worker' in manager._command(job['id'],spec)
    class Process:
        def poll(self):return None
        def terminate(self):raise AssertionError('Must not kill a running trainer on normal cancel')
    manager.jobs[job['id']]['status']='running'
    manager.active_id=job['id'];manager.process=Process()
    manager.cancel(job['id'])
    with pytest.raises(worker.Cancelled):worker.check_cancel(manager.directory(job['id']))
    assert manager.jobs[first['id']]['status']=='queued'
    for bad in ({'steps':True},{'rank':0},{'learning_rate':float('nan')},{'checkpoint_every':0},{'model':'remote/repo'}):
        with pytest.raises(ValueError):trainer.training_spec({'project_id':project['id'],**bad})
    (Path(project['folder'])/'test.wav').write_bytes(b'changed')
    with pytest.raises(ValueError,match='changed'):trainer.training_spec({'project_id':project['id']})


def test_cache_reuse_and_vae_identity_invalidation(tmp_path,monkeypatch):
    project=saved_project(tmp_path,monkeypatch)
    monkeypatch.setattr(worker,'ROOT',tmp_path)
    from yue2 import modeling_vae
    calls=[]
    class Decoder:
        def to(self,*args):return self
    class FakeVAE:
        decoder=Decoder()
        @classmethod
        def from_pretrained(cls,*args,**kwargs):return cls()
        def encode(self,audio):
            calls.append(audio.shape)
            return torch.ones((1,64,audio.shape[-1]//1920))
    monkeypatch.setattr(modeling_vae,'YuE2VAE',FakeVAE)
    directory=tmp_path/'run';(directory/'result').mkdir(parents=True)
    spec={'project':project,'vae':'not-loaded'}
    first=worker.cache_audio(spec,directory,torch.device('cpu'),{'weights':'one'})
    second=worker.cache_audio(spec,directory,torch.device('cpu'),{'weights':'one'})
    assert first==second and len(calls)==1
    third=worker.cache_audio(spec,directory,torch.device('cpu'),{'weights':'two'})
    assert third!=first and len(calls)==2
    assert json.loads((directory/'result/dataset.json').read_text())['clips']==1
    (directory/'cancel.request').touch()
    with pytest.raises(worker.Cancelled):worker.cache_audio(spec,directory,torch.device('cpu'),{})


def test_audio_mono_conversion_and_nonfinite_export(tmp_path,tiny):
    path=tmp_path/'mono.wav'
    sf.write(path,np.linspace(-.5,.5,48000,dtype=np.float32),48000)
    audio=worker.audio_clip(path,0,.5)
    assert audio.shape==(1,2,24000)
    assert torch.equal(audio[:,0],audio[:,1])
    adapters=worker.install_adapters(tiny,2)
    with torch.no_grad():next(iter(adapters.values())).up.fill_(float('nan'))
    with pytest.raises(ValueError,match='non-finite'):worker.export_adapter(adapters,tmp_path/'bad.safetensors',{})
    assert not (tmp_path/'bad.safetensors').exists()
