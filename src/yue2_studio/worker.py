"""Isolated GPU generation process. A cancelled process releases its CUDA context."""
import json
from pathlib import Path
import sys

from .settings import ROOT
from .compatibility import capabilities, compatible_runtime


def run(path):
    spec = json.loads(Path(path).read_text(encoding='utf-8'))
    settings = spec['settings']
    selection = settings.get('lora', {})
    if selection.get('path') and settings['runtime']['backend']=='audio.cpp':
        raise ValueError('Style LoRAs are not supported by audio.cpp.')
    if settings['runtime']['backend']=='audio.cpp':
        from .gguf import run
        return run(path)
    from yue2 import YuE2Pipeline
    from yue2.protocol import GenerationConfig
    config = GenerationConfig.from_dict({k:settings[k] for k in ('abc','semantic')} |
                                        {'ode_steps':settings['generation']['ode_steps']})
    runtime, adjustment = compatible_runtime(settings['runtime'], capabilities()['flash_attention'])
    if adjustment:
        print('Studio compatibility: torch CUDA graphs retained. '+adjustment['reason']+' Sampling and synthesis settings are unchanged.',flush=True)
        (Path(path).parent/'runtime_adjustments.json').write_text(json.dumps(adjustment,indent=2),encoding='utf-8')
    for key in ('revision','vae_revision','cache_dir'):
        if not runtime[key]:
            runtime[key] = None
    output = Path(path).parent / 'result'
    output.mkdir(exist_ok=False)
    with YuE2Pipeline.from_pretrained(**runtime,generation_config=config) as pipe:
        if selection.get('path'):
            info = pipe.load_lora(selection['path'], strength=selection['strength'])
            if info['sha256'] != spec.get('lora',{}).get('sha256'):
                raise ValueError('LoRA file changed after this song was queued; no audio was generated.')
            if info.get('kind')=='artist':
                from .training_worker import model_identity
                if info['companion_sha256']!=spec['lora'].get('companion_sha256') or info['base_identity']!=spec['lora'].get('base_identity'):
                    raise ValueError('Artist bundle identity changed after queueing.')
                if model_identity(pipe.model_dir,Path(path).parent)!=info['base_identity']:
                    raise ValueError('Artist LoRA was trained against different base-model files.')
                if spec['request'].get('cot')!='off':raise ValueError('Artist LoRA requires No score mode.')
                print('Artist AR adapter + pinned NAR companion selected; no score mode.',flush=True)
            print('Studio LoRA: '+Path(info['path']).name+' · strength '+str(info['strength']), flush=True)
        if spec['stage']=='plan':
            plan = pipe.plan(**spec['request'])
            plan.save(output)
            (output/'request.json').write_text(json.dumps(spec['request'],ensure_ascii=False,indent=2),encoding='utf-8')
            (output/'provenance.json').write_text(json.dumps({'weights':pipe.weights,'config':pipe.effective_config(plan.request)},indent=2),encoding='utf-8')
            (output/'studio_summary.json').write_text(json.dumps({'truncated':{'abc':plan.truncated},'stage':'plan'}),encoding='utf-8')
        else:
            song = pipe(**spec['request'])
            song.save_artifacts(output)
    print('Studio: artifacts saved.',flush=True)


if __name__ == '__main__':
    run(sys.argv[1])
