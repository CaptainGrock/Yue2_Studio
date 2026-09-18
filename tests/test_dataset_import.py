import json
from pathlib import Path
import shutil
import subprocess
import wave

import pytest

from yue2_studio.dataset_import import DatasetImportManager, playlist_url, write_json
from yue2_studio.dataset_worker import run, safe_name, track_names, valid_wav, completed_path, publish_wav


def test_publish_preserves_existing_file(tmp_path):
    source, target = tmp_path/'audio.wav', tmp_path/'existing.wav'
    wav(source)
    target.write_bytes(b'user recording')
    with pytest.raises(FileExistsError):
        publish_wav(source, target)
    assert valid_wav(source)
    assert target.read_bytes() == b'user recording'


def test_windows_publish_does_not_need_hardlinks(tmp_path, monkeypatch):
    import os
    if os.name != 'nt':
        pytest.skip('Windows-specific exFAT regression')
    def unsupported(*args):
        raise OSError('Hard links unsupported')
    monkeypatch.setattr(os, 'link', unsupported)
    source, target = tmp_path/'audio.wav', tmp_path/'finished.wav'
    wav(source)
    publish_wav(source, target)
    assert valid_wav(target)
    assert not source.exists()


def wav(path):
    with wave.open(str(path), 'wb') as out:
        out.setparams((2, 2, 48000, 0, 'NONE', 'not compressed'))
        out.writeframes(b'\x00' * 1920)


def test_url():
    assert playlist_url('https://music.youtube.com/watch?v=abc&list=PL1234567890') == 'https://www.youtube.com/playlist?list=PL1234567890'
    for value in ['file:///tmp/x', 'https://evil.com/?list=PL1234567890', 'https://youtube.com/watch?v=123', 'https://user@youtube.com/?list=PL1234567890']:
        with pytest.raises(ValueError):
            playlist_url(value)


def test_names():
    assert track_names({'artist':'Band','track':'Song'}) == ('Band','Song',False)
    assert track_names({'title':'Band - Song'}) == ('Band','Song',True)
    assert track_names({'title':'Song'}) == ('Unknown artist','Song',True)
    assert safe_name('../CON: a?') == '_CON_ a_'
    assert safe_name('CON') == '_CON'


def test_fallback_artist():
    for title in ['02   Ultraviolence', '05  West Coast', '08  Money Power Glory']:
        song = title.split(maxsplit=1)[1]
        assert track_names({'title':title + ' - Ultraviolence (Deluxe Edition)'}, 'Lana Del Rey') == ('Lana Del Rey', song, True)
    assert track_names({'title':'Song'}, ' My Band ') == ('My Band','Song',True)
    assert track_names({'track':'Song'}, 'My Band') == ('My Band','Song',True)
    assert track_names({'artist':'Other Band','track':'Song'}, 'My Band') == ('Other Band','Song',False)
    assert track_names({'title':'My Band - Song'}, 'My Band') == ('My Band','Song',True)
    assert track_names({'title':'Other Band - Song'}, 'My Band') == ('Other Band','Song',True)
    assert track_names({'title':'Song'}, ' ') == ('Unknown artist','Song',True)


def test_manager_validation(tmp_path, monkeypatch):
    monkeypatch.setattr('yue2_studio.dataset_import.tools_status',lambda: {'yt_dlp':True})
    manager = DatasetImportManager(tmp_path/'runs')
    for folder in ['', 'relative', Path(tmp_path).anchor]:
        with pytest.raises(ValueError):
            manager.start({'url':'https://youtube.com/playlist?list=PL1234567890','folder':folder})
    assert not manager.busy()
    assert manager.cancel()['job'] is None


def test_manager_worker_exit(tmp_path, monkeypatch):
    write_json(tmp_path/'status.json', {'status':'starting','tracks':[]})
    commands = []
    class Process:
        def __init__(self, command, **kwargs): commands.append(command)
        def wait(self): return 1
    monkeypatch.setattr('yue2_studio.dataset_import.subprocess.Popen',Process)
    manager = DatasetImportManager(tmp_path)
    manager._run(tmp_path,False)
    assert json.loads((tmp_path/'status.json').read_text())['status'] == 'failed'
    assert commands[0][1:3] == ['-m','yue2_studio.dataset_worker']
    (tmp_path/'cancel.request').touch()
    manager._run(tmp_path,False)
    assert json.loads((tmp_path/'status.json').read_text())['status'] == 'cancelled'


