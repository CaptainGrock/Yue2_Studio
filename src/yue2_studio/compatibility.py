"""Resolve optimized execution against the installed Torch build, not OS guesses."""
from functools import lru_cache


@lru_cache(maxsize=1)
def capabilities():
    import torch
    available = torch.backends.cuda.is_flash_attention_available()
    return {'flash_attention': available, 'note': '' if available else
            'This PyTorch build lacks Flash Attention. The torch backend keeps CUDA graphs enabled and selects cuDNN attention when supported (otherwise SDPA). Select torch for fast generation.'}


def compatible_runtime(runtime, flash_attention):
    effective = dict(runtime)
    warning = None
    if runtime['backend']=='torch' and not flash_attention and str(runtime['device']).split(':')[0] not in ('cpu','mps'):
        warning={'requested_backend':'torch','effective_backend':'torch',
                 'reason':'Flash Attention is not compiled. CUDA graphs remain enabled with cuDNN attention when supported, otherwise SDPA.'}
    return effective, warning
