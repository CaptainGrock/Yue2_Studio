"""Supervise the user's local LLM server (llama.cpp) alongside Studio's lifecycle.
Best-effort companion: a missing or failing LLM server never blocks Studio itself."""
from __future__ import annotations

import atexit
import os
import time
from pathlib import Path
import subprocess
import urllib.error
import urllib.request

# Defaults; override with environment variables. YUE2_LLM_BAT=0 disables the companion.
BAT = Path(os.environ.get('YUE2_LLM_BAT') or r'C:\Stable\LMRunner\start_server.bat')
PORT = int(os.environ.get('YUE2_LLM_PORT', '1234'))
PING_TIMEOUT = 1.0

_proc: subprocess.Popen | None = None
_released = False  # a managed server was stopped for a render and may be revived


def alive(timeout=PING_TIMEOUT):
    """True when something already serves the LLM port (not necessarily something we started)."""
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{PORT}/v1/models', timeout=timeout):
            return True
    except urllib.error.HTTPError:
        return True  # any HTTP answer means a server owns the port
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


def start():
    """Launch the configured LLM server script unless its port is already served."""
    global _proc
    if _proc is not None or os.environ.get('YUE2_LLM_BAT', '').strip() == '0':
        return
    if alive():
        print(f'LLM server already running on port {PORT}.', flush=True)
        return
    if not BAT.is_file():
        print(f'LLM server script not found ({BAT}); skipping companion start.', flush=True)
        return
    try:
        # DETACHED_PROCESS keeps cmd off Studio's console. The bat runs llama-server in the
        # foreground, so the recorded pid's process tree contains the server for its whole
        # lifetime — that is what makes stop() below reliable.
        _proc = subprocess.Popen(['cmd', '/c', str(BAT)], cwd=str(BAT.parent), env={**os.environ, 'PORT': str(PORT)},
                                 creationflags=0x00000008,  # DETACHED_PROCESS
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
        atexit.register(stop)
        print(f'Starting LLM server from {BAT} (port {PORT}); it needs a moment to load.', flush=True)
    except OSError as exc:
        print(f'Could not start LLM server script: {exc}', flush=True)


def ensure():
    """Revive a companion server that release_for_render() stopped, before LLM use."""
    global _released, _proc
    if not _released:
        return
    _released = False
    if _proc is not None and _proc.poll() is not None:
        _proc = None  # it crashed on its own earlier; allow a fresh start
    if alive():
        print(f'LLM server already answering on port {PORT}; no revive needed.', flush=True)
        return
    start()


def release_for_render(wait=25.0):
    """Stop a companion-started LLM server so music generation gets the whole GPU.

    This llama.cpp build keeps a startup-loaded model resident until the process
    exits, so stopping the process is the reliable way to free VRAM. Servers we
    did not start are never touched. Returns a human-readable status string."""
    global _released, _proc
    if _proc is None or _proc.poll() is not None:
        _proc = None
        return 'LLM server was not running; GPU already free.'
    proc, _proc = _proc, None
    _released = True  # the next LLM request may bring it back
    try:
        subprocess.run(['taskkill', '/T', '/F', '/PID', str(proc.pid)],
                       capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        pass
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if not alive():
            print('LLM server stopped; GPU memory freed for music generation.', flush=True)
            return 'LLM server stopped to free GPU memory for music generation.'
        time.sleep(0.5)
    print('LLM server stop requested but the port is still answering.', flush=True)
    return 'LLM server stop was requested but its port is still answering.'


def stop():
    """Stop the LLM server only when this Studio process started it."""
    global _proc
    if _proc is None:
        return
    proc, _proc = _proc, None
    if proc.poll() is not None:
        return
    try:
        # /T takes the whole tree (cmd and llama-server); /F because llama-server has no
        # console handler, so a plain WM_CLOSE could never reach it.
        subprocess.run(['taskkill', '/T', '/F', '/PID', str(proc.pid)],
                       capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        pass


def running():
    """Companion status for logging: port served, and by a process we started?"""
    return {'port': PORT, 'alive': alive(), 'managed': _proc is not None}
