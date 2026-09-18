"""Automatic Artist Trainer lyric-cleaning contracts."""
import hashlib
import json

import pytest

from yue2_studio.artist_lyrics import clean_lyrics, clean_project, write_cleaning_artifacts


@pytest.mark.parametrize(('source', 'expected'), [
    ('diamanté', 'diamante'),
    ('word\u3164word', 'wordword'),
    ('acción', 'accion'),
    ('Château', 'Chateau'),
    ('Medellín', 'Medellin'),
    ('cariño', 'carino'),
    ('“Wait—don’t…”', '"Wait-don\'t..."'),
    ('hello \U0001f3b5 world', 'hello  world'),
])
def test_clean_lyrics_repairs_known_alignment_failures(source, expected):
    cleaned, changes = clean_lyrics('[Verse]\n' + source)
    assert cleaned == '[Verse]\n' + expected
    assert changes
    assert all(change['line'] == 2 for change in changes)
    assert all(change['codepoints'] and change['reason'] for change in changes)


def test_clean_lyrics_reports_exact_location_and_preserves_input():
    source = '[Verse]\nSing cariño\u3164'
    cleaned, changes = clean_lyrics(source)
    assert source == '[Verse]\nSing cariño\u3164'
    assert cleaned == '[Verse]\nSing carino'
    assert [(change['line'], change['column'], change['codepoints']) for change in changes] == [
        (2, 10, ['U+00F1']),
        (2, 12, ['U+3164']),
    ]


def test_non_latin_letters_require_alignment_off():
    with pytest.raises(ValueError, match='alignment weight 0'):
        clean_lyrics('[Verse]\nПривет')
    cleaned, changes = clean_lyrics('[Verse]\nПривет\u200b', require_ascii=False)
    assert cleaned == '[Verse]\nПривет'
    assert changes[0]['codepoints'] == ['U+200B']


def _project():
    lyrics = '[Verse]\nSing cariño\u3164'
    return {
        'name': 'Artist',
        'tracks': [
            {'name': 'one.wav', 'enabled': True, 'lyrics_name': 'one.lyrics.txt',
             'lyrics': lyrics, 'lyrics_sha256': hashlib.sha256(lyrics.encode()).hexdigest(),
             'lyrics_bytes': len(lyrics.encode()), 'lyrics_mtime_ns': '123'},
            {'name': 'two.wav', 'enabled': False, 'lyrics_name': 'two.lyrics.txt',
             'lyrics': 'untouched café', 'lyrics_sha256': 'a' * 64,
             'lyrics_bytes': 14, 'lyrics_mtime_ns': '456'},
        ],
    }


def test_clean_project_freezes_cleaned_copy_and_source_identity():
    project = _project()
    frozen, report = clean_project(project, [project['tracks'][0]], require_ascii=True)
    original = project['tracks'][0]
    cleaned = frozen['tracks'][0]
    assert original['lyrics'].endswith('cariño\u3164')
    assert cleaned['lyrics'].endswith('carino')
    assert cleaned['source_lyrics_sha256'] == original['lyrics_sha256']
    assert cleaned['lyrics_sha256'] == hashlib.sha256(cleaned['lyrics'].encode()).hexdigest()
    assert frozen['tracks'][1]['lyrics'] == 'untouched café'
    assert report['songs_checked'] == report['songs_changed'] == 1
    assert report['changes_total'] == 2


def test_cleaning_artifacts_preserve_source_and_record_changes(tmp_path):
    project = _project()
    source = tmp_path / 'source' / 'one.lyrics.txt'
    source.parent.mkdir()
    source.write_text(project['tracks'][0]['lyrics'], encoding='utf-8')
    before = source.read_bytes()
    frozen, report = clean_project(project, [project['tracks'][0]], require_ascii=True)
    run = tmp_path / 'run'
    write_cleaning_artifacts(frozen, report, run)
    assert source.read_bytes() == before
    assert (run / 'result/cleaned-lyrics/one.lyrics.txt').read_text(encoding='utf-8').endswith('carino')
    receipt = json.loads((run / 'result/lyrics-cleaning.json').read_text(encoding='utf-8'))
    assert receipt['songs'][0]['changes'][0]['codepoints'] == ['U+00F1']
    log = (run / 'result/lyrics-cleaning.log').read_text(encoding='utf-8')
    assert 'one.wav' in log and 'U+00F1' in log and 'U+3164' in log


def test_cleaning_artifact_rejects_unsafe_sidecar_name(tmp_path):
    project = _project()
    frozen, report = clean_project(project, [project['tracks'][0]], require_ascii=True)
    frozen['tracks'][0]['lyrics_name'] = '../outside.txt'
    with pytest.raises(ValueError, match='Invalid cleaned lyric filename'):
        write_cleaning_artifacts(frozen, report, tmp_path / 'run')
