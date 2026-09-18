"""Local WAV catalogue and read-only LRCLIB search; explicit, no-clobber lyric saves."""
import json
import math
from pathlib import Path
import re
import threading
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import wave

from .dataset_worker import track_names, publish_wav
from .lyric_files import matching_lyrics

_API = 'https://lrclib.net/api/search'
_NETWORK_LOCK = threading.Lock()
_LAST_REQUEST = 0.0


def dataset_folder(value):
    path = Path(str(value or '').strip())
    if not path.is_absolute() or not path.is_dir():
        raise ValueError('Enter an existing absolute dataset folder.')
    return path.resolve()


def audio_path(folder, filename):
    name = str(filename or '')
    path = folder / name
    if not name or Path(name).name != name or path.suffix.lower() != '.wav':
        raise ValueError('Select a WAV file from the loaded folder.')
    if path.resolve().parent != folder or path.is_symlink() or not path.is_file():
        raise ValueError('WAV file is missing or outside the dataset folder.')
    return path


def query_title(value):
    # Keep live/remix/version distinctions; remove only common upload decorations.
    return re.sub(r'\s*\((?:official\s+)?(?:audio|music video|video|lyric video|lyrics)\)\s*',
                  ' ', str(value), flags=re.I).strip()


def scan(data):
    folder = dataset_folder(data.get('folder'))
    manifest_path = folder / '.playlist-import/manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.is_file() else {}
    records = {r.get('filename'): r for r in manifest.get('tracks', {}).values()}
    tracks = []
    for path in sorted(folder.iterdir(), key=lambda p: p.name.casefold()):
        if path.suffix.lower() != '.wav' or not path.is_file() or path.is_symlink():
            continue
        record = records.get(path.name, {})
        artist, title, _ = track_names({'title':path.stem}, data.get('fallback_artist', ''))
        artist, title = record.get('artist') or artist, record.get('title') or title
        if artist == 'Unknown artist':
            artist = ''
        duration, error = None, ''
        try:
            with wave.open(str(path), 'rb') as audio:
                duration = audio.getnframes() / audio.getframerate()
        except (OSError, EOFError, wave.Error) as exc:
            error = 'Unable to read WAV duration: ' + str(exc)
        tracks.append({'filename':path.name, 'artist':artist, 'title':query_title(title),
                       'album':record.get('album') or '', 'duration':duration,
                       'exists':matching_lyrics(path).exists(), 'error':error})
    return {'folder':str(folder), 'tracks':tracks}


def request_records(artist, title):
    global _LAST_REQUEST
    request = urllib.request.Request(_API + '?' + urllib.parse.urlencode(
        {'artist_name':artist, 'track_name':title}),
        headers={'User-Agent':'YuE2-Studio-DatasetBuilder/1.0 (+https://github.com/vrgamegirl19/Yue2_Studio)',
                 'Accept':'application/json'})
    # Serialize requests across tabs, with a small courtesy delay.
    with _NETWORK_LOCK:
        time.sleep(max(0, .3 - (time.monotonic() - _LAST_REQUEST)))
        _LAST_REQUEST = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                raw = response.read(2_000_001)
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                raise ValueError('LRCLIB rate limit reached. Stop and retry later.') from exc
            raise ValueError(f'LRCLIB returned HTTP {exc.code}. Retry later.') from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ValueError('Could not reach LRCLIB. Check your connection and retry.') from exc
    if len(raw) > 2_000_000:
        raise ValueError('LRCLIB response was too large.')
    records = json.loads(raw)
    if not isinstance(records, list):
        raise ValueError('Unexpected LRCLIB response.')
    return records[:20]


def lyric_text(record):
    plain = record.get('plainLyrics')
    if isinstance(plain, str) and plain.strip():
        return plain.strip()
    synced = record.get('syncedLyrics')
    if not isinstance(synced, str):
        return ''
    lines = []
    for line in synced.splitlines():
        if re.match(r'^\[(?:ar|ti|al|by|offset|length):', line, flags=re.I):
            continue
        lines.append(re.sub(r'^(?:\[\d+:\d+(?:[.:]\d+)?\])+', '', line).strip())
    return '\n'.join(lines).strip()


def search(data):
    artist, title = str(data.get('artist') or '').strip(), str(data.get('title') or '').strip()
    if not artist or not title or max(len(artist), len(title)) > 300:
        raise ValueError('Enter artist and song title (up to 300 characters each).')
    duration = data.get('duration')
    if duration is not None and (not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0):
        raise ValueError('Invalid track duration.')
    results = []
    for record in request_records(artist, title):
        if not isinstance(record, dict):
            continue
        text = lyric_text(record)
        seconds = record.get('duration')
        delta = abs(seconds - duration) if duration and isinstance(seconds, (int, float)) and math.isfinite(seconds) else None
        exact = str(record.get('artistName', '')).casefold() == artist.casefold() and str(record.get('trackName', '')).casefold() == title.casefold()
        results.append({'id':record.get('id'), 'artist':record.get('artistName', ''),
                        'title':record.get('trackName', ''), 'album':record.get('albumName', ''),
                        'duration':seconds, 'duration_difference':round(delta, 1) if delta is not None else None,
                        'instrumental':bool(record.get('instrumental')), 'text':text,
                        'exact_names':exact})
    results.sort(key=lambda r: (not r['exact_names'], r['duration_difference'] if r['duration_difference'] is not None else float('inf')))
    return {'matches':results}


def save(data):
    folder = dataset_folder(data.get('folder'))
    audio = audio_path(folder, data.get('filename'))
    text = data.get('text')
    if not isinstance(text, str) or not text.strip() or '\x00' in text:
        raise ValueError('Lyrics must contain text.')
    if len((text.strip() + '\n').encode('utf-8')) > 65536:
        raise ValueError('Lyrics exceed the trainer limit of 64 KB.')
    target = audio.with_suffix('.lyrics.txt')
    existing = matching_lyrics(audio)
    if existing.exists() or existing.is_symlink():
        raise ValueError('A matching text file already exists; it was not overwritten: ' + existing.name)
    # Stage a complete file, then publish without replacing existing files.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n',
                dir=folder, prefix='.lyrics-', suffix='.tmp', delete=False) as output:
            temporary = Path(output.name)
            output.write(text.strip() + '\n')
        publish_wav(temporary, target)
    except FileExistsError as exc:
        raise ValueError('A matching text file already exists; it was not overwritten.') from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return {'filename':target.name, 'saved':True}
