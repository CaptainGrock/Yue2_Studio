# Experimental audio.cpp / GGUF backend

GGUF is a different runtime format, not a file the PyTorch YuE2 loader can open.
Studio invokes a separate **audio.cpp CLI** for each song and converts its WAV into
FLAC for the existing player/library. The original WAV is retained in artifacts.
The same queue and process-tree cancellation apply. Surprise me writes each song
with your chosen LLM, then submits it to the selected engine.

## Status and requirements

The adapter follows audio.cpp dev commit
`fbe3eedbf6c504e45189e2cdcf1b257740a28863` and its
[Yue2 runtime documentation](https://github.com/0xShug0/audio.cpp/blob/fbe3eedbf6c504e45189e2cdcf1b257740a28863/docs/models/yue2.md).
It is experimental. Automated tests verify request mapping, full-range seeds,
Unicode/long lyrics, asset preflight, WAV/FLAC handling and review receipts using
a mocked executable. **Real Q8_0 + F16 CUDA generation was validated locally on
Windows with an RTX 5090 on September 11, 2026**, using the pinned source above.
One short `full` planning request at 32 ODE steps and the normal 9,000 semantic-token
ceiling produced 60.76 seconds of stereo 48 kHz audio in 20.17 seconds including
worker startup and output conversion. Peak sampled **total device memory** was
7,627 MiB, including desktop applications. This is one test, not a speed or memory
guarantee; it does not establish lyric accuracy or musical quality. WAV and FLAC
decoded successfully with finite, non-silent samples. Q4 and other devices remain
untested locally.
The model card describes this dev branch as community testing/validation work.

Studio still requires the original YuE2 environment for its shared protocol,
score tools and audio conversion. This is not yet a standalone C++-only installer.

## 1. Obtain audio.cpp with Yue2 support

Use the [audio.cpp dev branch](https://github.com/0xShug0/audio.cpp/tree/dev).
An older release binary may not contain the Yue2 model family.
Keep runtime DLLs beside the executable as required by its build.

```powershell
git clone --branch dev --recursive https://github.com/0xShug0/audio.cpp.git
cd audio.cpp
# For the source contract used by this adapter:
git checkout fbe3eedbf6c504e45189e2cdcf1b257740a28863
git submodule update --init --recursive
```

Follow the [upstream Windows build prerequisites](https://github.com/0xShug0/audio.cpp/blob/fbe3eedbf6c504e45189e2cdcf1b257740a28863/docs/build/windows.md)
(MSVC C++ Build Tools, CMake/Ninja, and CUDA Toolkit for NVIDIA).
From that checkout, the documented CUDA CLI build is:

```powershell
.\scripts\build_windows.ps1 -Preset windows-cuda-release -Target audiocpp_cli -Jobs 16
```

The documented output is `build/windows-cuda-release/bin/audiocpp_cli.exe`.
For other operating systems/backends, use upstream build instructions. Do not
assume CUDA support simply because the executable exists.

## 2. Download components

From [audio-cpp/Yue2-3B-GGUF](https://huggingface.co/audio-cpp/Yue2-3B-GGUF/tree/main),
put the following under your YuE2 `models/Yue2-3B-GGUF/` folder:

```text
yue2-3b-q8_0.gguf                  # balanced default; or Q4_0/BF16
yue2-vae-f16.gguf                 # or F32
sidecars/
   yue2-model-config.json
   yue2-generation-config.json
   yue2-qwen.tiktoken
   yue2-vae-config.json
```

You need only one main model and one VAE, plus **all four sidecars**. Preserve
filenames. No models, binaries or DLLs are bundled with Studio.
The model card lists Q4_0, Q8_0 and BF16 mains, and F16/F32 VAEs.

## 3. Configure Studio

1. Finish current work, update/install Studio and restart it.
2. In **Models & runtime**, choose inference backend **audio.cpp**.
3. In **audio.cpp / GGUF**, enter the executable and GGUF model-folder paths.
4. Select the main model and VAE files you downloaded; use `cuda` for an NVIDIA
   CUDA build. Leave weight storage at `native` initially.
5. Keep the existing synthesis/sampling controls or adjust them deliberately.
6. Apply settings and create a song. Missing files are rejected before a render
   is queued; Surprise me checks the files before calling its LLM.

### First test

Start with **one normal song**, before trying a Surprise me batch:

- Select Q8_0, F16 decoder, CUDA, and Full planning. Keep 32 synthesis steps and
  default sampling settings.
- Enter a short verse and outro with section tags, plus a simple style such as
  `English, female vocals, acoustic folk, gentle guitar, warm, intimate`.
- Generate and open the queued run. The elapsed-time heartbeat confirms the worker
  is active; native builds may provide little additional log output.
- When it finishes, play the song and compare the sung words with the saved lyrics.
  Check the ending too. **Needs review** is expected for this experimental backend.
- Download the WAV/FLAC and song-details JSON. The run's `result/config.json` records
  the actual engine, component files, and sampling options used.

After a single song works, try a two-song batch. Each song should release its GPU
process before the next starts. Start larger batches only after reviewing those
outputs. A successful render confirms the engine works, not that it obeyed every
lyric, style, or vocal instruction.

The PyTorch model/VAE paths, device, memory budget, hash verification, offloading,
quantization, revisions, cache settings and VAE tiles are **not used by audio.cpp**.
The adapter records this in its config receipt. Use the GGUF component selection,
backend and arena controls instead. Detailed-progress toggling controls the Studio
stage heartbeat; the native CLI log is always retained for diagnostics.

## Supported workflows and limits

- Lyrics, style, `full` / `melody` / `off`, 63-bit seed, CFG, ODE steps, and all
  exposed ABC/semantic sampling options are forwarded explicitly.
- `full` and `melody` can plan internally, but **Plan only** and generated-score
  export are not exposed by this CLI. Use torch when you need an editable new ABC.
- Supplied ABC covers are supported. Source transcription still uses SheetSage2.
- Requests use a UTF-8 JSON file, avoiding Windows command-line length limits and
  preserving large seeds as strings. No shell-interpreted lyric text is used.
- Native stdout/stderr is kept in run.log. The UI shows a generic audio.cpp stage
  with elapsed time; it does not invent per-token/ODE percentages from native logs.
- Output receives **Needs review**, because generated ABC, native token arrays,
  PyTorch provenance and structured truncation flags are not returned by this CLI.
  Listen for a complete ending, especially if you changed maximum tokens.
- Each song launches a fresh process. Publisher server-mode/warm-session timings
  do not directly predict this adapter's load-plus-render time.

## Memory and quality

The publisher reports Q4_0 + F16 VAE around **7,755 MiB peak VRAM** and Q8_0 + F16
around **8,867 MiB** on one RTX 5090 longform benchmark. These are publisher results,
not Studio measurements or minimum-GPU guarantees. Prompt lengths, settings,
backends and builds can change memory use. Source: the [model card](https://huggingface.co/audio-cpp/Yue2-3B-GGUF).

Q4 is smaller but not necessarily faster; quantization can change music output.
Studio retains 32 ODE steps instead of silently adopting the card's short-demo
8-step setting. The arena/context controls are capacities in MiB, not an overall
VRAM budget. Lowering them too far can fail allocation. Start with upstream defaults.

Model weights retain their separate CC BY-NC 4.0 license as described by their
publisher. audio.cpp is installed separately under its own license.
