"""Experimental text-conditioned acoustic LoRA training, in the Studio GPU queue.

No semantic-token supervision or AR training. Source audio and base weights are
read-only. This uses the local engine's velocity forward with gradients enabled.
"""
from __future__ import annotations

import gc
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import numpy as np
import soundfile as sf
import torch
from torch import nn
from torch.utils.checkpoint import checkpoint
from safetensors.torch import save_file, load_file

from .settings import ROOT
from .jobs import write_json
from .trainer import validate_sources

CACHE_VERSION = 'yue2-mean-48k-stereo-context2-v1'


class Cancelled(Exception):
    pass


def check_cancel(directory):
    if (directory/'cancel.request').exists():
        raise Cancelled()


def digest(path, directory=None):
    value = hashlib.sha256()
    with Path(path).open('rb') as handle:
        while block := handle.read(8*1024*1024):
            if directory is not None:
                check_cancel(directory)
            value.update(block)
    return value.hexdigest()


def model_identity(folder, directory):
    folder = Path(folder)
    files = sorted(set(folder.glob('*.safetensors')) | set(folder.glob('*.json')) | set(folder.glob('*.tiktoken')))
    return {p.name:digest(p,directory) for p in files}


class TrainLinear(nn.Module):
    def __init__(self, base, rank):
        super().__init__()
        self.base = base
        # Optimizer/master adapter weights remain FP32, including on BF16 CUDA.
        self.down = nn.Parameter(torch.empty(rank,base.in_features,device=base.weight.device,dtype=torch.float32))
        self.up = nn.Parameter(torch.zeros(base.out_features,rank,device=base.weight.device,dtype=torch.float32))
        nn.init.kaiming_uniform_(self.down,a=math.sqrt(5))

    def forward(self, x):
        delta = torch.nn.functional.linear(torch.nn.functional.linear(x.float(),self.down),self.up)
        return self.base(x) + delta.to(x.dtype)


def install_adapters(model, rank, checkpoint_layers=True):
    model.eval().requires_grad_(False)
    adapters = {}
    for name, module in list(model.named_modules()):
        if type(module) is nn.Linear and re.fullmatch(r'model\.layers\.\d+\.nar_self_attn\.(q|k|v|o)_proj',name):
            parent, key = name.rsplit('.',1)
            adapter = TrainLinear(module,rank)
            setattr(model.get_submodule(parent),key,adapter)
            adapters[name] = adapter
    if not adapters:
        raise ValueError('No supported NAR attention layers found in this model.')
    if checkpoint_layers:
        for layer in model.model.layers:
            original = layer.forward
            # Bind each layer independently; non-reentrant supports frozen inputs.
            def forward(*args, _original=original, **kwargs):
                return checkpoint(_original,*args,use_reentrant=False,**kwargs)
            layer.forward = forward
    return adapters


def export_adapter(adapters, path, metadata):
    state = {}
    for name, module in adapters.items():
        state[name+'.lora_down.weight'] = module.down.detach().cpu().contiguous()
        state[name+'.lora_up.weight'] = module.up.detach().cpu().contiguous()
    if not all(torch.isfinite(value).all() for value in state.values()):
        raise ValueError('Refusing to save non-finite adapter weights.')
    temporary = path.with_suffix('.tmp')
    save_file(state,str(temporary),metadata={**metadata,'format':'yue2-lora-v1'})
    temporary.replace(path)


def sequence(prefix, frames, device, latent_ids=None):
    from yue2.protocol import LATENT_START, LATENT_PAD, LATENT_END
    start,pad,end = latent_ids or (LATENT_START,LATENT_PAD,LATENT_END)
    tokens = torch.tensor([prefix+[start]+[pad]*frames+[end]],device=device)
    ar = torch.arange(tokens.shape[1],device=device)[None,:] < len(prefix)
    content = ~ar.clone()
    content[:,len(prefix)] = False
    content[:,-1] = False
    return tokens,ar,~ar,content


def training_loss(model, seq, clean, raw_t=None, noise=None):
    raw_t = torch.randn(()).item() if raw_t is None else raw_t
    noise = torch.randn_like(clean) if noise is None else noise
    # Use the same sigmoid + shift for both interpolation and conditioning.
    t = model._shift_t_value(raw_t,clean.device,torch.float32)
    noisy = (1-t)*clean + t*noise
    velocity = type(model).nar_velocity.__wrapped__(model,*seq,noisy,raw_t)
    return torch.nn.functional.mse_loss(velocity.float(),(noise-clean).float())


