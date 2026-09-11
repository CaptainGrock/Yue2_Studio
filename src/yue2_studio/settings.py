"""Single source of truth for editable controls, defaults and validation."""
from __future__ import annotations

import math
import os
from pathlib import Path

ROOT = Path(os.environ.get('YUE2_KIT', Path(__file__).resolve().parents[2])).resolve()


def detected_gguf_executable():
    name = 'audiocpp_cli.exe' if os.name == 'nt' else 'audiocpp_cli'
    for checkout in (ROOT/'tools/audio.cpp', ROOT/'audio.cpp'):
        for build in ('build/windows-cuda-release/bin', 'build/bin'):
            candidate = checkout/build/name
            if candidate.is_file():
                return str(candidate.resolve())
    return ''


def field(key, label, default, note, *, kind=None, choices=None, minimum=None, maximum=None, step=None):
    return dict(key=key, label=label, default=default, note=note,
                kind=kind or ('bool' if isinstance(default, bool) else 'number' if isinstance(default, (int, float)) else 'text'),
                choices=choices, min=minimum, max=maximum, step=step)


GROUPS = [
    dict(id='runtime', title='Models & runtime', subtitle='Where the music runs and how memory is used.', fields=[
        field('model', 'YuE2 model', str(ROOT / 'models/YuE2-3B'), 'Local model folder or Hugging Face repository ID. The local YuE2-3B installation is selected by default. Changing the model changes the generated performance.'),
        field('vae', 'Audio decoder (VAE)', str(ROOT / 'models/YuE2-Vae'), 'Use YuE2-Vae for listening. YuE2-Vae-legacy is for reproducing the published benchmark. Accepts a local folder or Hub repository ID; the decoder identity is recorded with the song.'),
        field('revision', 'Model revision', '', 'Optional Hugging Face commit or tag for the generation model. A commit pins a reproducible snapshot. Leave blank for the repository default; local folders use their existing files.'),
        field('vae_revision', 'Decoder revision', '', 'Optional independent Hub commit or tag for the VAE. This does not change the generation model revision.'),
        field('device', 'Compute device', 'auto', 'auto selects CUDA, then Apple MPS, then CPU. Enter cuda:0 or cuda:1 for a specific GPU. The supported baseline is a BF16-capable NVIDIA GPU with 24 GiB VRAM; CPU execution can be extremely slow.'),
        field('memory_budget_gib', 'GPU memory budget · GiB', 24.0, 'Total runtime memory budget. The CUDA pipeline reserves 2 GiB and caps allocation against physical VRAM. Smaller budgets can use smaller decode tiles; they do not shorten the song or reduce synthesis steps.', minimum=2.1, step=.5),
        field('backend', 'Inference backend', 'torch', 'torch uses fast CUDA graphs. Builds without Flash Attention use cuDNN attention when supported, otherwise SDPA, while retaining graphs. torch-eager disables graphs for troubleshooting and is substantially slower. vllm needs separate fast dependencies and a supported platform. audio.cpp is experimental GGUF support; configure its separate settings group. PyTorch model paths, device, memory budget, quantization, offloading and VAE tiles do not apply to audio.cpp.', choices=['torch','torch-eager','vllm','audio.cpp']),
        field('quantization', 'Weight quantization', 'none', 'none preserves the baseline model precision. fp8 uses the optional runtime FP8 path to reduce weight memory; hardware/backend support and output quality require separate validation.', choices=['none','fp8']),
        field('offload_ar', 'Offload autoregressive model', False, 'Release/offload the autoregressive model before acoustic synthesis to reduce peak GPU memory. Reloading increases latency. This is not a lower-quality sampling preset.'),
        field('local_files_only', 'Offline model loading', True, 'Only use local files and already cached snapshots. Disable to allow Hugging Face downloads. LLM API calls are controlled separately by your chosen runner.'),
        field('cache_dir', 'Hugging Face cache folder', str(ROOT / 'hf-cache'), 'Cache for model snapshots. Existing local model folders take precedence. For private or gated Hub repositories, set HF_TOKEN in the launcher environment; secrets are never written to run manifests.'),
        field('verify_hashes', 'Verify model hashes', False, 'Hash model files when opening the pipeline so each run records exact weight identity. Large files can take time to verify. Disabling trades provenance strength for faster startup.'),
        field('vae_core_frames', 'VAE tile core frames', None, 'Blank uses the engine default: 512 at budgets of 12 GiB or less, otherwise 1024. Larger tiles use more memory. Applies to tiled decoding; the engine may decode in one pass when memory permits.', kind='integer', minimum=1),
        field('progress', 'Detailed engine progress', True, 'Show live stage messages, token counts, and elapsed times in the run log. No artificial percentage is calculated: token limits are ceilings, not known completion targets.'),
    ]),
    dict(id='generation', title='Synthesis & guidance', subtitle='Audio rendering and native generation behavior.', fields=[
        field('ode_steps', 'Synthesis steps', 32, 'Number of midpoint integration steps that convert semantic tokens into acoustic latents. More steps cost time; fewer depart from the validated 32-step baseline. This is not a song-duration control.', kind='integer', minimum=1),
        field('cfg_scale', 'Semantic guidance (CFG)', None, 'Blank uses 1.0 for full/melody or 1.01 for direct audio. Values above 1 strengthen text conditioning and can increase compute. With ABC, both CFG branches retain the same score. Higher is not automatically better. No CFG is applied to the ABC planner.', kind='number', minimum=0, maximum=20, step=.01),
    ]),
]

