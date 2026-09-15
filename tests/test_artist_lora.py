"""CPU-only Artist generation loading, companion, and exact restoration."""
import copy
import hashlib
import json
import pytest
import torch
from yue2.artist_lora import ArtistLoRA,read_adapter
from yue2.modeling_yue2 import YuE2Config,YuE2ForCausalLM
from yue2_studio import artist_encoder,artist_ar,loras
from yue2_studio.settings import defaults
from yue2_studio.jobs import generation_spec


@pytest.fixture
def bundle(tmp_path,monkeypatch):
    torch.set_num_threads(1)
    model=YuE2ForCausalLM(YuE2Config(hidden_size=16,intermediate_size=32,num_hidden_layers=1,
        num_attention_heads=4,num_key_value_heads=2,head_dim=4,vocab_size=32,
        max_position_embeddings=128,latent_dim=64,vae_latent_dim=64,max_latent_frames=128)).eval()
    companion={'rank':32,'lora':[],'io':{}}
    for layer in model.model.layers:
        for branch,names in [('nar_self_attn',('q_proj','k_proj','v_proj','o_proj')),('nar_mlp',('gate_proj','up_proj','down_proj'))]:
            for name in names:
                linear=getattr(getattr(layer,branch),name)
                companion['lora'] += [torch.ones(32,linear.in_features)*.01,torch.ones(linear.out_features,32)*.01]
    for name in ('vae2llm','llm2vae'):companion['io'][name]={k:v.clone()+.01 for k,v in getattr(model,name).state_dict().items()}
    cp=tmp_path/'companion.pt';torch.save(companion,cp);digest=hashlib.sha256(cp.read_bytes()).hexdigest()
    monkeypatch.setitem(artist_encoder.HASHES,'nar_lora_joint_v4.pt',digest)
    adapters=artist_ar.install(copy.deepcopy(model),2)
    with torch.no_grad():
        for module in adapters.values():module.up.fill_(.02)
    folder=tmp_path/'runs/studio'/('a'*32)/'result';folder.mkdir(parents=True)
    path=folder/'final.safetensors'
    artist_ar.export(adapters,path,{'rank':'2','step':'20','encoder_revision':artist_encoder.REVISION,'companion_sha256':digest,'trigger_word':'test_artist'})
    (folder/'manifest.json').write_text(json.dumps({'base':{'model.safetensors':'test'},'companion':{'path':str(cp)}}),encoding='utf-8')
    (folder.parent/'job.json').write_text(json.dumps({'kind':'artist_training','status':'complete','title':'Artist test'}),encoding='utf-8')
    return model,path,cp


def test_artist_and_companion_changes_then_restores(bundle):
    model,path,cp=bundle;adapter=read_adapter(path)
    original={k:v.clone() for k,v in model.state_dict().items()}
    with adapter.applied(model,1):
        assert not torch.equal(model.model.layers[0].self_attn.q_proj.weight,original['model.layers.0.self_attn.q_proj.weight'])
        assert torch.equal(model.vae2llm.weight,original['vae2llm.weight'])
    for strength in (0,.5,1):
        with pytest.raises(InterruptedError):
            with adapter.synthesis_applied(model,strength):
                assert torch.equal(model.vae2llm.weight,original['vae2llm.weight'])==(strength==0)
                assert torch.equal(model.model.layers[0].nar_self_attn.q_proj.weight,original['model.layers.0.nar_self_attn.q_proj.weight'])==(strength==0)
                raise InterruptedError('cancel')
        assert all(torch.equal(value,original[key]) for key,value in model.state_dict().items())
    cp.write_bytes(b'changed')
    with pytest.raises(ValueError,match='companion'):read_adapter(path)


def test_relative_companion_path_uses_bundle_folder(bundle):
    _,path,companion=bundle
    relative=path.parent/'companion.pt';relative.write_bytes(companion.read_bytes())
    manifest=path.parent/'manifest.json'
    data=json.loads(manifest.read_text());data['companion']['path']='companion.pt'
    manifest.write_text(json.dumps(data))
    assert read_adapter(path).companion_path==str(relative.resolve())


