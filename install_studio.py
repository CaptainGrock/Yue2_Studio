"""Install the Studio overlay into the parent YuE2 source checkout; standard library only."""
import argparse
import hashlib
from datetime import datetime
from pathlib import Path
import re
import shutil
import socket
import sys

REPO = Path(__file__).resolve().parent
UPSTREAM_PIPELINE_SHA256 = '48eda878c0af5b101a2f48f62c0d12ffb40db91c902b831bab1082be13c4af44'
STYLE_PIPELINE_SHA256 = 'f705cbd95cefbd65303511510a228dde345125bd0c2c50255d3f35fa3586358b'


def code_hash(path):
    return hashlib.sha256(path.read_text(encoding='utf-8').encode('utf-8')).hexdigest()


def install(target, check=False):
    target = Path(target).resolve()
    if target == REPO or target.is_relative_to(REPO):
        raise ValueError('Target must be the existing YuE2 folder outside this add-on.')
    project = target/'pyproject.toml'
    if not project.is_file() or not (target/'src/yue2/pipeline.py').is_file():
        raise ValueError('No YuE2 source installation found. Clone this add-on INSIDE the installed YuE2 folder.')
    metadata = project.read_text(encoding='utf-8')
    if not re.search(r'name\s*=\s*"yue2-infer"',metadata) or not re.search(r'version\s*=\s*"0\.1\.6"',metadata):
        raise ValueError('This add-on is tested with yue2-infer 0.1.6. See README compatibility instructions.')
    # This feature needs engine hooks, not only UI files. Refuse to overwrite
    # an unreviewed/local pipeline even when its package version is still 0.1.6.
    pipeline = target/'src/yue2/pipeline.py'
    if code_hash(pipeline) not in {UPSTREAM_PIPELINE_SHA256,STYLE_PIPELINE_SHA256,code_hash(REPO/'src/yue2/pipeline.py')}:
        raise ValueError('YuE2 pipeline differs from the tested upstream or this Studio overlay. Use a clean checkout of upstream commit 92a73cc7652fcc1f937855e4b765e0a0edd7ff2e; preserve and review your custom engine changes first.')
    adapter = target/'src/yue2/lora.py'
    if adapter.exists() and code_hash(adapter)!=code_hash(REPO/'src/yue2/lora.py'):
        raise ValueError('Existing lora.py contains different changes. Preserve and review it before installing this overlay.')
    artist_adapter=target/'src/yue2/artist_lora.py'
    if artist_adapter.exists() and code_hash(artist_adapter)!=code_hash(REPO/'src/yue2/artist_lora.py'):
        raise ValueError('Existing artist_lora.py contains different changes. Preserve and review it before installing this overlay.')
    files = [REPO/'launch_studio.py', REPO/'src/yue2/cuda_graph.py', REPO/'src/yue2/pipeline.py', REPO/'src/yue2/lora.py', REPO/'docs/studio.md', REPO/'docs/settings.md', REPO/'docs/gguf.md', REPO/'docs/trainer.md', REPO/'docs/lora.md']
    files.extend(sorted((REPO/'images').glob('*.png')))
    files.extend([REPO/'src/yue2/artist_lora.py',REPO/'docs/artist-setup.md',REPO/'docs/artist-trainer.md'])
    for base in ('src/yue2_studio','skills/yue2-music/scripts'):
        files.extend(p for p in (REPO/base).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix in {'.py','.json','.md','.html','.js','.css','.svg'})
    changes=[]
    for source in files:
        relative=source.relative_to(REPO);dest=target/relative
        if not dest.resolve().is_relative_to(target):
            raise ValueError(f'Install path escapes YuE2 folder: {relative}')
        if not dest.is_file() or dest.read_bytes()!=source.read_bytes():
            changes.append((source,dest,relative))
    print(f'YuE2: {target}\nFiles needing installation/update: {len(changes)}')
    if check or not changes:return len(changes)
    # Do not replace Python code underneath a live default-port Studio.
    try:
        with socket.create_connection(('127.0.0.1',7862),timeout=.5):
            raise ValueError('Port 7862 is in use. Finish active work and stop Studio before installing updates.')
    except OSError:
        pass
    backup=target/'.studio-backups'/datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    for source,dest,relative in changes:
        if dest.is_file():
            saved=backup/relative;saved.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(dest,saved)
        dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,dest)
    print(f'Installed. Replaced files backed up under {backup}')
    return len(changes)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target',type=Path,default=REPO.parent)
    parser.add_argument('--check',action='store_true',help='Validate installation and list change count without writing')
    args=parser.parse_args()
    try:install(args.target,args.check)
    except (ValueError,OSError) as exc:print(f'Install failed: {exc}',file=sys.stderr);sys.exit(1)
