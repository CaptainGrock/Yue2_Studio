"""Compare Artist base files without treating generation metadata as weights."""
import hashlib
from pathlib import Path


def _digest(path, directory):
    value = hashlib.sha256()
    with path.open('rb') as handle:
        while block := handle.read(8 * 1024 * 1024):
            if (Path(directory) / 'cancel.request').exists():
                from .training_worker import Cancelled
                raise Cancelled()
            value.update(block)
    return value.hexdigest()


def compatibility_files(identity):
    # Accept legacy manifests, which also recorded every JSON sidecar.
    return {name: digest for name, digest in identity.items()
            if name in ('config.json', 'qwen.tiktoken', 'model.safetensors.index.json')
            or name.endswith('.safetensors')}


def validate_base(folder, expected, directory, trained_model=None):
    folder = Path(folder)
    expected = compatibility_files(expected)
    if not {'config.json', 'qwen.tiktoken'} <= expected.keys() or not any(
            name.endswith('.safetensors') for name in expected):
        raise ValueError('Artist LoRA manifest is missing its base weights, config, or tokenizer identity.')
    names = {p.name for p in folder.glob('*.safetensors')}
    names.update(('config.json', 'qwen.tiktoken'))
    if (folder / 'model.safetensors.index.json').is_file():
        names.add('model.safetensors.index.json')
    actual = {name: _digest(folder / name, directory) for name in names
              if (folder / name).is_file()}
    differences = sorted(name for name in actual.keys() | expected.keys()
                         if actual.get(name) != expected.get(name))
    if differences:
        source = trained_model or 'not recorded in this older Artist bundle'
        raise ValueError('Artist LoRA was trained against different base-model files. '
                         f'Differing or missing files: {", ".join(differences)}. '
                         f'Training model: {source}. Generation model: {folder}. '
                         'Select the matching model folder in Studio runtime settings.')
