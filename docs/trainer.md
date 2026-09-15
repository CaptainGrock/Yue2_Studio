# Style Trainer: experimental acoustic LoRA training

Open **Style trainer** in the main navigation and enter your local folder of songs.
Only use recordings you have permission to use for training. Scanning inspects
files directly in that folder (not subfolders), reads audio headers,
and estimates complete clips. It does not load a music model,
decode entire songs, detect silence/clipping, or judge audio quality.

Write one **shared style** describing the instruments, vocal character, genre,
and production. Every selected song uses that same description. No per-song text
files are read or required. Shared `collection_metadata.json` can suggest a name,
trigger and style description. Review those suggestions before saving.

Exclude songs as needed. Files that cannot be inspected or are shorter than one
clip are disabled. Mono/non-48-kHz recordings are flagged for later conversion;
no audio is converted during preparation. Format support depends on libsndfile;
convert an unsupported recording to WAV before including it.

**Save training setup** validates the selected songs and creates a new JSON
version under `training/projects`. It records the shared style, source
paths, file sizes/timestamps, clip settings and the training goal. Source songs
and sidecars are unchanged. Saved versions can be reopened in the tab; save a new
version to retain changes. Unsaved edits remain only in the current page.

## Train a saved setup

Select a saved project, then choose **Queue training**. This uses that saved
snapshot, not unsaved form changes. Click the information disclosures beside
steps, learning rate, rank and checkpoint interval for tradeoffs. The default
20-step run is a smoke test, not a finished style model. Each optimizer step uses
one clip; batches are shuffled across the dataset. No lyric files are loaded.

Training runs in the same single-worker queue as generation and transcription;
existing Studio jobs finish first. This does not coordinate GPU use by other
applications or separate Studio instances. The worker uses CUDA device 0 and
requires BF16 support, local complete HF-layout YuE2/VAE folders, and ffmpeg
for non-48-kHz or multichannel input. Inference backend/quantization settings
do not apply to this trainer. Model folders come from Models & runtime.

The worker hashes model/audio content, converts bounded audio segments to stereo
48 kHz, and encodes VAE posterior means with up to two seconds of surrounding
context. Complete clips are cached under `training/cache`, keyed by audio hash,
VAE identity, clip length, and preprocessing version. Tails shorter than one
clip are excluded. All selected clips are cached before training starts, even
for a short smoke test. Source recordings and pretrained weights are read-only.

Only NAR acoustic attention q/k/v/o low-rank weights are trainable. The composer,
VAE, MLPs and original projection weights remain frozen. Conditioning uses the
trigger plus shared style, with no score or semantic-codec supervision. The
local engine's velocity forward is reused with gradients enabled; training uses
flow-matching MSE, FP32 adapter/AdamW state, layer checkpointing, gradient clipping,
and a warmup/cosine learning-rate schedule. No guarantee of singer identity,
style isolation, or musical quality is implied by a falling loss.

## Progress and output

Open **Progress / checkpoints** in the trainer to see cache and training progress,
logs, inputs and downloadable artifacts. **Cancel run** is cooperative: it waits
for the current operation/optimizer step, then saves completed updates. Loading
large weights or encoding a segment can delay stopping. Closing Studio allows
only ten seconds before force termination, so the newest unsaved updates may be
lost; previously committed cache/checkpoint files are preserved.

Periodic, stopped and final `.safetensors` adapters live under the run's `result`
folder. They contain LoRA weights, not optimizer/RNG state: exact training resume
is not implemented. Errors retain previously committed checkpoints. Successful
final adapters are also installed with unique names under `models/loras`. Refresh
the creation page's **Style LoRA** list and select the adapter there. Intermediate
checkpoints can be selected by their local file path. New adapters do not alter
existing songs or automatically select themselves for future renders.

`training.json`, `dataset.json`, `model_identity.json`, and the run's `input.json`
record controls, source hashes, model identity and results. A successful smoke
test establishes that the pipeline runs; audition matched generation settings
with and without the adapter before deciding to train longer.

## Installation and readiness

The normal Studio installer includes the trainer and acoustic LoRA engine hooks.
It supports the documented upstream YuE2 commit and refuses to overwrite a custom
pipeline or a different existing LoRA implementation. Backups are retained.
No model weights, example songs, API keys, community encoder, or trained adapters
are distributed in this repository. No extra trainer Python packages are needed
beyond the base YuE2 dependencies.

Click **Check setup** to check model files, dependencies, driver-reported BF16
capability, and conversion requirements for the selected saved project. This does
not allocate GPU memory. It is not a VRAM capacity or quality guarantee.

If full weights are missing, **Download training models** queues an explicit,
CPU-only download of pinned official YuE2-3B and YuE2-Vae snapshots. Approximately
7.8 GB of weights plus small support files are needed; allow additional space for
cache files, audio latents and checkpoints. Downloads use a separate
`models/style-trainer-cache` folder, verify the released weight hashes, and never
execute downloaded Python code. No credentials are sent. Cancel stops the download
worker; Hugging Face may retain partial files for retry. No training starts on
completion. Check setup again, click **Use downloaded model paths**, then check
again. Selecting those paths changes future generation/training settings only.

The downloaded snapshots are pinned to:

- YuE2-3B: `1a96eca688d6ae5d7f0feb88573fec89920fcd19`
- YuE2-Vae: `95535e72a97bc0f09b8ada125d26b4009428c0e8`

Review the [YuE2 model license](https://huggingface.co/m-a-p/YuE2-3B/blob/main/LICENSE)
and [VAE license](https://huggingface.co/m-a-p/YuE2-Vae/blob/main/LICENSE). Weights
are subject to their own CC BY-NC 4.0 terms, not the Studio code license.

Training requires a BF16-capable NVIDIA GPU and full PyTorch weights, not GGUF.
LoRA playback uses the Python engine; **audio.cpp/GGUF is not supported**.
The trainer does not silently switch the creation backend or generation mode.
If FFmpeg is missing, either install it on PATH using your system package manager
or supply already-converted 48 kHz mono/stereo WAV/FLAC. Unsupported audio files
must be converted before scanning. Drivers, CUDA-enabled PyTorch and hardware
remain prerequisites of the base YuE2 installation.

## Verification scope

The PR includes CPU-only tests with tiny synthetic models for training gradients,
frozen base weights, adapter export/import, acoustic synthesis, cancellation,
queue contracts, installer safety and setup checks. These are not singer-similarity
or listening-quality tests. A 20-step smoke test is still recommended on each user\'s
hardware before a longer experiment. Do not interpret a small loss as voice cloning.
