"""Issue #12: optional sidecars must not invalidate an Artist base model."""
import hashlib
import pytest

from yue2_studio.artist_identity import validate_base


@pytest.fixture
def base(tmp_path):
    folder = tmp_path / 'model'
    folder.mkdir()
    for name in ('config.json', 'qwen.tiktoken', 'model.safetensors',
                 'generation_config.json', 'weights_manifest.json'):
        (folder / name).write_bytes(name.encode())
    identity = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()}
    return folder, identity, tmp_path


def test_legacy_manifest_accepts_changed_missing_and_extra_sidecars(base):
    folder, expected, directory = base
    (folder / 'generation_config.json').write_text('{}')
    (folder / 'weights_manifest.json').unlink()
    (folder / 'yue2_generation_config.json').write_text('{}')
    validate_base(folder, expected, directory)


@pytest.mark.parametrize('name', ['config.json', 'qwen.tiktoken', 'model.safetensors'])
@pytest.mark.parametrize('missing', [False, True])
def test_rejects_changed_or_missing_required_files(base, name, missing):
    folder, expected, directory = base
    if missing:
        (folder / name).unlink()
    else:
        (folder / name).write_bytes(b'changed')
    with pytest.raises(ValueError) as error:
        validate_base(folder, expected, directory, 'original-model')
    assert name in str(error.value)
    assert 'original-model' in str(error.value)
    assert str(folder) in str(error.value)


def test_rejects_added_weights(base):
    folder, expected, directory = base
    (folder / 'extra.safetensors').write_bytes(b'extra')
    with pytest.raises(ValueError, match='extra.safetensors'):
        validate_base(folder, expected, directory)


def test_rejects_incomplete_manifest(base):
    folder, _, directory = base
    with pytest.raises(ValueError, match='manifest is missing'):
        validate_base(folder, {}, directory)


def test_sharded_weights_and_index_remain_required(base):
    folder, _, directory = base
    (folder / 'model.safetensors').unlink()
    for name in ('model-00001-of-00002.safetensors', 'model-00002-of-00002.safetensors',
                 'model.safetensors.index.json'):
        (folder / name).write_bytes(name.encode())
    expected = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()}
    validate_base(folder, expected, directory)
    (folder / 'model.safetensors.index.json').write_text('{}')
    with pytest.raises(ValueError, match='model.safetensors.index.json'):
        validate_base(folder, expected, directory)
