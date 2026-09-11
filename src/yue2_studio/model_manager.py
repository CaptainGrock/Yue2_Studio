"""Allowlisted, pinned GGUF downloads with atomic publication and cancellation."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import urllib.request

from .settings import ROOT, detected_gguf_executable

CATALOG = json.loads(Path(__file__).with_name('gguf_catalog.json').read_text())
VARIANTS = {'q4': ('Q4', 'yue2-3b-q4_0.gguf', 'Smallest weights; quality can differ. Not necessarily faster.'),
            'q8': ('Q8', 'yue2-3b-q8_0.gguf', 'Balanced choice. Tested locally with CUDA on RTX 5090.'),
            'bf16': ('BF16', 'yue2-3b-bf16.gguf', 'Unquantized main weights. Larger download and memory use; not locally tested.')}


class ModelManager:
    def __init__(self, root=None):
        self.root = Path(root or ROOT/'models/Yue2-3B-GGUF').resolve()
        self.lock = threading.RLock()
        self.cancel_event = threading.Event()
        self.thread = None
        self.transfer = {'status': 'idle', 'bytes': 0, 'total': 0, 'file': '', 'error': ''}
        self.gpu = None
        try:
            result = subprocess.run(['nvidia-smi','--query-gpu=name,memory.total','--format=csv,noheader,nounits'],
                capture_output=True,text=True,timeout=3,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            name, memory = result.stdout.splitlines()[0].rsplit(',',1)
            self.gpu = {'name':name.strip(), 'memory_mib':int(memory.strip())}
        except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
            pass

    def files(self, variant):
        if variant not in VARIANTS:
            raise ValueError('Choose Q4, Q8, or BF16.')
        return [VARIANTS[variant][1], 'yue2-vae-f16.gguf', *[p for p in CATALOG['files'] if p.startswith('sidecars/')]]

    def target(self, name):
        path = self.root/name
        if not path.resolve().is_relative_to(self.root):
            raise ValueError('Model path escapes the download folder.')
        return path

    def busy(self):
        with self.lock:
            return self.transfer['status'] in ('downloading','verifying','cancelling') or bool(self.thread and self.thread.is_alive())

    def update(self, **changes):
        with self.lock:
            self.transfer.update(changes)

    def status(self):
        variants = []
        for key,(label,main,note) in VARIANTS.items():
            names = self.files(key)
            present = [n for n in names if self.target(n).is_file() and self.target(n).stat().st_size==CATALOG['files'][n]['size']]
            variants.append({'id':key,'label':label,'main':main,'note':note,'installed':len(present)==len(names),
                'total_bytes':sum(CATALOG['files'][n]['size'] for n in names),
                'missing_bytes':sum(CATALOG['files'][n]['size'] for n in names if n not in present)})
        with self.lock:
            transfer = deepcopy(self.transfer)
        return {'variants':variants,'transfer':transfer,'model_dir':str(self.root),
                'executable':detected_gguf_executable(),'gpu':self.gpu,
                'suggested':'q4' if self.gpu and self.gpu['memory_mib']<12288 else 'q8'}

    def start(self, variant):
        names = self.files(variant)
        with self.lock:
            if self.busy():
                raise ValueError('A model download is already active.')
            self.root.mkdir(parents=True,exist_ok=True)
            required = sum(CATALOG['files'][n]['size'] for n in names if not self.target(n).is_file())
            if shutil.disk_usage(self.root).free < required + 512*1024**2:
                raise ValueError('Not enough free disk space for this model bundle.')
            self.cancel_event.clear()
            self.transfer = {'status':'verifying','variant':variant,'bytes':0,
                'total':sum(CATALOG['files'][n]['size'] for n in names),'file':'','error':''}
            self.thread = threading.Thread(target=self._download,args=(names,),daemon=True)
            self.thread.start()
        return self.status()

    def cancel(self):
        with self.lock:
            if self.busy():
                self.cancel_event.set()
                self.transfer['status']='cancelling'
        return self.status()

    def check_cancel(self):
        if self.cancel_event.is_set():
            raise InterruptedError('Download cancelled. Completed files are kept; retry restarts the unfinished file.')

    def digest(self, path, meta):
        hasher = hashlib.sha256() if meta['sha256'] else hashlib.sha1(b'blob '+str(meta['size']).encode()+b'\0')
        with path.open('rb') as source:
            while chunk := source.read(4*1024**2):
                self.check_cancel()
                hasher.update(chunk)
        return hasher.hexdigest() == (meta['sha256'] or meta['git_oid'])

    def _download(self, names):
        done = 0
        temporary = None
        try:
            for name in names:
                self.check_cancel()
                target = self.target(name); meta = CATALOG['files'][name]
                self.update(status='verifying',file=name,bytes=done)
                if target.is_file() and target.stat().st_size==meta['size'] and self.digest(target,meta):
                    done += meta['size']; self.update(bytes=done); continue
                if shutil.disk_usage(self.root).free < meta['size']+64*1024**2:
                    raise ValueError('Not enough disk space to download '+name)
                target.parent.mkdir(parents=True,exist_ok=True)
                temporary = self.target(name+'.studio-part')
                url = f"https://huggingface.co/{CATALOG['repo']}/resolve/{CATALOG['revision']}/{name}"
                self.update(status='downloading')
                received = 0
                # No API key or ambient Hugging Face credentials are sent.
                with urllib.request.urlopen(url,timeout=30) as response, temporary.open('wb') as output:
                    while True:
                        self.check_cancel()
                        chunk = response.read(1024**2)
                        if not chunk: break
                        received += len(chunk)
                        if received > meta['size']: raise ValueError('Unexpected download size: '+name)
                        output.write(chunk); self.update(bytes=done+received)
                if received != meta['size']: raise ValueError('Incomplete download: '+name+'. Retry to download it again.')
                self.update(status='verifying')
                if not self.digest(temporary,meta): raise ValueError('Checksum verification failed: '+name)
                self.check_cancel()
                temporary.replace(target); temporary = None
                done += meta['size']; self.update(bytes=done)
            self.check_cancel()
            self.update(status='complete',file='',bytes=done)
        except InterruptedError as exc:
            self.update(status='cancelled',error=str(exc))
        except Exception as exc:
            self.update(status='failed',error=str(exc))
        finally:
            if temporary is not None:
                try: temporary.unlink(missing_ok=True)
                except OSError: pass