def test_validation(tmp_path):
    file = tmp_path / 'song.wav'
    wav(file)
    assert valid_wav(file)
    record = {'filename':file.name,'bytes':file.stat().st_size}
    assert completed_path(tmp_path,record) == file
    assert completed_path(tmp_path,{'filename':'../song.wav'}) is None
    file.write_bytes(b'partial')
    assert not valid_wav(file)


def test_batch_failure_resume_collision(tmp_path):
    folder = tmp_path / 'dataset'
    folder.mkdir()
    original = folder / 'Band - Song.wav'
    original.write_bytes(b'user file')
    job = tmp_path / 'job'
    job.mkdir()
    write_json(job/'input.json', {'url':'https://www.youtube.com/playlist?list=PL1234567890','folder':str(folder)})
    calls = []
    class Fake:
        def __init__(self, options): self.options = options
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def extract_info(self,url,download):
            if not download:
                return {'title':'Test', 'entries':[{'id':'aaaaaaaaaaa','title':'Good'}, {'id':'bbbbbbbbbbb','title':'Bad'}, None]}
            calls.append(url)
            if url.endswith('bbbbbbbbbbb'): raise ValueError('Unavailable')
            wav(Path(self.options['outtmpl'].replace('%(ext)s','wav')))
            self.options['progress_hooks'][0]({'status':'finished'})
            return {'artist':'Band','track':'Song','album':'Album','duration':.01}
    run(job,Fake)
    result = json.loads((job/'status.json').read_text())
    assert result['status'] == 'complete_with_errors'
    assert [t['status'] for t in result['tracks']] == ['saved','failed','failed']
    assert original.read_bytes() == b'user file'
    assert valid_wav(folder/'Band - Song [aaaaaaaaaaa].wav')
    manifest = json.loads((folder/'.playlist-import/manifest.json').read_text())
    assert manifest['tracks']['aaaaaaaaaaa']['album'] == 'Album'
    run(job,Fake)
    result = json.loads((job/'status.json').read_text())
    assert result['tracks'][0]['status'] == 'skipped'
    assert len(calls) == 3
    (job/'cancel.request').touch()
    run(job,Fake)
    assert json.loads((job/'status.json').read_text())['status'] == 'cancelled'


def test_real_ffmpeg_conversion(tmp_path):
    pytest.importorskip('yt_dlp')
    if not shutil.which('ffmpeg'): pytest.skip('FFmpeg unavailable')
    from yt_dlp import YoutubeDL
    from yt_dlp.postprocessor.ffmpeg import FFmpegExtractAudioPP
    source = tmp_path/'audio.flac'
    subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','sine=frequency=440:duration=0.1',str(source)],check=True)
    with YoutubeDL({'quiet':True,'postprocessor_args':{'extractaudio+ffmpeg_o':['-ar','48000','-ac','2','-c:a','pcm_s16le']}}) as downloader:
        FFmpegExtractAudioPP(downloader,preferredcodec='wav').run({'filepath':str(source),'ext':'flac','vcodec':'none'})
    assert valid_wav(tmp_path/'audio.wav')


def test_offline_recovery(tmp_path):
    from yue2_studio.dataset_recovery import recover
    folder = tmp_path/'dataset'
    stage = folder/'.playlist-import'/'aaaaaaaaaaa'
    stage.mkdir(parents=True)
    source = stage/'audio.wav'
    target = folder/'Band - Song.wav'
    wav(source)
    job = tmp_path/'job'
    job.mkdir()
    write_json(job/'status.json', {'status':'complete_with_errors','folder':str(folder),'tracks':[
        {'id':'aaaaaaaaaaa','status':'failed','message':f'[WinError 1] Incorrect function: {str(source)!r} -> {str(target)!r}'},
        {'id':'bbbbbbbbbbb','status':'failed','message':'Video unavailable'}]})
    assert recover(job) == 1
    assert source.exists() and not target.exists()
    assert recover(job, apply=True) == 1
    assert valid_wav(target)
    assert (job/'status.before-recovery.json').exists()
    state = json.loads((job/'status.json').read_text())
    assert [row['status'] for row in state['tracks']] == ['saved','failed']
    manifest = json.loads((folder/'.playlist-import/manifest.json').read_text())
    assert completed_path(folder, manifest['tracks']['aaaaaaaaaaa']) == target
    assert recover(job, apply=True) == 0
