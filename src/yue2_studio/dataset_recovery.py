"""Recover cached WAVs from the old Windows hard-link publication failure."""
import argparse
import ast
import json
from pathlib import Path
import re
import wave

from .dataset_import import write_json
from .dataset_worker import completed_path, publish_wav, valid_wav


def recover(directory, apply=False):
    directory = Path(directory).resolve()
    status_path = directory / 'status.json'
    state = json.loads(status_path.read_text(encoding='utf-8'))
    if state.get('status') not in ('complete_with_errors', 'failed'):
        raise ValueError('Recovery requires a finished, failed import.')
    folder = Path(state['folder']).resolve()
    cache = folder / '.playlist-import'
    if cache.resolve().parent != folder:
        raise ValueError('Cache is outside the dataset folder.')
    manifest_path = cache / 'manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else {'version': 1, 'tracks': {}}
    plan = []
    for row in state['tracks']:
        message = row.get('message', '')
        if row.get('status') != 'failed' or not message.startswith('[WinError 1]') or ' -> ' not in message:
            continue
        identifier = row['id']
        if not re.fullmatch(r'[A-Za-z0-9_-]{11}', identifier):
            raise ValueError('Invalid track ID.')
        target = Path(ast.literal_eval(message.split(' -> ', 1)[1]))
        source = cache / identifier / 'audio.wav'
        if target.resolve().parent != folder or target.suffix.lower() != '.wav' or source.resolve().parent != (cache / identifier).absolute():
            raise ValueError('Recovery path is outside its expected directory.')
        if completed_path(folder, manifest['tracks'].get(identifier, {})) == target:
            plan.append((row, source, target, None))
            continue
        if target.exists() or not valid_wav(source):
            raise ValueError(f'Cannot safely recover {identifier}: target exists or cached WAV is invalid.')
        with wave.open(str(source), 'rb') as audio:
            duration = audio.getnframes() / audio.getframerate()
        artist, separator, title = target.stem.partition(' - ')
        record = {'id': identifier, 'artist': artist if separator else 'Unknown artist',
                  'title': title if separator else target.stem, 'album': None,
                  'duration': duration, 'source_url': 'https://www.youtube.com/watch?v=' + identifier,
                  'filename': target.name, 'bytes': source.stat().st_size,
                  'needs_name_review': True, 'recovered_from_cache': True}
        plan.append((row, source, target, record))
    print(f'Validated {len(plan)} cached tracks for recovery into {folder}.')
    if not apply:
        return len(plan)
    backup = directory / 'status.before-recovery.json'
    if not backup.exists():
        write_json(backup, state)
    for row, source, target, record in plan:
        if record is not None:
            publish_wav(source, target)
            manifest['tracks'][row['id']] = record
            write_json(manifest_path, manifest)
        row.update(status='saved', filename=target.name,
                   message='Recovered cached WAV. Review inferred artist/title.')
        write_json(status_path, state)
    failures = sum(row['status'] == 'failed' for row in state['tracks'])
    state.update(status='complete_with_errors' if failures else 'complete',
                 message=f'Recovered {len(plan)} cached WAVs without downloading. {failures} tracks still failed.')
    write_json(status_path, state)
    print(state['message'])
    return len(plan)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory')
    parser.add_argument('--apply', action='store_true', help='Publish validated cached WAVs; otherwise only inspect.')
    args = parser.parse_args()
    recover(args.directory, args.apply)
