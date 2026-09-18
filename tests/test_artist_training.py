"""CPU-only artist training contracts; no production GPU jobs."""
import os
os.environ['CUDA_VISIBLE_DEVICES']=''
import json
from pathlib import Path
import numpy as np
import pytest
import torch
from safetensors import safe_open
from yue2.modeling_yue2 import YuE2Config,YuE2ForCausalLM
from yue2_studio import artist_ar as ar,artist_training as training
from yue2_studio.artist_prepare import words_of
from yue2_studio.artist_whisper import match_lyrics
from yue2_studio.artist_train_worker import learning_rate_factor,run
from yue2_studio.jobs import JobManager


def test_ar_gradients_frozen_base_and_export(tmp_path):
    torch.set_num_threads(1)
    model=YuE2ForCausalLM(YuE2Config(hidden_size=16,intermediate_size=32,num_hidden_layers=2,
        num_attention_heads=4,num_key_value_heads=2,head_dim=4,vocab_size=32,
        max_position_embeddings=128,latent_dim=64,vae_latent_dim=64,max_latent_frames=128)).eval()
    original={name:value.clone() for name,value in model.state_dict().items()}
    ids=torch.tensor([[1,2,3,4,5,6]])
    initial=ar.loss(model,ids,3,grad=False)[0].detach()
    ar.place_ar(model,'cpu')
    torch.testing.assert_close(ar.loss(model,ids,3,grad=False)[0],initial)
    adapters=ar.install(model,2)
    assert len(adapters)==14 and all('.nar_' not in name for name in adapters)
    torch.testing.assert_close(ar.loss(model,ids,3)[0],initial)
    params=[p for a in adapters.values() for p in (a.down,a.up)]
    cursor=torch.nn.Linear(16,16,bias=False)
    optimizer=torch.optim.AdamW(params+list(cursor.parameters()),lr=.01)
    targets=(0,2,3,torch.tensor([0,1,2]),torch.tensor([0,1,1]),torch.ones(3))
    for _ in range(2):
        optimizer.zero_grad();lm,cl=ar.loss(model,ids,3,cursor,targets,chunk=2)
        (lm+.08*cl).backward()
        assert all(p.grad is not None and torch.isfinite(p.grad).all() for p in params)
        assert cursor.weight.grad.abs().sum()>0
        optimizer.step()
    selective=(0,2,3,torch.tensor([0,1]),torch.tensor([0,1]),torch.ones(2),
               torch.tensor([0,2]),2.)
    lm,cl=ar.loss(model,ids,3,cursor,selective,grad=False,chunk=2)
    assert torch.isfinite(lm) and torch.isfinite(cl)
    for name,value in original.items():
        parent,key=name.rsplit('.',1);module=model.get_submodule(parent)
        if isinstance(module,ar.ArtistLinear):module=module.base
        assert torch.equal(getattr(module,key),value),name
    path=tmp_path/'adapter.safetensors';ar.export(adapters,path,{'rank':'2'})
    with safe_open(str(path),framework='pt') as f:
        assert f.metadata()['format']=='yue2-artist-ar-v1'
        assert len(list(f.keys()))==28


def test_sequences_never_clip():
    item={'name':'song','prefix':[1,2],'codec':np.array([0,1,32767],dtype=np.int32)}
    ids,length=ar.sequence(item,'cpu',6)
    assert length==2 and ids.shape==(1,6) and ids[0,-1].item()==151852
    with pytest.raises(ValueError,match='truncated'):ar.sequence(item,'cpu',5)
    with pytest.raises(ValueError,match='Invalid'):ar.sequence(dict(item,codec=np.array([-1])),'cpu')


def test_alignment_resampler_is_available():
    import ast
    import inspect
    from yue2_studio import artist_prepare
    tree=ast.parse(inspect.getsource(artist_prepare.prepare))
    assert any(isinstance(node,ast.ImportFrom) and node.module=='scipy.signal'
               and any(alias.name=='resample_poly' for alias in node.names)
               for node in ast.walk(tree))


def test_word_offsets_and_cursor():
    from yue2.protocol import SongRequest,token_prefixes
    class CharTokenizer:
        def encode(self,text):return list(map(ord,text))
        def decode(self,ids):return ''.join(map(chr,ids))
    tok=CharTokenizer();lyrics="[Verse]\nI'm here"
    words=words_of(lyrics);assert words==[(8,11,"i'm"),(12,16,'here')]
    item=dict(name='test',style='guitar',lyrics=lyrics,codec=np.zeros(50,dtype=np.int32),words=np.array([[0,.5,.8,8,11],[1,2,.9,12,16]]))
    item['prefix']=token_prefixes(SongRequest(style='guitar',lyrics=lyrics,cot='off'),tok)
    start,end,frames,rows,cols,values=ar.cursor_targets(item,tok,'cpu')
    assert frames==50 and end>start
    torch.testing.assert_close(torch.zeros(frames).index_add_(0,rows,values),torch.ones(frames))
    with pytest.raises(ValueError,match='English'):words_of('bonjour café')
    with pytest.raises(ValueError,match='No alignable'):words_of('[Instrumental]')


