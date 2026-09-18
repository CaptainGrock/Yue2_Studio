"""CPU-only playlist imports, isolated from Studio's GPU job queue."""
import importlib.util
from functools import lru_cache
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
from urllib.parse import urlsplit, parse_qs
import uuid

from .settings import ROOT


def playlist_url(value):
    url = urlsplit(str(value).strip())
    if url.scheme != 'https' or url.hostname not in ('youtube.com', 'www.youtube.com', 'music.youtube.com', 'm.youtube.com') or url.username or url.password:
        raise ValueError('Enter an HTTPS YouTube playlist URL.')
    identifier = parse_qs(url.query).get('list', [''])[0]
    if not re.fullmatch(r'[A-Za-z0-9_-]{10,200}', identifier):
        raise ValueError('The YouTube URL must contain a playlist ID (list=...).')
    return 'https://www.youtube.com/playlist?list=' + identifier


def write_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


@lru_cache(maxsize=1)
def javascript_runtime():
    candidates = [('deno', shutil.which('deno'), (2, 3, 0))]
    candidates += [('node', str(path), (22, 0, 0)) for path in sorted((ROOT/'tools/dataset-runtime').glob('node-*/node.exe'), reverse=True)]
    candidates.append(('node', shutil.which('node'), (22, 0, 0)))
    for name, executable, minimum in candidates:
        if not executable:
            continue
        try:
            result = subprocess.run([executable, '--version'], capture_output=True, text=True, timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            match = re.search(r'(\d+)\.(\d+)\.(\d+)', result.stdout)
            if result.returncode == 0 and match and tuple(map(int, match.groups())) >= minimum:
                return {name: {'path': executable}}
        except (OSError, subprocess.TimeoutExpired):
            pass
    return {}


def tools_status():
    return {'yt_dlp': importlib.util.find_spec('yt_dlp') is not None,
            'ffmpeg': bool(shutil.which('ffmpeg')), 'ffprobe': bool(shutil.which('ffprobe')),
            'javascript': bool(javascript_runtime())}


class DatasetImportManager:
    def __init__(self, root=None):
        self.root = Path(root or ROOT / 'runs/dataset-imports')
        self.lock = threading.RLock()
        self.process = None
        self.thread = None
        self.current = None

    def busy(self):
        with self.lock:
            return bool(self.thread and self.thread.is_alive())

    def status(self):
        with self.lock:
            job = None
            if self.current:
                try:
                    job = json.loads((self.current / 'status.json').read_text(encoding='utf-8'))
                except (OSError, ValueError):
                    job = {'status': 'starting', 'tracks': []}
            return {'tools': tools_status(), 'busy': self.busy(), 'job': job,
                    'default_folder': str(ROOT / 'datasets/youtube-playlist')}

    def start(self, data, install=False):
        spec = {'action': 'install' if install else 'download'}
        if not install:
            spec['url'] = playlist_url(data.get('url', ''))
            spec['fallback_artist'] = str(data.get('fallback_artist') or '').strip()
            if len(spec['fallback_artist']) > 200:
                raise ValueError('Fallback artist must be 200 characters or fewer.')
            folder = str(data.get('folder', '')).strip()
            if not folder or not Path(folder).is_absolute():
                raise ValueError('Choose an absolute dataset folder path.')
            spec['folder'] = str(Path(folder).resolve())
            if Path(spec['folder']) == Path(Path(spec['folder']).anchor) or Path(spec['folder']) == ROOT:
                raise ValueError('Choose a dataset subfolder.')
            missing = [name for name, present in tools_status().items() if not present]
            if missing:
                raise ValueError('Missing tools: ' + ', '.join(missing) + '. See setup instructions below.')
        with self.lock:
            if self.busy():
                raise ValueError('A dataset import or tool installation is already running.')
            self.current = self.root / uuid.uuid4().hex
            self.current.mkdir(parents=True)
            write_json(self.current / 'input.json', spec)
            write_json(self.current / 'status.json', {'status': 'starting', 'tracks': []})
            self.thread = threading.Thread(target=self._run, args=(self.current, install), daemon=True)
            self.thread.start()
        return self.status()

    def _run(self, directory, install):
        try:
            command = ([sys.executable, '-m', 'pip', 'install', '--upgrade', 'yt-dlp[default]'] if install else
                       [sys.executable, '-m', 'yue2_studio.dataset_worker', str(directory)])
            env = os.environ.copy()
            env['PYTHONPATH'] = str(Path(__file__).resolve().parents[1]) + os.pathsep + env.get('PYTHONPATH', '')
            env.update(PYTHONUTF8='1', PYTHONUNBUFFERED='1')
            with (directory / 'run.log').open('w', encoding='utf-8') as log:
                with self.lock:
                    if (directory / 'cancel.request').exists():
                        raise InterruptedError('Cancelled before starting.')
                    self.process = subprocess.Popen(command, env=env, stdout=log, stderr=subprocess.STDOUT,
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
                        start_new_session=os.name != 'nt')
                code = self.process.wait()
            value = json.loads((directory / 'status.json').read_text(encoding='utf-8'))
            if (directory / 'cancel.request').exists():
                value.update(status='cancelled', message='Cancelled. Completed WAVs are kept; start again to resume.')
            elif install:
                value.update(status='complete' if code == 0 else 'failed', message='Downloader installed.' if code == 0 else 'Installation failed.')
            elif code and value.get('status') not in ('failed', 'cancelled'):
                value.update(status='failed', message='Importer exited unexpectedly.')
            value['log'] = str(directory / 'run.log')
            write_json(directory / 'status.json', value)
        except Exception as exc:
            write_json(directory / 'status.json', {'status': 'cancelled' if isinstance(exc, InterruptedError) else 'failed',
                       'message': str(exc), 'tracks': [], 'log': str(directory / 'run.log')})
        finally:
            with self.lock:
                self.process = None

    def cancel(self):
        with self.lock:
            if self.busy():
                (self.current / 'cancel.request').touch()
                if self.process and self.process.poll() is None:
                    if os.name == 'nt':
                        subprocess.run(['taskkill', '/PID', str(self.process.pid), '/T', '/F'],
                            capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
                    else:
                        import signal
                        os.killpg(self.process.pid, signal.SIGTERM)
        return self.status()
