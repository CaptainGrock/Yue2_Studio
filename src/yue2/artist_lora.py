"""Artist AR adapter plus pinned community NAR decoder dialect.

All merges are temporary. The companion stays at its trained strength whenever
the artist bundle is enabled; strength zero disables the whole bundle.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import io
import json
from pathlib import Path
import re
import torch
from safetensors.torch import load
from .lora import AcousticLoRA,validate_strength


@dataclass(frozen=True)
class ArtistLoRA(AcousticLoRA):
    companion: dict
    companion_path: str
    base_identity: dict

    @classmethod
    def read(cls,path):
        from yue2_studio.artist_encoder import HASHES,REVISION
        path=Path(path).resolve()
        if path.suffix.lower()!='.safetensors':raise ValueError('Artist LoRA must be safetensors.')
        raw=path.read_bytes();tensors=load(raw)
        metadata=json.loads(raw[8:8+int.from_bytes(raw[:8],'little')]).get('__metadata__',{})
        if metadata.get('format')!='yue2-artist-ar-v1' or metadata.get('scale')!='1':raise ValueError('Unsupported Artist LoRA format/scale.')
        if metadata.get('encoder_revision')!=REVISION or metadata.get('companion_sha256')!=HASHES['nar_lora_joint_v4.pt']:
            raise ValueError('Unsupported Artist LoRA companion identity.')
        manifest=json.loads((path.parent/'manifest.json').read_text(encoding='utf-8'))
        companion_path=Path(manifest['companion']['path'])
        if not companion_path.is_absolute():companion_path=path.parent/companion_path
        companion_path=companion_path.resolve()
        companion_bytes=companion_path.read_bytes()
        if hashlib.sha256(companion_bytes).hexdigest()!=metadata['companion_sha256']:
            raise ValueError('Artist companion file changed or is incompatible.')
        companion=torch.load(io.BytesIO(companion_bytes),map_location='cpu',weights_only=True)
        groups=[];used=set()
        for key in sorted(tensors):
            if not key.endswith('.lora_down.weight'):continue
            name=key[:-len('.lora_down.weight')];up_key=name+'.lora_up.weight'
            if not re.fullmatch(r'model\.layers\.\d+\.(self_attn\.(q|k|v|o)_proj|mlp\.(gate|up|down)_proj)',name):
                raise ValueError('Unsupported Artist AR target: '+name)
            down=tensors[key];up=tensors.get(up_key)
            if up is None or down.ndim!=2 or up.ndim!=2 or min(*down.shape,*up.shape)<1 or down.shape[0]!=up.shape[1]:raise ValueError('Invalid Artist LoRA matrices.')
            if any(not x.is_floating_point() or not torch.isfinite(x).all() for x in (down,up)):raise ValueError('Non-finite Artist LoRA matrices.')
            groups.append(((name,),down.float(),up.float(),1.));used.update((key,up_key))
        if not groups or used!=set(tensors):raise ValueError('Incomplete Artist adapter.')
        return cls(str(path),hashlib.sha256(raw).hexdigest(),metadata,tuple(groups),companion,str(companion_path),manifest['base'])

    def info(self,strength):
        return {**super().info(strength),'kind':'artist','companion_path':self.companion_path,
                'companion_sha256':self.metadata['companion_sha256'],'base_identity':self.base_identity,
                'conditioning':'cot-off','companion_strength':1. if strength!=0 else 0.,
                'base_model':self.metadata.get('base_model')}

    def validate_model(self,model):
        from yue2_studio.artist_encoder import check_nar
        super().validate_model(model)
        expected={f'model.layers.{i}.{branch}.{projection}' for i in range(model.config.num_hidden_layers)
                  for branch,projections in [('self_attn',('q_proj','k_proj','v_proj','o_proj')),('mlp',('gate_proj','up_proj','down_proj'))]
                  for projection in projections}
        if {names[0] for names,_,_,_ in self.groups}!=expected:raise ValueError('Artist adapter must cover every AR projection.')
        check_nar(self.companion,model.config.to_dict())

    @contextmanager
    def synthesis_applied(self,model,strength):
        from yue2_studio.artist_encoder import apply_companion
        strength=validate_strength(strength);self.validate_model(model)
        originals=[]
        try:
            with self.applied(model,strength):
                if strength!=0:
                    # Save all companion targets before any write, including full
                    # input/output projections (not just attention LoRA tensors).
                    for name,value in model.named_parameters():
                        if '.nar_self_attn.' in name or '.nar_mlp.' in name or name.startswith(('vae2llm.','llm2vae.')):
                            originals.append((value,value.detach().to('cpu',copy=True)))
                    apply_companion(model,self.companion)
                    if not all(torch.isfinite(value).all() for value,_ in originals):raise ValueError('Non-finite merged Artist companion weights.')
                yield
        finally:
            with torch.no_grad():
                for value,original in reversed(originals):value.copy_(original)


def read_adapter(path):
    from safetensors import safe_open
    with safe_open(str(path),framework='pt') as handle:kind=(handle.metadata() or {}).get('format')
    return ArtistLoRA.read(path) if kind=='yue2-artist-ar-v1' else AcousticLoRA.read(path)
