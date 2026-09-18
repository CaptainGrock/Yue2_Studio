"""Download individual playlist tracks as WAV; no Torch imports or GPU use."""
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
import wave

from .dataset_import import write_json, javascript_runtime


def track_names(info, fallback_artist=''):
    artist = str(info.get('artist') or '').strip()
    title = str(info.get('track') or '').strip()
    reliable = bool(artist and title)
    video_title = str(info.get('title') or info.get('id') or 'Untitled').strip()
    if not title:
        # Numbered album uploads commonly use "02   Song - Album", not Artist - Song.
        numbered = re.match(r'^\d{1,3}(?:\s{2,}|[.)]\s+)(.+?)\s+[-–—]\s+(.+)$', video_title)
        match = re.match(r'^(.+?)\s+[-–—]\s+(.+)$', video_title)
        if numbered and (artist or str(fallback_artist or '').strip()):
            title = numbered[1].strip()
        elif match:
            artist = artist or match[1].strip()
            title = match[2].strip()
        else:
            title = video_title
    artist = artist or str(fallback_artist or '').strip() or 'Unknown artist'
    return artist, title, not reliable


def safe_name(value):
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', value).strip(' .')[:150].rstrip(' .')
    if not value or value.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', *('COM'+str(i) for i in range(1,10)), *('LPT'+str(i) for i in range(1,10))}:
        value = '_' + value
    return value


def valid_wav(path):
    try:
        with wave.open(str(path), 'rb') as audio:
            return (audio.getframerate() == 48000 and audio.getnchannels() == 2 and
                    audio.getsampwidth() == 2 and audio.getnframes() > 0 and
                    path.stat().st_size >= audio.getnframes() * 4 + 44)
    except (OSError, EOFError, wave.Error):
        return False


def completed_path(folder, record):
    name = record.get('filename', '')
    if not name or Path(name).name != name:
        return None
    path = folder / name
    if path.resolve().parent != folder.resolve():
        return None
    return path if valid_wav(path) and path.stat().st_size == record.get('bytes') else None


def publish_wav(audio, target):
    """Publish on the same volume without replacing an existing destination."""
    if os.name == 'nt':
        # Windows rename fails if target exists and works on exFAT as well as NTFS.
        # Do not use replace(): it would silently overwrite user files.
        os.rename(audio, target)
    else:
        os.link(audio, target)
        audio.unlink()


