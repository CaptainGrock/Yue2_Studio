import json

import pytest

from yue2_studio import dataset_lyrics as lyrics
from yue2_studio.dataset_import import write_json
from test_dataset_import import wav


def test_scan_uses_metadata_and_detects_existing(tmp_path):
    wav(tmp_path/'Band - Song (Audio).wav')
    (tmp_path/'Band - Song (Audio).lyrics.txt').write_text('keep', encoding='utf-8')
    cache = tmp_path/'.playlist-import'
    cache.mkdir()
    write_json(cache/'manifest.json', {'tracks':{'id':{'filename':'Band - Song (Audio).wav','artist':'Actual Band','title':'Song (Audio)','album':'Album'}}})
    result = lyrics.scan({'folder':str(tmp_path)})
    row = result['tracks'][0]
    assert row['artist'] == 'Actual Band'
    assert row['title'] == 'Song'
    assert row['exists'] and row['duration'] > 0
    assert lyrics.query_title('Song (Live)') == 'Song (Live)'


def test_search_ranking_and_synced_fallback(monkeypatch):
    monkeypatch.setattr(lyrics, 'request_records', lambda a,t: [
        {'id':1,'artistName':'Other','trackName':'Song','duration':100,'plainLyrics':'wrong'},
        {'id':2,'artistName':'Band','trackName':'Song','duration':105,'syncedLyrics':'[ar:Band]\n[00:01.00]First line\n[00:02.00][00:03.00]Second line'},
        {'id':3,'artistName':'Band','trackName':'Song','duration':100,'instrumental':True}])
    results = lyrics.search({'artist':'Band','title':'Song','duration':101})['matches']
    assert [r['id'] for r in results] == [3,2,1]
    assert results[1]['text'] == 'First line\nSecond line'
    assert results[0]['instrumental']
    for data in [{'artist':'','title':'Song'}, {'artist':'Band','title':'Song','duration':float('nan')}]:
        with pytest.raises(ValueError): lyrics.search(data)


def test_save_no_overwrite_and_traversal(tmp_path):
    wav(tmp_path/'Band - Song.wav')
    data = {'folder':str(tmp_path),'filename':'Band - Song.wav','text':'Test fixture line\nSecond fixture line'}
    assert lyrics.save(data)['filename'] == 'Band - Song.lyrics.txt'
    assert (tmp_path/'Band - Song.lyrics.txt').read_text() == data['text'] + '\n'
    assert lyrics.scan({'folder':str(tmp_path)})['tracks'][0]['exists']
    with pytest.raises(ValueError, match='64 KB'):
        lyrics.save({**data,'text':'é' * 32768})
    with pytest.raises(ValueError,match='already exists'):
        lyrics.save({**data,'text':'replacement'})
    for filename in ['../other.wav', str(tmp_path.parent/'other.wav'), 'not-audio.json']:
        with pytest.raises(ValueError): lyrics.save({**data,'filename':filename})
    with pytest.raises(ValueError): lyrics.save({**data,'text':''})


def test_plain_txt_is_recognized_and_protected(tmp_path):
    wav(tmp_path/'Band - Song.wav')
    plain = tmp_path/'Band - Song.txt'
    plain.write_text('Existing words', encoding='utf-8')
    assert lyrics.scan({'folder':str(tmp_path)})['tracks'][0]['exists']
    with pytest.raises(ValueError, match='already exists'):
        lyrics.save({'folder':str(tmp_path),'filename':'Band - Song.wav','text':'Other words'})
    assert plain.read_text() == 'Existing words'
    assert not (tmp_path/'Band - Song.lyrics.txt').exists()


def test_request_parameters_and_rate_limit(monkeypatch):
    class Response:
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def read(self, size): return b'[]'
    seen = []
    def open_request(request,timeout):
        seen.append(request)
        return Response()
    monkeypatch.setattr(lyrics.urllib.request, 'urlopen', open_request)
    monkeypatch.setattr(lyrics.time, 'sleep', lambda _:None)
    assert lyrics.request_records('Band & Friends','A Song') == []
    url = seen[0].full_url
    assert url.startswith('https://lrclib.net/api/search?')
    assert 'artist_name=Band+%26+Friends' in url and 'track_name=A+Song' in url
    assert seen[0].get_header('User-agent').startswith('YuE2-Studio')
    def limited(*args,**kwargs):
        raise lyrics.urllib.error.HTTPError(url,429,'Too many requests',{},None)
    monkeypatch.setattr(lyrics.urllib.request,'urlopen',limited)
    with pytest.raises(ValueError,match='rate limit'): lyrics.request_records('Band','Song')
