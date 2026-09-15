"""CPU math-SDPA regression for the long-song backward OOM fix."""
import copy
import pytest
import torch
from torch.nn import functional as F
from torch.nn.attention import sdpa_kernel,SDPBackend
from torch.utils.checkpoint import checkpoint
from yue2_studio import artist_ar as ar


@pytest.mark.parametrize('heads,kv_heads',[(4,4),(4,2)])
@pytest.mark.parametrize('tile_size',[1,3,8,30])
def test_tiled_outputs_and_all_gradients_match_full_causal(heads,kv_heads,tile_size):
    torch.set_num_threads(1);torch.manual_seed(19)
    source=[torch.randn(11,h,8,dtype=torch.float64) for h in (heads,kv_heads,kv_heads)]
    dense=[x.clone().requires_grad_() for x in source]
    tiled=[x.clone().requires_grad_() for x in source]
    weights=torch.randn(11,heads,8,dtype=torch.float64)
    with sdpa_kernel(SDPBackend.MATH):
        full=F.scaled_dot_product_attention(*(x.transpose(0,1)[None] for x in dense),is_causal=True,enable_gqa=heads!=kv_heads)[0].transpose(0,1)
        (full*weights).sum().backward()
        # Include the outer decoder-layer checkpoint: the production path nests
        # per-tile checkpoints inside each layer checkpoint.
        small=checkpoint(lambda *xs:ar.training_attention(*xs,query_chunk_size=tile_size),*tiled,use_reentrant=False)
        (small*weights).sum().backward()
    torch.testing.assert_close(small,full,rtol=1e-10,atol=1e-10)
    for original,actual in zip(dense,tiled):torch.testing.assert_close(actual.grad,original.grad,rtol=1e-10,atol=1e-10)


def test_backward_recomputes_only_bounded_tiles(monkeypatch):
    calls=[];original=F.scaled_dot_product_attention
    def observed(query,key,value,**kwargs):
        calls.append((query.shape[-2],key.shape[-2]))
        return original(query,key,value,**kwargs)
    monkeypatch.setattr(F,'scaled_dot_product_attention',observed)
    tensors=[torch.randn(17,h,8,requires_grad=True) for h in (4,2,2)]
    with sdpa_kernel(SDPBackend.MATH):
        result=ar.training_attention(*tensors,query_chunk_size=4)
        forward_calls=len(calls);result.square().sum().backward()
    assert forward_calls==5 and len(calls)>forward_calls
    assert all(q<=4 for q,k in calls)
    assert max(k for q,k in calls)==17  # Full context, not a sliding window.
    assert all(torch.isfinite(x.grad).all() for x in tensors)


def test_layer_adapter_gradients_preserved(monkeypatch):
    from yue2.modeling_yue2 import YuE2Config,YuE2ForCausalLM
    torch.manual_seed(42)
    model=YuE2ForCausalLM(YuE2Config(hidden_size=16,intermediate_size=32,num_hidden_layers=2,
        num_attention_heads=4,num_key_value_heads=2,head_dim=4,vocab_size=32,
        max_position_embeddings=128,latent_dim=64,vae_latent_dim=64,max_latent_frames=128))
    ar.install(model,2)
    with torch.no_grad():
        for name,param in model.named_parameters():
            if name.endswith('.up'):param.normal_(0,.01)
    other=copy.deepcopy(model);ids=torch.tensor([[1,2,3,4,5,6,7,8,9]])
    attention=ar.training_attention
    monkeypatch.setattr(ar,'training_attention',lambda *xs:attention(*xs,query_chunk_size=32))
    full=ar.loss(model,ids,3,chunk=3)[0];full.backward()
    monkeypatch.setattr(ar,'training_attention',lambda *xs:attention(*xs,query_chunk_size=2))
    tiled=ar.loss(other,ids,3,chunk=3)[0];tiled.backward()
    torch.testing.assert_close(full,tiled)
    for (name,a),(_,b) in zip(model.named_parameters(),other.named_parameters()):
        if a.requires_grad:torch.testing.assert_close(a.grad,b.grad,rtol=1e-4,atol=1e-6,msg=name)