def run(directory, factory=None):
    if factory is None:
        from yt_dlp import YoutubeDL
        factory = YoutubeDL
    directory = Path(directory)
    spec = json.loads((directory / 'input.json').read_text(encoding='utf-8'))
    folder = Path(spec['folder'])
    folder.mkdir(parents=True, exist_ok=True)
    cache = folder / '.playlist-import'
    cache.mkdir(exist_ok=True)
    if cache.resolve().parent != folder.resolve():
        raise ValueError('Import cache must be inside the dataset folder, not a linked directory.')
    manifest_path = cache / 'manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else {'version': 1, 'tracks': {}}
    state = {'status': 'reading', 'folder': str(folder), 'url': spec['url'], 'tracks': [], 'message': 'Reading playlist…'}
    def publish():
        write_json(directory / 'status.json', state)
    def check():
        if (directory / 'cancel.request').exists():
            raise InterruptedError('Cancelled. Completed WAVs are kept.')
    runtimes = javascript_runtime()
    common = {'quiet': True, 'noprogress': True, 'socket_timeout': 30, 'retries': 3,
              'fragment_retries': 3, 'js_runtimes': runtimes}
    try:
        publish()
        check()
        with factory({**common, 'extract_flat': 'in_playlist', 'skip_download': True, 'ignoreerrors': True}) as downloader:
            playlist = downloader.extract_info(spec['url'], download=False)
        if not playlist:
            raise ValueError('Could not read playlist. Check that it is public or unlisted.')
        entries = list(playlist.get('entries') or [])
        if not entries:
            raise ValueError('No accessible tracks found in this playlist.')
        state['title'] = playlist.get('title', 'YouTube playlist')
        state['tracks'] = [{'id': (entry or {}).get('id', ''), 'title': (entry or {}).get('title', 'Unavailable item'),
                            'status': 'pending', 'message': ''} for entry in entries]
        state.update(status='downloading', message='Downloading playlist tracks…')
        publish()
        for row in state['tracks']:
            check()
            identifier = row['id']
            if not re.fullmatch(r'[A-Za-z0-9_-]{11}', str(identifier)):
                row.update(status='failed', message='Unavailable or unsupported playlist item.')
                publish()
                continue
            previous = manifest['tracks'].get(identifier, {})
            existing = completed_path(folder, previous)
            if existing:
                row.update(status='skipped', filename=existing.name, message='Already downloaded and verified.')
                publish()
                continue
            stage = cache / identifier
            stage.mkdir(exist_ok=True)
            if stage.resolve().parent != cache.resolve():
                raise ValueError('Track cache must not be a linked directory.')
            last_update = 0
            def progress(data):
                nonlocal last_update
                check()
                now = time.monotonic()
                if now - last_update < .5 and data.get('status') != 'finished':
                    return
                last_update = now
                total = data.get('total_bytes') or data.get('total_bytes_estimate') or 0
                percent = round(100 * data.get('downloaded_bytes', 0) / total, 1) if total else None
                row.update(status='converting' if data.get('status') == 'finished' else 'downloading',
                           message='Converting to WAV…' if data.get('status') == 'finished' else f'Downloading {percent if percent is not None else ""}%')
                publish()
            row.update(status='downloading', message='Reading track metadata…')
            publish()
            try:
                with factory({**common, 'noplaylist': True, 'format': 'bestaudio/best',
                    'outtmpl': str(stage / 'audio.%(ext)s'), 'overwrites': True,
                    'progress_hooks': [progress],
                    'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'wav'}],
                    'postprocessor_args': {'extractaudio+ffmpeg_o': ['-ar', '48000', '-ac', '2', '-c:a', 'pcm_s16le']},
                    'match_filter': lambda info, **kwargs: 'Live streams are not dataset tracks.' if info.get('is_live') else None,
                }) as downloader:
                    info = downloader.extract_info('https://www.youtube.com/watch?v=' + identifier, download=True)
                check()
                audio = stage / 'audio.wav'
                if not info or not valid_wav(audio):
                    raise ValueError('No complete 48 kHz stereo WAV was produced.')
                artist, title, review = track_names(info, spec.get('fallback_artist', ''))
                stem = safe_name(artist + ' - ' + title)
                target = folder / (stem + '.wav')
                if target.exists():
                    target = folder / (stem + ' [' + identifier + '].wav')
                publish_wav(audio, target)
                record = {'id': identifier, 'artist': artist, 'title': title, 'album': info.get('album'),
                          'duration': info.get('duration'), 'source_url': 'https://www.youtube.com/watch?v=' + identifier,
                          'filename': target.name, 'bytes': target.stat().st_size, 'needs_name_review': review}
                manifest['tracks'][identifier] = record
                write_json(manifest_path, manifest)
                row.update(status='saved', filename=target.name,
                           message='Saved. Artist/title inferred; review filename.' if review else 'Saved.')
            except InterruptedError:
                raise
            except Exception as exc:
                row.update(status='failed', message=str(exc)[-1500:])
                print(f'{identifier}: {exc}', flush=True)
            publish()
        failures = sum(row['status'] == 'failed' for row in state['tracks'])
        state.update(status='complete_with_errors' if failures else 'complete',
                     message=f'Finished. {failures} failed; start again to retry. Completed WAVs will be skipped.' if failures else 'Finished. WAV files are ready in the dataset folder.')
    except InterruptedError as exc:
        state.update(status='cancelled', message=str(exc))
    except Exception as exc:
        state.update(status='failed', message=str(exc))
        print(str(exc), flush=True)
    finally:
        publish()


if __name__ == '__main__':
    run(sys.argv[1])
