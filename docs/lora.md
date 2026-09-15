# Experimental acoustic LoRA engine

The Python pipeline supports one acoustic adapter at a time. No adapter is
selected by default. The creation page now has a Style LoRA selector, a 0–2
strength slider with a clickable explanation, and an automatic trigger option.
Place YuE2 adapters in `models/loras` and choose Refresh list, or use the local
file path control to select an adapter elsewhere. Use **Style trainer** to create an adapter from your own songs.

Drafts, exported projects, and saved run settings retain the selection. Each
queued song records the adapter SHA-256 and strength. The worker checks that
hash before generating; a changed adapter produces an error rather than silently
using different weights. Retry also checks the original hash. No adapter copy is
embedded in a project or run, so keep the selected file available. Selecting None
does not change previously queued jobs. GGUF cannot use these adapters and the
server rejects that combination. Existing running workers are not reconfigured.

```python
with YuE2Pipeline.from_pretrained(model_path, vae=vae_path) as pipe:
    pipe.load_lora("models/loras/my_style.safetensors", strength=1.0)
    song = pipe(style="my_trigger, soul", lyrics=lyrics)
    pipe.set_lora_strength(0.5)
    softer = pipe(style="my_trigger, soul", lyrics=lyrics)
    pipe.unload_lora()  # Equivalent to pipe.load_lora(None).
    original = pipe(style="soul", lyrics=lyrics)
```

Supported files are compatible `comfyui-native-lora` safetensors
exports and the Studio trainer's `yue2-lora-v1` acoustic format. Native fused QKV and gate/up
matrices are split by the loaded model's actual dimensions; per-module alpha is
honored. Only NAR attention/MLP and audio/time projections are accepted. Unknown,
unpaired, non-finite, or incompatible tensors fail with an error. This API is for
the Python YuE2 pipeline; it does not add an audio.cpp/GGUF adapter loader.

Selection reads and hashes the adapter on CPU without loading the base model.
Shape validation occurs immediately if the model is loaded, or before synthesis
otherwise. Shape compatibility does not prove the adapter used the same base
checkpoint; the reported base-model field is the trainer's supplied metadata.
`pipe.lora_info` returns the path, SHA-256, strength, and trigger/base metadata.
Generated song configuration includes this information. Trigger text must be
included explicitly in the prompt; the engine does not rewrite prompts.

During synthesis, updates are calculated in CPU FP32 and copied into the existing
acoustic weights. Exact originals are retained in CPU memory and restored after
synthesis, including errors or cancellation. Strength zero skips weight changes;
unloading clears the selection. Repeated use does not accumulate rounding drift.
This costs additional system RAM roughly equal to the targeted base weights plus
temporary merge matrices, and adds CPU merge/transfer time to each synthesis.
Base checkpoint files and AR composer weights are never modified.

Public generation stages hold an exclusive pipeline lock. Other threads receive
a busy error, and callbacks cannot change the adapter or close the pipeline.
Studio captures the selection separately for each queued job.
Closing releases the selected adapter. `save_pretrained` exports base model files,
not a merged LoRA; keep adapter files separately.

CPU tests exercise native fused mapping, actual acoustic synthesis, scaling,
bit-exact BF16 restoration, malformed input, failure rollback, and busy-state
protection. GPU/audio quality testing with a trained adapter remains a separate
validation step.
# Surprise me

**Keep this style unchanged** defaults on when selecting a LoRA. Supply your
training style in Style direction: the renderer uses that text instead of the
LLM's generated style, while new titles and lyrics are still written. Automatic
trigger insertion may add the adapter's trigger phrase. Locked style takes
precedence over vocal-gender wording; Instrumental still removes sung lyrics.
An empty locked style is rejected. Uncheck to experiment with varied styles.
The choice is saved in projects/drafts and frozen per batch. Updating an already
running Studio requires a restart after its jobs finish to enable this backend
feature; the UI blocks locked batches on an older running backend.

The Surprise me panel has a LoRA dropdown and Refresh list action. It shares the
creation-area selection, strength, and automatic-trigger setting; every song in
a new batch uses that saved selection. Choose None for the original model.
Queued/running jobs retain their saved settings. Torch is required; selecting a
LoRA does not switch away from GGUF automatically.
