"""Pinned community encoder loading and CPU compatibility checks.

Implements the checkpoint architecture described by the pinned upstream
ar_prep.py; upstream scripts are reference material, never imported/executed.
No GPU work occurs on import or in preflight().
"""
import hashlib
import json
from pathlib import Path

import numpy as np
import torch
from torch import nn

from .settings import ROOT

REPO = 'Mothersuperior/yue2-mothersuperior-realaudio-tokenizer-v4'
REVISION = 'f2278a2e005dc4ecc421c53a0929f62b3aeb2280'
HASHES = {
    'tokenizer_head_joint_v4.pt':'d23c4f757a05f031134b8471ec84245ec2338966516e1a9e26a17ff300a5f87e',
    'nar_lora_joint_v4.pt':'df175dbf9405a8e15b2c3f8dbdcc97303575f763787f227b03029020e28102fe',
}


def sha256(path):
    value=hashlib.sha256()
    with Path(path).open('rb') as handle:
        while block:=handle.read(8*1024*1024):value.update(block)
    return value.hexdigest()


def load_checkpoint(folder,name):
    path=Path(folder)/name
    if name not in HASHES or sha256(path)!=HASHES[name]:
        raise ValueError('Community checkpoint hash mismatch: '+name)
    return torch.load(path,map_location='cpu',weights_only=True)


class SemanticHead(nn.Module):
    def __init__(self):
        super().__init__()
        self.inp=nn.Linear(1024,512)
        self.pos=nn.Parameter(torch.zeros(1,512,512))
        layer=nn.TransformerEncoderLayer(512,8,2048,dropout=.1,batch_first=True,norm_first=True,activation='gelu')
        self.enc=nn.TransformerEncoder(layer,8,enable_nested_tensor=False)
        self.norm=nn.LayerNorm(512)
        self.head=nn.Linear(512,32768)

    def forward(self,x):
        return self.head(self.norm(self.enc(self.inp(x)+self.pos[:,:x.shape[1]])))


def load_head(folder):
    checkpoint=load_checkpoint(folder,'tokenizer_head_joint_v4.pt')
    head=SemanticHead().eval().requires_grad_(False)
    head.load_state_dict(checkpoint['model'],strict=True)
    if not all(torch.isfinite(p).all() for p in head.parameters()):
        raise ValueError('Non-finite encoder weights.')
    return head


def normalize_features(features):
    x=np.asarray(features,dtype=np.float32)
    if x.ndim!=2 or x.shape[1]!=1024 or not len(x) or not np.isfinite(x).all():
        raise ValueError('Expected nonempty finite MERT features [frames,1024].')
    return (x-x.mean(0))/(x.std(0)+1e-5)


def window_ranges(frames):
    if type(frames) is not int or frames<1:raise ValueError('Expected a positive frame count.')
    starts=list(range(0,max(1,frames-512+1),256))
    if starts[-1]+512<frames:starts.append(max(0,frames-512))
    for start in starts:
        length=min(512,frames-start)
        lo=start+(0 if start==0 else 128)
        hi=start+length-(0 if start+length>=frames else 128)
        yield start,length,lo,hi


@torch.inference_mode()
def predict_tokens(head,features,device):
    from contextlib import nullcontext
    x=normalize_features(features)
    output=np.zeros(len(x),dtype=np.int32)
    for start,length,lo,hi in window_ranges(len(x)):
        window=np.pad(x[start:start+length],((0,512-length),(0,0)))
        context=torch.autocast('cuda',dtype=torch.bfloat16) if device.type=='cuda' else nullcontext()
        with context:
            logits=head(torch.from_numpy(window[None]).to(device))
        prediction=logits[0,:length].float().argmax(-1).cpu().numpy()
        output[lo:hi]=prediction[lo-start:hi-start]
    return output


@torch.no_grad()
def apply_companion(model,checkpoint):
    """Use only in an isolated reconstruction process; changes RAM, not files."""
    check_nar(checkpoint,model.config.to_dict())
    pairs=iter(checkpoint['lora'])
    for layer in model.model.layers:
        for module,names in [(layer.nar_self_attn,('q_proj','k_proj','v_proj','o_proj')),
                             (layer.nar_mlp,('gate_proj','up_proj','down_proj'))]:
            for name in names:
                linear=getattr(module,name)
                down,up=next(pairs),next(pairs)
                delta=up.float()@down.float()
                linear.weight.add_(delta.to(device=linear.weight.device,dtype=linear.weight.dtype))
    for name in ('vae2llm','llm2vae'):
        getattr(model,name).load_state_dict(checkpoint['io'][name],strict=True)


