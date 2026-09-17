"""LoRA queue and worker contracts, using tiny CPU fixtures and no live engine."""
import json
import threading
import urllib.request
from unittest.mock import MagicMock, patch

import pytest
import torch
from safetensors.torch import save_file

from yue2_studio import loras
from yue2_studio.jobs import JobManager, generation_spec
from yue2_studio.settings import defaults
from yue2_studio.worker import run


@pytest.fixture
def adapter(tmp_path):
    folder = tmp_path / 'models' / 'loras'
    folder.mkdir(parents=True)
    path = folder / 'test_style.safetensors'
    save_file({'diffusion_model.llm2vae.lora_down.weight':torch.ones(2, 16),
               'diffusion_model.llm2vae.lora_up.weight':torch.ones(64, 2)},path,
              metadata={'format':'comfyui-native-lora','trigger_word':'my_sound','training_style':'Warm guitars, expressive mezzo'})
    return path


def payload(adapter):
    settings = defaults()
    settings['lora'].update(path=str(adapter), strength=.75)
    return {'request':{'style':'piano pop','lyrics':'[Verse]\nHello','seed':42},'settings':settings}


def test_legacy_training_style_lookup_is_read_only(tmp_path,monkeypatch):
    monkeypatch.setattr(loras,'ROOT',tmp_path)
    project_id='a'*32
    folder=tmp_path/'training/projects';folder.mkdir(parents=True)
    path=folder/(project_id+'.json')
    path.write_text(json.dumps({'id':project_id,'default_caption':'Original saved style'}))
    original=path.read_bytes()
    metadata={'format':'yue2-lora-v1','project_id':project_id}
    assert loras.training_style(metadata)=='Original saved style'
    assert path.read_bytes()==original
    assert loras.training_style({**metadata,'training_style':'Embedded style'})=='Embedded style'
    assert loras.training_style({**metadata,'project_id':'../../outside'})==''
    assert loras.training_style({})==''


def test_discovery_excludes_wrong_models_and_corrupt_files(adapter, tmp_path, monkeypatch):
    monkeypatch.setattr(loras, 'ROOT', tmp_path)
    (adapter.parent/'bad.safetensors').write_bytes(b'bad')
    save_file({'diffusion_model.blocks.0.lora_down.weight':torch.ones(1,1),
               'diffusion_model.blocks.0.lora_up.weight':torch.ones(1,1)},adapter.parent/'music3.safetensors')
    result = loras.catalogue()
    assert len(result['loras']) == 1 and len(result['rejected']) == 2
    assert result['loras'][0]['trigger_word'] == 'my_sound'
    assert result['loras'][0]['training_style'] == 'Warm guitars, expressive mezzo'
    assert loras.inspect_adapter(str(adapter))['training_style'] == 'Warm guitars, expressive mezzo'


def test_queue_snapshot_trigger_and_restore(adapter, tmp_path):
    manager = JobManager(tmp_path/'runs',start=False)
    data = payload(adapter)
    job = manager.generate(data)
    spec = manager.detail(job['id'])['input']
    assert data['request']['style'] == 'piano pop'
    assert spec['request']['style'] == 'my_sound, piano pop'
    assert spec['lora']['strength'] == .75
    assert job['lora']['sha256'] == spec['lora']['sha256']
    data['settings']['lora']['strength'] = 2
    assert manager.detail(job['id'])['input']['settings']['lora']['strength'] == .75
    assert generation_spec(spec)['request']['style'] == 'my_sound, piano pop'
    data['settings']['lora']['auto_trigger'] = False
    assert generation_spec(data)['request']['style'] == 'piano pop'
    data['settings']['lora']['path'] = ''
    assert 'lora' not in generation_spec(data)


def test_gguf_and_invalid_strength_rejected(adapter):
    data = payload(adapter)
    data['settings']['runtime']['backend'] = 'audio.cpp'
    with pytest.raises(ValueError, match='Python engine'):
        generation_spec(data)
    data['settings']['runtime']['backend'] = 'torch'
    for strength in [-1, 3, float('nan'), True]:
        data['settings']['lora']['strength'] = strength
        with pytest.raises(ValueError):
            generation_spec(data)


