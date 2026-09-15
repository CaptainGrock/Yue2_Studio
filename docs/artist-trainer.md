# Artist Trainer and playback — experimental

Artist trainer appears below Style trainer. See [setup](artist-setup.md) for the
separate runtime, verified model paths and explicit setup/download actions.
Use full matching lyrics and a shared style, review the scan, and save a setup.
Training uses the saved selection, requires explicit GPU confirmation and runs
in Studio's serial queue. Model and runtime paths are frozen for that job.

Completed Artist runs appear in **Style / Artist LoRA**, including Surprise me.
Selecting an adapter offers its embedded training style in both creation style
boxes; existing text requires confirmation. You can edit the result. Surprise me
can lock that style while the LLM writes new titles and lyrics.

Artist playback requires **No score**, **Torch/Torch-eager**, **quantization None**
and **AR offloading disabled**. Incompatible settings fail rather than silently
changing backend or generation mode. GGUF is unsupported. Only one Style adapter
or Artist bundle can be selected; arbitrary LoRA stacking is not supported.

An Artist bundle contains its AR safetensors adapter, sibling `manifest.json`,
and the exact pinned community NAR companion referenced by that manifest. Keep
these together when transferring a bundle. Relative companion paths resolve from
the manifest folder; absolute paths refer to that PC. A standalone safetensors file
without its manifest/companion is insufficient. Checkpoints can be selected via
the local-path control while retaining the same sibling manifest.

The queue freezes adapter, companion and base-model identities. Playback checks
those identities against the actual files before generating. Artist deltas apply
to semantic generation and acoustic-prefix conditioning; the companion applies
to acoustic synthesis. Every modified weight is restored after each stage,
including failure/cancellation paths. No encoder/MERT is needed merely to play an
already trained bundle; the base YuE2 model, VAE and companion are needed.

Strength scales the Artist AR delta. At any nonzero strength, the companion stays
at its trained full strength. Zero disables both; it is not an AR-only comparison
with an unchanged companion. None selects original YuE2. Increased strength or
longer training is not a guarantee of singer similarity or better music.

The installer accepts stock upstream 0.1.6 and the known merged Style Trainer
pipeline, backs up replaced files, and refuses unfamiliar pipeline or adapter
code. It does not download models or install Artist dependencies automatically.

Release status: CPU/mocked integration checks only until the isolated packaged
build completes fresh runtime/download tests and separately approved GPU testing.
Earlier local training results are not proof of fresh-install compatibility.