def check_nar(checkpoint,config):
    hidden=config['hidden_size'];inner=config['intermediate_size']
    query=config['num_attention_heads']*config['head_dim']
    kv=config['num_key_value_heads']*config['head_dim']
    rank=checkpoint['rank'];tensors=checkpoint['lora']
    expected=[]
    for _ in range(config['num_hidden_layers']):
        for out_size,in_size in [(query,hidden),(kv,hidden),(kv,hidden),(hidden,query),
                                 (inner,hidden),(inner,hidden),(hidden,inner)]:
            expected.extend([(rank,in_size),(out_size,rank)])
    if rank!=32 or len(tensors)!=len(expected):raise ValueError('NAR adapter count/rank mismatch.')
    for value,shape in zip(tensors,expected):
        if tuple(value.shape)!=shape or not torch.isfinite(value).all():
            raise ValueError('NAR adapter shape or finite-value check failed.')
    dim=config['latent_dim']
    expected_io={'vae2llm':{'weight':(hidden,dim),'bias':(hidden,)},
                 'llm2vae':{'weight':(dim,hidden),'bias':(dim,)}}
    if set(checkpoint['io'])!=set(expected_io):raise ValueError('Unexpected NAR IO keys.')
    for name,shapes in expected_io.items():
        values=checkpoint['io'][name]
        if set(values)!=set(shapes):raise ValueError('Unexpected projection keys.')
        for key,shape in shapes.items():
            if tuple(values[key].shape)!=shape or not torch.isfinite(values[key]).all():
                raise ValueError('NAR IO projection mismatch.')
    return len(tensors)


def preflight():
    import scipy
    import torchaudio
    import transformers
    from transformers import AutoConfig, AutoModel, AutoFeatureExtractor
    folder=ROOT/'models/artist-encoder-v4'
    old=torch.get_num_threads();torch.set_num_threads(4)
    try:
        head=load_head(folder)
        with torch.inference_mode():
            result=head(torch.zeros(1,8,1024))
        if result.shape!=(1,8,32768) or not torch.isfinite(result).all():
            raise ValueError('Encoder CPU smoke check failed.')
        count=check_nar(load_checkpoint(folder,'nar_lora_joint_v4.pt'),
                        json.loads((ROOT/'models/YuE2-3B/config.json').read_text()))
        mert_path=ROOT/'models/MERT-v2-FullSong'
        cfg=AutoConfig.from_pretrained(mert_path,local_files_only=True,trust_remote_code=True)
        processor=AutoFeatureExtractor.from_pretrained(mert_path,local_files_only=True)
        # Resolve/import local MERT code and verify shapes without loading 1+ GB
        # of weights or executing its audio forward on any device.
        with torch.device('meta'):
            mert=AutoModel.from_config(cfg,trust_remote_code=True)
        from safetensors import safe_open
        with safe_open(str(mert_path/'model.safetensors'),framework='pt',device='cpu') as handle:
            expected=mert.state_dict()
            if set(handle.keys())!=set(expected):raise ValueError('MERT weight keys mismatch.')
            for name,value in expected.items():
                if tuple(handle.get_slice(name).get_shape())!=tuple(value.shape):
                    raise ValueError('MERT tensor shape mismatch: '+name)
        if cfg.hidden_size!=1024 or cfg.num_hidden_layers<=20 or processor.sampling_rate!=24000:
            raise ValueError('MERT feature configuration mismatch.')
        return dict(status='cpu_ready_gpu_unverified',repo=REPO,revision=REVISION,sha256=HASHES,
                    torch=torch.__version__,torchaudio=torchaudio.__version__,scipy=scipy.__version__,
                    transformers=transformers.__version__,encoder_cpu_forward='passed',nar_tensors=count,
                    mert_structure='passed',feature_hidden_state_index=20,
                    note='Matches upstream hidden_states[20] literally (21st block in local MERT). No GPU work, real-audio encoding, or reconstruction has run.')
    finally:
        torch.set_num_threads(old)
