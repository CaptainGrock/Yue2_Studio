# Artist setup preparation (integration in progress)

This is the setup layer for the upcoming Artist Trainer, not a finished release.
The Artist panel, setup actions and training worker now use the new registry
paths. Playback integration and installer support are implemented and tested on
CPU in isolated installs. Real isolated runtime installation passed; visual and GPU tests
remain release gates. This is not yet a fully validated Artist release.

## Artist panel and queue

Artist trainer sits below Style trainer. Enter/reuse model folders, then queue
Check setup, Prepare model paths / download missing, or Install separate Artist
runtime. The download action requires acceptance of model terms and confirmation;
the runtime action requires confirmation. Checks are read-only. Preparing model
paths records them only after verification, even when all files already exist.
Setup runs in the shared serial queue, with results/errors in Library → Open run.

Scan matching audio and full lyric files, review the lyrics, enter a shared style
and trigger, and save a versioned setup. Source files are not changed. Training
requires a saved setup, at least two 30–360 second recordings and explicit GPU
approval. The last selected song is held out; controls default to 800 updates,
rank 64, learning rate 0.0001, checkpoint interval 200 and alignment weight 0.08.
Alignment's first use may download Demucs/MMS weights; zero alignment weight
skips separation/alignment but not lyric conditioning. No silent clipping occurs.

The queue freezes verified model paths and the registered runtime path into the
job; the worker rechecks pinned assets before GPU work. New checkpoints embed the
shared training style. Cancellation waits for a safe training boundary and retains
completed adapter snapshots, not optimizer-resume state. Setup cancellation uses
the existing process-tree termination path; partial downloads/environments remain
for diagnosis rather than replacing a previous successful setup.

## Explicit actions

Run with the installed Studio's Python 3.12 interpreter and installed source on
the import path. `YUE2_KIT` must identify that installation, not the add-on repo.

```
python -m yue2_studio.artist_setup check
python -m yue2_studio.artist_setup download-models --confirm --accept-model-terms
python -m yue2_studio.artist_setup install-runtime --confirm
```

`check` reads files and hashes and probes an already registered runtime with
CUDA hidden and Hugging Face offline. It installs nothing, downloads nothing,
and returns nonzero when setup is incomplete. Hashing large local weights takes
time and disk bandwidth. Its success is not a GPU-memory or musical-quality test.

Model paths can be supplied using `--model`, `--vae`, `--mert`, `--encoder` and
`--regularizer`. Existing local model folders and the Style Trainer's downloaded
model/VAE registry are reused. Only the tested, hash-pinned releases are accepted.
An existing invalid folder fails validation; it is not overwritten automatically.

Missing assets download to `models/artist-cache/<kind>/<revision>` using ordinary
files, not symlinks. Exact-file requests avoid snapshot progress-library failures.
Transfers include explicit support/license files, not the
community's training scripts or entire audio corpus. The five paths publish to
`training/artist-models.json` only after every required file passes validation.
Failed downloads retain partial cache files and leave an older registry intact.
Allow substantial disk space: full base/VAE/MERT weights plus the encoder,
companion and reference pack, and later caches and runtime dependencies.

The runtime action creates a fresh `.artist-runtimes/<unique-id>` environment,
installs pinned Torch/torchaudio 2.10.0 CUDA 13.0 and supporting packages, checks
dependency consistency and CPU imports, then writes `training/artist-runtime.json`.
It does not upgrade the base Studio environment or `.venv-artist`. A source-only
`.pth` reference makes installed YuE2/Studio code available without sharing the
base environment's site-packages. Failed attempts remain available for diagnosis;
no old runtime is removed or replaced. This uses more disk space than sharing
Torch. A working Python 3.12 venv/pip installation and network access are required.

The known Demucs dependencies are installed explicitly before Demucs itself
(`--no-deps`), followed by `pip check`; this preserves the selected Torch pair.
Demucs/MMS alignment model downloads and GPU alignment tests are still separate
release work. Passing the import probe does not establish alignment readiness.

Package commands use pip's system-certificate trust-store support and ignore
unrelated global index/trusted-host settings. TLS verification stays enabled.
Package failures retain the underlying command output in the setup log.

## Model sources and terms

Review the model cards/licenses before confirming downloads:

- [Official YuE2 model](https://huggingface.co/m-a-p/YuE2-3B)
- [Official VAE](https://huggingface.co/m-a-p/YuE2-Vae)
- [Official full-song MERT](https://huggingface.co/m-a-p/MERT-v2-FullSong)
- [Community encoder and NAR companion](https://huggingface.co/Mothersuperior/yue2-mothersuperior-realaudio-tokenizer-v4)
- [Community reference pack](https://huggingface.co/datasets/Mothersuperior/yue2-minted-corpus)

Exact revisions and SHA256 values are recorded in `artist_setup.ASSETS`. The
community release's model card includes noncommercial terms; do not assume the
Studio code license grants rights to model weights or training recordings.
No weights, training recordings or personal run artifacts are distributed here.

MERT requires its two pinned architecture files at training time. Setup verifies
their SHA256 without executing them. The community scripts are not executed.

## Validation status

CPU tests cover explicit confirmation, local reuse, pinned transfer requests,
hash rejection, fresh runtime commands, and failure-safe registry publication.
Those unit tests mock transfers and pip commands. The full suite passes 149 tests
plus 28 subtests, alongside the Artist/Style/LoRA/Surprise UI-handler checks.
Real isolated setup tests downloaded and hash-verified the pinned encoder,
companion and reference pack, reusing verified base/VAE/MERT folders read-only.
The downloaded encoder and companion also loaded on CPU. This is not a cold
download test of all five model groups.

Real dependency checks found and fixed Windows certificate handling, including
nested pip build processes, without disabling TLS verification. The supporting
packages, Demucs, dependency consistency check and CPU imports passed, followed
by a successful complete fresh runtime installation with the corrected installer.
The fresh runtime also imported the installed Artist preparation/training modules
with CUDA uninitialized. Visual review and GPU training/alignment/playback remain
separate release gates; passing CPU imports does not establish musical quality.
The isolated Studio's real setup queue also completed `check`, with all files and
imports ready and a saved result receipt. No training was started.
