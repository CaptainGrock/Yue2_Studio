"""Experimental audio.cpp CLI adapter, checked against dev fbe3eedbf6c504e45189e2cdcf1b257740a28863."""
import json
import os
from pathlib import Path
import subprocess
import signal
import time

SIDECARS = ('yue2-model-config.json','yue2-generation-config.json','yue2-qwen.tiktoken','yue2-vae-config.json')
NON_NATIVE = ('model','vae','revision','vae_revision','device','memory_budget_gib','quantization','offload_ar','local_files_only','cache_dir','verify_hashes','vae_core_frames')


def validate(settings, stage):
    if stage != 'audio':
        raise ValueError('audio.cpp currently exposes complete audio generation only. Use torch for Plan only and generated ABC export.')
    cfg=settings['gguf'];exe=Path(cfg['executable'])
    if not exe.is_file() or exe.name.lower() not in ('audiocpp_cli','audiocpp_cli.exe'):
        raise ValueError('Set the full path to a Yue2-capable audiocpp_cli executable in audio.cpp / GGUF settings.')
    root=Path(cfg['model_dir'])
    for relative in [cfg['model_gguf'],cfg['vae_gguf'],*('sidecars/'+name for name in SIDECARS)]:
        if not (root/relative).is_file():
            raise ValueError('Missing GGUF model component: '+str(root/relative))


def prepare(spec, directory):
    settings=spec['settings'];validate(settings,spec['stage']);cfg=settings['gguf'];request=spec['request']
    options={key:str(request[key]) for key in ('style','cot','seed')}
    options['num_inference_steps']=str(settings['generation']['ode_steps'])
    if request.get('cfg_scale') is not None:options['cfg_scale']=str(request['cfg_scale'])
    for stage in ('abc','semantic'):
        options.update({stage+'_'+key:str(value) for key,value in settings[stage].items()})
    if request.get('abc'):
        score=directory/'score.abc';score.write_text(request['abc'],encoding='utf-8');options['abc_file']=str(score.resolve())
    sequence=directory/'audiocpp-request.json'
    # All values, particularly 63-bit seeds, are strings: audio.cpp parses JSON numbers as doubles.
    sequence.write_text(json.dumps([{'id':'song','text':request['lyrics'],'options':options}],ensure_ascii=False,indent=2),encoding='utf-8')
    session={key:str(value) for key,value in cfg.items() if key not in ('executable','model_dir','backend','threads')}
    command=[str(Path(cfg['executable']).resolve()),'--task','gen','--family','yue2','--model',str(Path(cfg['model_dir']).resolve()),
             '--backend',cfg['backend'],'--threads',str(cfg['threads']),'--request-sequence',str(sequence.resolve()),
             '--batch-merge-audio','concat','--out',str((directory/'audio.wav').resolve()),'--log']
    for key,value in session.items():command.extend(['--session-option','yue2.'+key+'='+value])
    return command,{'backend':'audio.cpp','request_options':options,'session_options':session,
                   'device_backend':cfg['backend'],'threads':cfg['threads'],
                   'not_applicable_pytorch_controls':list(NON_NATIVE),
                   'upstream_contract_commit':'fbe3eedbf6c504e45189e2cdcf1b257740a28863'}


def run(path):
    from yue2.progress import Progress
    import soundfile as sf
    path=Path(path);spec=json.loads(path.read_text(encoding='utf-8'));output=path.parent/'result'
    output.mkdir(exist_ok=False)
    command,config=prepare(spec,output)
    (output/'config.json').write_text(json.dumps(config,indent=2),encoding='utf-8')
    (output/'request.json').write_text(json.dumps(spec['request'],ensure_ascii=False,indent=2),encoding='utf-8')
    print('Studio: experimental audio.cpp backend. Native C++ logs follow; PyTorch runtime controls are not used.',flush=True)
    started=time.monotonic()
    with Progress(enabled=spec['settings']['runtime']['progress']).stage('audio.cpp music generation'):
        # Inherit stdout/stderr into run.log. The queue owns and cancels this worker's entire process tree.
        previous=None
        if os.name!='nt':
            def cancelled(signum,frame):
                raise InterruptedError('audio.cpp render cancelled')
            previous=signal.signal(signal.SIGTERM,cancelled)
        try:
            # subprocess.run kills and reaps its child when interrupted by this exception.
            subprocess.run(command,check=True,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        finally:
            if previous is not None:signal.signal(signal.SIGTERM,previous)
    source=output/'audio.wav'
    if not source.is_file():raise RuntimeError('audio.cpp finished without producing audio.wav. Check build compatibility and the engine log.')
    with sf.SoundFile(source) as audio:
        if audio.frames<=0:raise RuntimeError('audio.cpp returned an empty waveform.')
        info={'sample_rate':audio.samplerate,'channels':audio.channels,'frames':audio.frames}
        with sf.SoundFile(output/'audio.flac','w',samplerate=audio.samplerate,channels=audio.channels,format='FLAC',subtype='PCM_24') as target:
            for block in audio.blocks(blocksize=65536,dtype='float32',always_2d=True):target.write(block)
    summary={'stage':'audio','backend':'audio.cpp','elapsed_seconds':time.monotonic()-started,**info,
             'warnings':['Experimental audio.cpp output: listen for completeness. This CLI does not export a generated ABC score or a structured truncation report; full PyTorch provenance is unavailable.']}
    (output/'studio_summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print('Studio: audio.cpp audio saved as WAV and FLAC. Review the result before use.',flush=True)