def test_catalogue_and_queue_restrictions(bundle,tmp_path,monkeypatch):
    _,path,_=bundle;monkeypatch.setattr(loras,'ROOT',tmp_path)
    result=loras.catalogue();assert len(result['loras'])==1 and result['loras'][0]['kind']=='artist'
    settings=defaults();settings['lora']['path']=str(path)
    request={'style':'guitar','lyrics':'Hello','seed':42,'cot':'off'}
    spec=generation_spec({'request':request,'settings':settings})
    assert spec['lora']['kind']=='artist' and spec['lora']['companion_sha256']
    assert spec['request']['style']=='test_artist, guitar'
    assert generation_spec(spec)['lora']==spec['lora']
    zero=copy.deepcopy(settings);zero['lora']['strength']=0
    assert generation_spec({'request':request,'settings':zero})['lora']['companion_strength']==0
    for mode in ('full','melody'):
        with pytest.raises(ValueError,match='No score'):generation_spec({'request':dict(request,cot=mode),'settings':settings})
    for key,value in [('backend','vllm'),('quantization','fp8'),('offload_ar',True)]:
        modified=copy.deepcopy(settings);modified['runtime'][key]=value
        with pytest.raises(ValueError,match='Artist LoRA'):generation_spec({'request':request,'settings':modified})


def test_pipeline_applies_ar_during_semantic_and_restores(bundle,monkeypatch):
    from yue2 import pipeline
    from yue2.pipeline import YuE2Pipeline,SymbolicPlan,SemanticResult
    from yue2.protocol import SongRequest,GenerationConfig,CODEC_OFFSET
    model,path,_=bundle;pipe=object.__new__(YuE2Pipeline)
    pipe._model=model;pipe.backend='torch-eager';pipe.quantization='none';pipe.offload_ar=False
    pipe.progress=False;pipe.generation_config=GenerationConfig();pipe.tokenizer=object()
    pipe._load_model=lambda **kwargs:model
    monkeypatch.setattr(pipeline,'token_prefixes',lambda *args:[1,2])
    request=SongRequest(style='guitar',lyrics='Hello',cot='off',cfg_scale=1)
    plan=SymbolicPlan(request,None,[],[1,2]);original=model.model.layers[0].self_attn.q_proj.weight.clone()
    pipe.load_lora(path)
    def generate(*args,**kwargs):
        assert not torch.equal(model.model.layers[0].self_attn.q_proj.weight,original)
        return [CODEC_OFFSET],{},False
    pipe._generate=generate
    assert pipe.generate_semantic(plan).tokens==[0]
    assert torch.equal(model.model.layers[0].self_attn.q_proj.weight,original)
    def failed(*args,**kwargs):raise InterruptedError('cancelled')
    pipe._generate=failed
    with pytest.raises(InterruptedError):pipe.generate_semantic(plan)
    assert torch.equal(model.model.layers[0].self_attn.q_proj.weight,original)
    with pytest.raises(ValueError,match='No score'):pipe.plan(request=SongRequest(style='x',lyrics='x',cot='full'))
    import yue2.nar
    original_io=model.vae2llm.weight.clone()
    def synth(*args,**kwargs):
        assert not torch.equal(model.model.layers[0].self_attn.q_proj.weight,original)
        assert not torch.equal(model.vae2llm.weight,original_io)
        return torch.zeros(1,64)
    monkeypatch.setattr(yue2.nar,'synthesize',synth)
    pipe.synthesize(SemanticResult(plan,[0],{},False))
    assert torch.equal(model.model.layers[0].self_attn.q_proj.weight,original)
    assert torch.equal(model.vae2llm.weight,original_io)
    pipe.unload_lora();assert pipe.lora_info is None