def test_whisper_timing_excludes_estimates_from_cursor_loss():
    from types import SimpleNamespace
    from yue2.protocol import SongRequest,token_prefixes
    class CharTokenizer:
        def encode(self,text):return list(map(ord,text))
        def decode(self,ids):return ''.join(map(chr,ids))
    lyrics='[Verse]\nHello loud world'
    result=SimpleNamespace(segments=[SimpleNamespace(words=[
        SimpleNamespace(word='Hello',start=0.,end=.3),
        SimpleNamespace(word='world',start=1.,end=1.3)])])
    timed,summary=match_lyrics(lyrics,result,2.)
    assert summary['counts']=={'exact':2,'fuzzy':0,'estimated':1}
    assert [w['source'] for w in timed]==['exact','estimated','exact']
    tok=CharTokenizer()
    item=dict(name='whisper',style='guitar',lyrics=lyrics,codec=np.zeros(50,dtype=np.int32),
              alignment_method='whisper',words=np.array([[w['start'],w['end'],w['training_weight'],
                                                          w['start_offset'],w['end_offset']] for w in timed]))
    item['prefix']=token_prefixes(SongRequest(style='guitar',lyrics=lyrics,cot='off'),tok)
    cursor=ar.cursor_targets(item,tok,'cpu')
    assert len(cursor)==8
    active=cursor[6].numpy()
    assert 0<len(active)<len(item['codec'])
    assert all((0<=((frame+.5)/25)<.3) or (1<=((frame+.5)/25)<1.3) for frame in active)
    assert cursor[7]==pytest.approx(len(active))


def test_gpu_approval_is_required_before_import_or_preparation(tmp_path):
    with pytest.raises(ValueError,match='not approved'):run({},tmp_path)
    with pytest.raises(ValueError,match='Confirm GPU'):training.training_spec({'project_id':'none'})


def test_cursor_header_newline_merge():
    from yue2.protocol import SongRequest,token_prefixes
    class MergingTokenizer:
        def encode(self,text):return list(map(ord,text.replace('\n\n','\ue000')))
        def decode(self,ids):return ''.join(map(chr,ids)).replace('\ue000','\n\n')
    tok=MergingTokenizer();lyrics='\n[Verse]\nHello'
    item=dict(name='merged',style='guitar',lyrics=lyrics,codec=np.zeros(25,dtype=np.int32),words=np.array([[0,1,.8,9,14]]))
    item['prefix']=token_prefixes(SongRequest(style='guitar',lyrics=lyrics,cot='off'),tok)
    start,end,frames,rows,cols,values=ar.cursor_targets(item,tok,'cpu')
    assert frames==25 and end>start
    torch.testing.assert_close(torch.zeros(frames).index_add_(0,rows,values),torch.ones(frames))


def test_queue_uses_separate_worker_without_starting(tmp_path,monkeypatch):
    monkeypatch.setattr(training,'training_spec',lambda payload:dict(title='Artist test',stage='artist_train',mode='artist_trainer',gpu_confirmed=True,python='custom-runtime/python.exe'))
    manager=JobManager(tmp_path/'runs',start=False)
    job=manager.train_artist({})
    assert job['kind']=='artist_training' and job['status']=='queued'
    command=manager._command(job['id'],manager.detail(job['id'])['input'])
    assert command[0]=='custom-runtime/python.exe' and 'yue2_studio.artist_train_worker' in command
    manager.cancel(job['id']);assert manager.jobs[job['id']]['status']=='cancelled'


def test_http_train_queues_without_gpu(tmp_path,monkeypatch):
    import threading
    import urllib.request
    from yue2_studio.server import StudioServer
    monkeypatch.setattr(training,'training_spec',lambda payload:dict(title='Artist HTTP test',stage='artist_train',mode='artist_trainer',gpu_confirmed=True))
    manager=JobManager(tmp_path/'runs',start=False)
    server=StudioServer(('127.0.0.1',0),manager=manager)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        request=urllib.request.Request(f'http://127.0.0.1:{server.server_port}/api/artist-trainer/train',
            data=b'{}',headers={'Content-Type':'application/json','X-Studio-Token':server.token})
        with urllib.request.urlopen(request) as response:
            assert response.status==202
            job=json.load(response)
        assert job['kind']=='artist_training' and job['status']=='queued'
        assert manager.process is None
    finally:server.shutdown();server.server_close();thread.join(timeout=5)


