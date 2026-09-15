"""CPU-only helpers; no actual encoder downloads or GPU jobs in this suite."""
import numpy as np
import pytest
import torch
from yue2_studio.artist_encoder import normalize_features,window_ranges,check_nar


@pytest.mark.parametrize('frames',[1,8,511,512,513,750,1024,1025,9000])
def test_window_coverage(frames):
    covered=np.zeros(frames,dtype=bool)
    for start,length,lo,hi in window_ranges(frames):
        assert start<=lo<hi<=start+length<=frames
        assert 1<=length<=512
        covered[lo:hi]=True
    assert covered.all()


def test_feature_normalization():
    x=np.random.default_rng(1).normal(size=(16,1024))
    y=normalize_features(x)
    np.testing.assert_allclose(y.mean(0),0,atol=1e-6)
    assert np.isfinite(normalize_features(np.zeros((2,1024)))).all()
    for bad in (np.zeros((0,1024)),np.zeros((5,32)),np.full((2,1024),np.nan)):
        with pytest.raises(ValueError):normalize_features(bad)


def test_nar_shapes_and_finiteness():
    config=dict(hidden_size=8,intermediate_size=16,num_attention_heads=2,num_key_value_heads=1,
                head_dim=4,num_hidden_layers=1,latent_dim=2)
    tensors=[]
    for out_size,in_size in [(8,8),(4,8),(4,8),(8,8),(16,8),(16,8),(8,16)]:
        tensors.extend([torch.zeros(32,in_size),torch.zeros(out_size,32)])
    checkpoint={'rank':32,'lora':tensors,'io':{'vae2llm':{'weight':torch.zeros(8,2),'bias':torch.zeros(8)},
                                           'llm2vae':{'weight':torch.zeros(2,8),'bias':torch.zeros(2)}}}
    assert check_nar(checkpoint,config)==14
    checkpoint['lora'][0][0,0]=float('nan')
    with pytest.raises(ValueError):check_nar(checkpoint,config)