GROUPS.append(dict(id='gguf', title='audio.cpp / GGUF', subtitle='Experimental alternative engine. Requires a Yue2-capable audio.cpp dev build, GGUF components and all four sidecars. PyTorch runtime controls do not apply.', fields=[
    field('executable','audio.cpp executable',detected_gguf_executable(),'Full path to audiocpp_cli.exe on Windows or audiocpp_cli on Linux. Blank automatically detects a build under tools/audio.cpp or audio.cpp in your YuE2 folder. Use a build with Yue2 support from the audio.cpp dev branch. Studio does not install or download the binary.'),
    field('model_dir','GGUF model folder',str(ROOT/'models/Yue2-3B-GGUF'),'Folder containing the main GGUF, VAE GGUF and sidecars subfolder. Download only the component precision you want plus all sidecars.'),
    field('model_gguf','Main GGUF','yue2-3b-q8_0.gguf','Q8 is the balanced default. Q4 uses smaller weights but is not necessarily faster or identical in quality. Paths are relative to the GGUF folder.',choices=['yue2-3b-q8_0.gguf','yue2-3b-q4_0.gguf','yue2-3b-bf16.gguf']),
    field('vae_gguf','GGUF decoder','yue2-vae-f16.gguf','F16 reduces VAE weight memory. F32 uses more memory. The GGUF decoder is separate from the PyTorch VAE.',choices=['yue2-vae-f16.gguf','yue2-vae-f32.gguf']),
    field('backend','audio.cpp device backend','cuda','Must be compiled into your audio.cpp binary. CUDA is the NVIDIA path; other backends depend on your build and are not locally validated.',choices=['cuda','cpu','vulkan','metal','hip']),
    field('threads','audio.cpp CPU threads',8,'CPU threads for the C++ engine. More is not always faster when sharing the CPU with other programs.',kind='integer',minimum=1,maximum=256),
]))
for key,value,note in [
    ('model_weight_context_mb',6144,'Main-model weight context capacity.'),
    ('vae_weight_context_mb',1536,'VAE weight context capacity.'),
    ('ar_prefill_graph_arena_mb',4096,'Graph arena for processing the prompt and score prefix.'),
    ('ar_decode_graph_arena_mb',1536,'Graph arena for autoregressive token decoding.'),
    ('nar_graph_arena_mb',6144,'Graph arena for acoustic synthesis.'),
    ('vae_graph_arena_mb',1536,'Graph arena for waveform decoding.')]:
    GROUPS[-1]['fields'].append(field(key,key.replace('_',' ').capitalize(),value,note+' Units are MiB. These are upstream context/arena capacities, not a measured peak-VRAM estimate or a global memory budget. Smaller values can cause allocation failures.',kind='integer',minimum=1))
for key in ('model_weight_type','vae_weight_type'):
    GROUPS[-1]['fields'].append(field(key,key.replace('_',' ').capitalize(),'native','Native retains storage from the selected GGUF. Overrides can alter memory, speed and quality; support depends on the audio.cpp build.',choices=['native','f32','f16','bf16','q8_0','q4_0','q4_k']))