def test_validation_controls_and_holdout(tmp_path,monkeypatch):
    from yue2_studio import artist_setup
    registered={'files_and_imports_ready':True,'runtime':{'python':'custom/python.exe'},'paths':{'model':'custom-model'}}
    monkeypatch.setattr(artist_setup,'check_setup',lambda:registered)
    monkeypatch.setattr(artist_setup,'check_whisper_runtime',lambda _:dict(stable_ts='2.19.1'))
    lyrics='[Verse]\nSing café'
    lyric_hash=__import__('hashlib').sha256(lyrics.encode()).hexdigest()
    project={'id':'a'*32,'name':'test','tracks':[
        {'name':'a','enabled':True,'lyrics':lyrics,'lyrics_name':'a.txt','lyrics_sha256':lyric_hash,'lyrics_bytes':len(lyrics.encode()),'lyrics_mtime_ns':'1'},
        {'name':'b','enabled':True,'lyrics':'[Verse]\nHello','lyrics_name':'b.txt','lyrics_sha256':'b'*64,'lyrics_bytes':13,'lyrics_mtime_ns':'2'},
    ]}
    monkeypatch.setattr(training.artist_trainer,'load_project',lambda _:project)
    monkeypatch.setattr(training,'validate_project',lambda value:[row for row in value['tracks'] if row['enabled']])
    monkeypatch.setattr(training,'ROOT',tmp_path)
    for file in ['.venv-artist/Scripts/python.exe','models/artist-regularizer/regularizer/minted_regularizer_pack.pt',
                 'models/artist-encoder-v4/tokenizer_head_joint_v4.pt','models/artist-encoder-v4/nar_lora_joint_v4.pt',
                 'models/MERT-v2-FullSong/model.safetensors','models/YuE2-3B/model.safetensors']:
        path=tmp_path/file;path.parent.mkdir(parents=True,exist_ok=True);path.touch()
    valid={'project_id':project['id'],'gpu_confirmed':True}
    spec=training.training_spec(valid)
    assert spec['python']=='custom/python.exe' and spec['paths']=={'model':'custom-model'}
    assert spec['holdout']=='b' and spec['controls']['steps']==800
    assert spec['controls']['checkpoint_every']==200
    assert spec['controls']['lr_schedule']=='auto'
    assert spec['controls']['alignment_method']=='mms'
    assert spec['project']['tracks'][0]['lyrics'].endswith('cafe')
    assert spec['lyrics_cleaning']['songs_changed']==1
    assert training.training_spec(dict(valid,alignment_method='whisper'))['controls']['alignment_method']=='whisper'
    assert training.training_spec(dict(valid,lr_schedule='legacy'))['controls']['lr_schedule']=='legacy'
    explicit=training.training_spec(dict(valid,steps=5000,checkpoint_every=200))
    assert explicit['controls']['steps']==5000 and explicit['controls']['checkpoint_every']==200
    for key,value in [('steps',True),('steps',0),('steps',-1),('rank',0),('alignment_weight',float('nan')),('learning_rate',1),('python','bad')]:
        with pytest.raises(ValueError):training.training_spec(dict(valid,**{key:value}))
    with pytest.raises(ValueError,match='MMS or Whisper'):
        training.training_spec(dict(valid,alignment_method='other'))
    with pytest.raises(ValueError,match='automatic or legacy'):
        training.training_spec(dict(valid,lr_schedule='other'))


def test_validation_uses_source_hash_after_frozen_lyrics_are_cleaned(monkeypatch):
    source_hash='a'*64
    cleaned_hash='b'*64
    rows=[
        {'name':'a.wav','enabled':True,'bytes':10,'mtime_ns':'1','seconds':60,
         'lyrics_sha256':cleaned_hash,'source_lyrics_sha256':source_hash},
        {'name':'b.wav','enabled':True,'bytes':20,'mtime_ns':'2','seconds':90,
         'lyrics_sha256':'c'*64,'source_lyrics_sha256':'d'*64},
    ]
    project={'tracks':rows,'shared_style':'Piano','trigger':'artist'}
    fresh=[
        {'name':'a.wav','bytes':10,'mtime_ns':'1','seconds':60,'lyrics_sha256':source_hash,'error':''},
        {'name':'b.wav','bytes':20,'mtime_ns':'2','seconds':90,'lyrics_sha256':'d'*64,'error':''},
    ]
    monkeypatch.setattr(training.artist_trainer,'scan',lambda _: {'tracks':fresh})
    assert training.validate_project(project)==rows
    fresh[0]['lyrics_sha256']='e'*64
    with pytest.raises(ValueError,match='changed'):
        training.validate_project(project)


def test_artist_learning_rate_schedules_match_requested_steps():
    assert learning_rate_factor(50,800,'auto')==pytest.approx(1.)
    assert learning_rate_factor(800,800,'auto')==pytest.approx(.2)
    assert learning_rate_factor(5000,5000,'auto')==pytest.approx(.2)
    assert learning_rate_factor(400,800,'auto')<learning_rate_factor(400,800,'legacy')
    assert learning_rate_factor(1,1,'auto')==pytest.approx(1.)
    with pytest.raises(ValueError,match='Unknown Artist'):
        learning_rate_factor(1,800,'other')


def test_runtime_shows_historical_gpu_verification(tmp_path,monkeypatch):
    from yue2_studio import artist_trainer
    monkeypatch.setattr(artist_trainer,'ROOT',tmp_path)
    (tmp_path/'training').mkdir()
    receipt={'status':'gpu_smoke_passed','steps':20,'note':'Historical test, not a voice guarantee.'}
    (tmp_path/'training/artist-gpu-verification.json').write_text(json.dumps(receipt),encoding='utf-8')
    assert artist_trainer.runtime_status()==receipt