def test_worker_loads_recorded_adapter_before_generation(adapter, tmp_path):
    spec = generation_spec(payload(adapter))
    path = tmp_path/'input.json'
    path.write_text(json.dumps(spec),encoding='utf-8')
    factory = MagicMock()
    pipe = factory.return_value.__enter__.return_value
    pipe.load_lora.return_value = spec['lora']
    with patch('yue2.YuE2Pipeline.from_pretrained',factory), patch('yue2_studio.worker.capabilities',return_value={'flash_attention':True}):
        run(path)
    pipe.load_lora.assert_called_once_with(str(adapter),strength=.75)
    pipe.assert_called_once_with(**spec['request'])
    assert 'lora' not in factory.call_args.kwargs


def test_changed_file_fails_retry_and_worker_before_render(adapter, tmp_path):
    spec = generation_spec(payload(adapter))
    save_file({'diffusion_model.llm2vae.lora_down.weight':torch.zeros(2,16),
               'diffusion_model.llm2vae.lora_up.weight':torch.zeros(64,2)},adapter)
    with pytest.raises(ValueError,match='changed'):
        generation_spec(spec)
    path = tmp_path/'input.json'
    path.write_text(json.dumps(spec),encoding='utf-8')
    factory = MagicMock()
    pipe = factory.return_value.__enter__.return_value
    pipe.load_lora.return_value = loras.inspect_adapter(str(adapter))
    with patch('yue2.YuE2Pipeline.from_pretrained',factory), patch('yue2_studio.worker.capabilities',return_value={'flash_attention':True}):
        with pytest.raises(ValueError,match='changed'):
            run(path)
    pipe.assert_not_called()


@pytest.mark.parametrize('changed_weights', [False, True])
def test_artist_worker_checks_weights_but_allows_sidecar_changes(adapter, tmp_path, changed_weights):
    from yue2_studio.training_worker import model_identity
    model = tmp_path / 'base'
    model.mkdir()
    for name in ('model.safetensors', 'config.json', 'qwen.tiktoken', 'generation_config.json'):
        (model / name).write_bytes(name.encode())
    identity = model_identity(model, tmp_path)
    (model / 'generation_config.json').write_text('{}')
    if changed_weights:
        (model / 'model.safetensors').write_bytes(b'different')
    spec = generation_spec(payload(adapter))
    spec['request']['cot'] = 'off'
    spec['lora'].update(kind='artist', base_identity=identity, companion_sha256='companion')
    path = tmp_path / 'input.json'
    path.write_text(json.dumps(spec), encoding='utf-8')
    factory = MagicMock()
    pipe = factory.return_value.__enter__.return_value
    pipe.model_dir = model
    pipe.load_lora.return_value = spec['lora']
    with patch('yue2.YuE2Pipeline.from_pretrained', factory), patch(
            'yue2_studio.worker.capabilities', return_value={'flash_attention': True}):
        if changed_weights:
            with pytest.raises(ValueError, match='model.safetensors'):
                run(path)
            pipe.assert_not_called()
        else:
            run(path)
            pipe.assert_called_once_with(**spec['request'])


def test_http_catalogue_inspection_and_static_controls(adapter, tmp_path, monkeypatch):
    from yue2_studio.server import StudioServer
    monkeypatch.setattr(loras, 'ROOT', tmp_path)
    manager = JobManager(tmp_path/'http-runs',start=False)
    server = StudioServer(('127.0.0.1',0),manager=manager)
    thread = threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    try:
        with urllib.request.urlopen(base+'/api/loras') as response:
            assert json.load(response)['loras'][0]['name'] == 'test_style'
        with urllib.request.urlopen(base+'/loras.js') as response:
            assert 'function bindLoras' in response.read().decode()
        request = urllib.request.Request(base+'/api/loras/inspect',
            data=json.dumps({'path':str(adapter)}).encode(),
            headers={'Content-Type':'application/json','X-Studio-Token':server.token})
        with urllib.request.urlopen(request) as response:
            assert len(json.load(response)['sha256']) == 64
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