def audio_clip(path, start, duration):
    """Read a bounded segment; ffmpeg handles resampling/multichannel downmix."""
    info = sf.info(path)
    if info.samplerate==48000 and info.channels in (1,2):
        with sf.SoundFile(path) as handle:
            handle.seek(round(start*48000))
            data = handle.read(round(duration*48000),dtype='float32',always_2d=True)
        if data.shape[1]==1:
            data = np.repeat(data,2,axis=1)
    else:
        executable = shutil.which('ffmpeg')
        if not executable:
            raise ValueError('Install ffmpeg or provide 48 kHz mono/stereo WAV/FLAC audio for training.')
        result = subprocess.run([executable,'-nostdin','-v','error','-ss',str(start),'-i',str(path),
                                 '-t',str(duration),'-vn','-ar','48000','-ac','2','-f','f32le','pipe:1'],
                                capture_output=True,timeout=120,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        if result.returncode:
            raise ValueError('Audio conversion failed: '+result.stderr.decode('utf-8','replace')[-1500:])
        data = np.frombuffer(result.stdout,dtype='<f4').reshape(-1,2).copy()
    if not len(data) or not np.isfinite(data).all():
        raise ValueError('Audio is empty or contains non-finite samples: '+str(path))
    return torch.from_numpy(data.T.copy())[None]


def cache_audio(spec, directory, device, vae_identity):
    from yue2.modeling_vae import YuE2VAE
    project = spec['project']
    rows = validate_sources(project)
    clip = project['clip_seconds']
    frames = round(clip*25)
    if abs(frames/25-clip)>1e-6:
        raise ValueError('Clip length must align to the 25 Hz latent frame grid (use whole seconds).')
    root = ROOT/'training'/'cache'
    root.mkdir(parents=True,exist_ok=True)
    total = sum(row['clips'] for row in rows)
    paths, sources, vae = [], {}, None
    print(f'[YuE2] Starting Audio cache: 0/{total} items',flush=True)
    for row in rows:
        check_cancel(directory)
        source = Path(project['folder'])/row['name']
        source_hash = digest(source,directory)
        sources[row['name']] = source_hash
        identity = dict(version=CACHE_VERSION,source=source_hash,vae=vae_identity,clip=clip)
        key = hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
        folder = root/key
        folder.mkdir(exist_ok=True)
        for index in range(row['clips']):
            check_cancel(directory)
            target = folder/f'{index:05d}.safetensors'
            valid = False
            if target.is_file():
                try:
                    cached = load_file(str(target))['latent']
                    valid = tuple(cached.shape)==(frames,64) and bool(torch.isfinite(cached).all())
                except Exception:
                    valid = False
            if not valid:
                if vae is None:
                    print('Loading the full audio VAE for encoding (not the semantic tokenizer).',flush=True)
                    vae = YuE2VAE.from_pretrained(spec['vae'],local_files_only=True,device=device)
                    # Encoding does not need decoder GPU memory.
                    vae.decoder.to('cpu')
                begin = index*clip
                context_start = max(0,begin-2)
                duration = min(row['seconds'],begin+clip+2)-context_start
                audio = audio_clip(source,context_start,duration)
                with torch.inference_mode():
                    encoded = vae.encode(audio)
                offset = round((begin-context_start)*25)
                latent = encoded[0,:,offset:offset+frames].T.contiguous().cpu()
                if tuple(latent.shape)!=(frames,64) or not torch.isfinite(latent).all():
                    raise ValueError('VAE returned invalid or too-short latents for '+row['name'])
                temporary = target.with_suffix('.tmp')
                save_file({'latent':latent},str(temporary),metadata={'cache_version':CACHE_VERSION,'source_sha256':source_hash})
                temporary.replace(target)
                del encoded, audio, latent
            paths.append(target)
            print(f'[YuE2] Running Audio cache: {len(paths)}/{total} items · {row["name"]}',flush=True)
        if digest(source,directory)!=source_hash:
            raise ValueError('A source song changed during encoding; save a fresh dataset setup.')
    del vae
    gc.collect()
    if device.type=='cuda':
        torch.cuda.empty_cache()
    write_json(directory/'result'/'dataset.json',dict(sources=sources,vae=vae_identity,cache_version=CACHE_VERSION,clips=len(paths)))
    print(f'[YuE2] Completed Audio cache: {total}/{total} items',flush=True)
    return paths


def run(spec, directory):
    from yue2.modeling_yue2 import YuE2ForCausalLM
    from yue2.tokenization_yue2 import YuE2TextTokenizer
    from yue2.protocol import SongRequest, token_prefixes, MUSIC_END
    result = directory/'result'
    result.mkdir(exist_ok=True)
    check_cancel(directory)
    if not torch.cuda.is_available() or not torch.cuda.is_bf16_supported():
        raise ValueError('This experimental trainer requires a BF16-capable NVIDIA GPU. No CPU fallback or quantization is applied.')
    device = torch.device('cuda:0')
    torch.manual_seed(42)
    print('[YuE2] Starting Training preparation: hashing local model files',flush=True)
    vae_identity = model_identity(spec['vae'],directory)
    base_identity = model_identity(spec['model'],directory)
    write_json(result/'model_identity.json',dict(model=base_identity,vae=vae_identity))
    paths = cache_audio(spec,directory,device,vae_identity)
    check_cancel(directory)
    model = YuE2ForCausalLM.from_pretrained(spec['model'],local_files_only=True,dtype=torch.bfloat16).to(device)
    controls, project = spec['controls'], spec['project']
    tokenizer = YuE2TextTokenizer(Path(spec['model'])/'qwen.tiktoken')
    prefix = token_prefixes(SongRequest(style=project['trigger']+', '+project['default_caption'],lyrics='',cot='off',seed=42),tokenizer)+[MUSIC_END]
    frames = round(project['clip_seconds']*25)
    if len(prefix)+frames+2>model.config.max_position_embeddings or frames+2>model.config.max_latent_frames:
        raise ValueError('The shared style or clip is too long for this model. Shorten it and save a new setup.')
    # Cold-cache VAE construction consumes RNG; it must not change training's
    # adapter initialization, shuffle order, timesteps, or noise draws.
    torch.manual_seed(42)
    adapters = install_adapters(model,controls['rank'])
    parameters = [p for adapter in adapters.values() for p in (adapter.down,adapter.up)]
    optimizer = torch.optim.AdamW(parameters,lr=controls['learning_rate'],weight_decay=0.01)
    seq = sequence(prefix,frames,device)
    metadata = {'trigger_word':project['trigger'],'base_model':spec['model'],
                'base_sha256':hashlib.sha256(json.dumps(base_identity,sort_keys=True).encode()).hexdigest(),
                'project_id':project['id'],'alpha':str(controls['rank']), 'rank':str(controls['rank']),
                'conditioning':'text-only-cot-off','targets':'nar-attention','seed':'42'}
    steps = controls['steps']
    last_step, last_loss = 0, None
    order = []
    print(f'[YuE2] Completed Training preparation: {sum(p.numel() for p in parameters)} trainable parameters',flush=True)
    print(f'[YuE2] Starting LoRA training: 0/{steps} steps',flush=True)
    try:
        for step in range(1,steps+1):
            check_cancel(directory)
            if not order:
                order = torch.randperm(len(paths)).tolist()
            clean = load_file(str(paths[order.pop()]))['latent'].to(device).clone()
            warmup = max(1,min(20,steps//10))
            factor = min(1.,step/warmup) * (0.1+0.9*0.5*(1+math.cos(math.pi*(step-1)/steps)))
            optimizer.param_groups[0]['lr'] = controls['learning_rate']*factor
            optimizer.zero_grad(set_to_none=True)
            loss = training_loss(model,seq,clean)
            if not torch.isfinite(loss):
                raise ValueError('Non-finite training loss. Earlier checkpoints are retained; try a lower learning rate.')
            loss.backward()
            torch.nn.utils.clip_grad_norm_(parameters,1.,error_if_nonfinite=True)
            optimizer.step()
            last_step, last_loss = step, loss.item()
            print(f'[YuE2] Running LoRA training: {step}/{steps} steps · loss {last_loss:.6f}',flush=True)
            if step % controls['checkpoint_every']==0:
                export_adapter(adapters,result/f'step-{step:06d}.safetensors',{**metadata,'step':str(step)})
        check_cancel(directory)
    except Cancelled:
        if last_step:
            export_adapter(adapters,result/f'stopped-{last_step:06d}.safetensors',{**metadata,'step':str(last_step)})
        write_json(result/'training.json',dict(status='cancelled',steps=last_step,loss=last_loss))
        raise
    final = result/'final.safetensors'
    export_adapter(adapters,final,{**metadata,'step':str(last_step)})
    # Validate the same public format consumed by the creation-area selector.
    from yue2.lora import AcousticLoRA
    AcousticLoRA.read(final)
    destination = ROOT/'models'/'loras'
    destination.mkdir(parents=True,exist_ok=True)
    slug = re.sub(r'[^a-zA-Z0-9_-]+','-',project['name']).strip('-')[:60] or 'style'
    installed = destination/f'{slug}-{directory.name}.safetensors'
    if installed.exists():
        raise ValueError('An adapter already exists for this run; it will not be overwritten.')
    temporary = installed.with_suffix('.tmp')
    shutil.copyfile(final,temporary)
    temporary.replace(installed)
    write_json(result/'training.json',dict(status='complete',steps=last_step,loss=last_loss,
               installed_lora=str(installed),sha256=digest(installed),controls=controls,
               note='Experimental acoustic adapter. Loss is not a listening-quality or singer-similarity score.'))
    print(f'[YuE2] Completed LoRA training: {steps}/{steps} steps · saved {installed}',flush=True)


def main():
    path = Path(sys.argv[1]).resolve()
    try:
        run(json.loads(path.read_text(encoding='utf-8')),path.parent)
    except Cancelled:
        print('[YuE2] Cancelled LoRA training: stopped at a safe boundary; completed checkpoints retained',flush=True)


if __name__=='__main__':
    main()