SAMPLING_NOTES = {
    'temperature': 'Scales token probabilities. Lower values are more predictable; higher values add variation. Zero selects greedily. This affects this stage only; it is separate from the LLM writing temperature.',
    'top_p': 'Nucleus sampling keeps the smallest token set whose cumulative probability reaches this value. Smaller values narrow variation; 1 disables this filter. Combines with top-k and temperature.',
    'top_k': 'Keep only this many highest-scoring next-token candidates. A smaller set is more conservative. Must be at least 1; this engine does not use 0 as an off switch.',
    'repetition_penalty': 'Penalizes tokens repeated in the recent window. 1 is neutral; above 1 discourages repetition; below 1 encourages it. Excessive penalties can disrupt recurring musical or score patterns.',
    'penalty_window': 'Number of recent tokens examined for repetition, from 1 to 100. A larger window discourages repetition over a longer span; this is measured in model tokens, not lyric words or beats.',
    'min_tokens': 'Minimum stage tokens before the end marker is permitted. A large minimum may force unnecessary content. Must not exceed maximum tokens. This does not enforce seconds of audio.',
    'max_tokens': 'Hard upper bound for this stage, not a target length. Reaching it can truncate the score or song; the library displays truncation flags. More tokens increase runtime, memory pressure, and context consumption.',
}
for stage, defaults in [('abc', [.7,.9,30,1.005,100,32,4096]), ('semantic',[1.,.95,100,1.2,50,200,9000])]:
    bounds = [(0,5,.05),(.001,1,.01),(1,None,1),(.001,None,.005),(1,100,1),(0,None,1),(1,None,1)]
    GROUPS.append(dict(id=stage, title='Symbolic planner' if stage == 'abc' else 'Audio token sampling',
        subtitle='Used when generating a new ABC score. Bypassed for supplied scores and direct audio.' if stage == 'abc' else 'Controls the semantic music tokens before acoustic synthesis.',
        fields=[field(key,key.replace('_',' ').capitalize(),default,SAMPLING_NOTES[key],
                      kind='integer' if key in ('top_k','penalty_window','min_tokens','max_tokens') else 'number',
                      minimum=bound[0],maximum=bound[1],step=bound[2])
                for (key,default,bound) in zip(SAMPLING_NOTES,defaults,bounds)]))

GROUPS.append(dict(id='transcription', title='Cover transcription', subtitle='Runs in the separate SheetSage2 environment, one GPU job at a time.', fields=[
    field('python', 'SheetSage2 Python', str(ROOT / ('SheetSage2-venv/Scripts/python.exe' if __import__('os').name == 'nt' else 'SheetSage2-venv/bin/python')), 'Python executable for the separate SheetSage2 installation. Its dependency pins differ from YuE2. Only a Python executable is accepted; this is not a shell command.'),
    field('model','SheetSage2 model',str(ROOT / 'models/SheetSage2'),'Local SheetSage2 folder or Hub ID. The released transcription helper loads the model’s custom Transformers code. Use your installed, reviewed snapshot.'),
    field('base_model','MERT base model',str(ROOT / 'models/MERT-v2-FullSong'),'Verified MERT-v2-FullSong snapshot used by the SheetSage2 adapter. MERT features are not directly fed into YuE2.'),
    field('revision','Transcription revision','','Optional commit pin for both model weights and remote model code. Leave blank for the installed local files.'),
    field('task','Melody to transcribe','melody-full','Full lead melody includes instrumental passages. Vocal melody focuses on singing. Full score also transcribes chords and is useful for melody-and-harmony regeneration. Transcription does not extract lyric text.',choices=['melody-full','melody-vocal','full']),
    field('device','Transcription device','cuda','Select cuda, cuda:0, or another supported Torch device. SheetSage2 exits and frees its allocations before a music job begins.'),
    field('dtype','Transcription precision','bf16','bf16 is the normal GPU preset. fp32 increases memory use and can help compatibility; it is not a guarantee of better transcription.',choices=['bf16','fp32']),
    field('preset','Transcription preset','default','default is the release’s normal transcription preset. paper is its benchmark preset. Inspect resulting notes and warnings before using them as a cover condition.',choices=['default','paper']),
    field('max_seconds','Crop source to seconds',None,'Blank processes the entire recording. Enter a positive value only when you explicitly want to crop from the beginning. The original uploaded file is retained.',kind='number',minimum=.01,step=1),
    field('threads','CPU threads',4,'CPU worker threads used during transcription. More threads can help preprocessing but also increase CPU contention.',kind='integer',minimum=1),
    field('offline','Offline transcription',True,'Use only installed or cached SheetSage2 and MERT files. Disable only if you want the transcriber to resolve/download a Hub snapshot.'),
    field('overlap_seconds','Window overlap · seconds',None,'Blank follows the preset: 200 seconds for default, 100 for paper. Overlap carries earlier transcribed context into the next window. Require lookahead ≤ overlap < the model’s 300-second window. Excessive overlap can fill the decoder context.',kind='number',minimum=0,maximum=299.99,step=1),
    field('lookahead_seconds','Window lookahead · seconds',None,'Blank follows the preset: 100 seconds for default, 0 for paper. Keeps right-hand audio context before accepting a window’s final notes. Must not exceed overlap. The paper preset fixes both values.',kind='number',minimum=0,maximum=299.99,step=1),
    field('export_logits','Export raw transcription logits',False,'Save per-window raw decoder logits as safetensors. Intended for research and debugging; can produce very large files and increase CPU memory and disk use.'),
    field('export_scores','Export constrained token scores',False,'Save transcription token scores after grammar constraints. Useful for inspecting decoder decisions; these are not perceptual audio-quality scores.'),
    field('export_embeddings','Export audio embeddings',False,'Save MERT audio embeddings alongside the transcription. They are analysis artifacts, not YuE2 codec inputs.'),
    field('output_hidden_states','Export all MERT hidden layers',False,'Save all 24 MERT layer states for feature analysis. This can require substantial memory and disk space. Leave off for normal covers.'),
]))

FIXED = [
    dict(label='Context window', value='24,576 tokens', note='Fixed by the checkpoint protocol; shared by prompt, ABC, and music tokens.'),
    dict(label='ODE method', value='midpoint', note='The only supported synthesis integrator in this runtime.'),
    dict(label='Protocol version', value='yue2-native-v1', note='Native text/ABC/music serialization. This is a compatibility identifier, not a creative setting.'),
    dict(label='Precision', value='BF16 AR/NAR · FP32 VAE', note='Baseline model precision. Optional FP8 weight quantization is exposed above.'),
    dict(label='Audio output', value='48 kHz · stereo · FLAC', note='Native lossless result with audio, ABC, tokens, latents, timings and provenance retained. WAV download is available in the library.'),
    dict(label='VAE halo', value='16 frames', note='Fixed tile overlap used by the public decoder.'),
    dict(label='GPU concurrency', value='1 job', note='Song creation and transcription share one serial queue to avoid competing for GPU memory.'),
    dict(label='Duration / BPM / negative prompt', value='Musical conditions', note='There are no separate duration, BPM, reference-singer, or negative-prompt arguments. Describe tempo and instrumentation in Style; ABC can specify tempo exactly. Lyrics and score shape duration, but do not guarantee audio length.'),
]


def defaults():
    return {group['id']: {f['key']: f['default'] for f in group['fields']} for group in GROUPS}


def validate_settings(data):
    if not isinstance(data, dict):
        raise ValueError('Settings must be an object.')
    result = defaults()
    known = {g['id']: g for g in GROUPS}
    if set(data) - set(known):
        raise ValueError('Unknown settings groups: ' + ', '.join(set(data) - set(known)))
    for group_id, values in data.items():
        fields = {f['key']: f for f in known[group_id]['fields']}
        if not isinstance(values, dict) or set(values) - set(fields):
            raise ValueError(f'Unknown or invalid settings in {group_id}.')
        for key, value in values.items():
            f = fields[key]
            if value is None and f['default'] is None:
                result[group_id][key] = None
                continue
            kind = f['kind']
            valid = (type(value) is bool if kind == 'bool' else type(value) is int if kind == 'integer' else
                     type(value) in (float,int) and math.isfinite(value) if kind == 'number' else isinstance(value,str))
            if not valid:
                raise ValueError(f"{f['label']}: expected {kind}.")
            if f['choices'] and value not in f['choices']:
                raise ValueError(f"{f['label']}: unsupported value.")
            if kind in ('number','integer') and ((f['min'] is not None and value < f['min']) or (f['max'] is not None and value > f['max'])):
                raise ValueError(f"{f['label']}: outside the supported range.")
            if isinstance(value,str) and (len(value)>4096 or '\x00' in value):
                raise ValueError(f"{f['label']}: invalid text.")
            result[group_id][key] = value
    from yue2.protocol import GenerationConfig
    GenerationConfig.from_dict({**{k: result[k] for k in ('abc','semantic')}, 'ode_steps': result['generation']['ode_steps']})
    transcription=result['transcription']
    baseline=(200,100) if transcription['preset']=='default' else (100,0)
    overlap=transcription['overlap_seconds'] if transcription['overlap_seconds'] is not None else baseline[0]
    lookahead=transcription['lookahead_seconds'] if transcription['lookahead_seconds'] is not None else baseline[1]
    if not 0 <= lookahead <= overlap < 300:
        raise ValueError('Transcription requires 0 ≤ lookahead ≤ overlap < 300 seconds.')
    if transcription['preset']=='paper' and (overlap,lookahead)!=(100,0):
        raise ValueError('The paper transcription preset fixes overlap=100 and lookahead=0.')
    if not result['gguf']['executable'].strip():
        result['gguf']['executable'] = detected_gguf_executable()
    return result
