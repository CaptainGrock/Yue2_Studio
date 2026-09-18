"""Deterministic lyric cleaning for frozen Artist Trainer jobs."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import unicodedata

from .jobs import write_json


POLICY = 'artist-lyrics-ascii-v1'
PUNCTUATION = {
    '\u2018': "'", '\u2019': "'", '\u201a': "'", '\u201b': "'",
    '\u201c': '"', '\u201d': '"', '\u201e': '"', '\u201f': '"',
    '\u2010': '-', '\u2011': '-', '\u2012': '-', '\u2013': '-', '\u2014': '-', '\u2212': '-',
    '\u2026': '...', '\u2044': '/', '\u00b7': '.',
}
LATIN = {
    'Æ': 'AE', 'æ': 'ae', 'Œ': 'OE', 'œ': 'oe', 'Ø': 'O', 'ø': 'o',
    'Ð': 'D', 'ð': 'd', 'Þ': 'Th', 'þ': 'th', 'Ł': 'L', 'ł': 'l',
    'Đ': 'D', 'đ': 'd', 'Ħ': 'H', 'ħ': 'h', 'ı': 'i', 'Ŋ': 'N', 'ŋ': 'n', 'ß': 'ss',
}
INVISIBLE = {'\ufeff', '\u200b', '\u200c', '\u200d', '\u2060', '\u00ad', '\u3164', '\u115f', '\u1160'}


def _replacement(char, require_ascii):
    code = ord(char)
    category = unicodedata.category(char)
    if char == '\n' or 32 <= code <= 126:
        return char, ''
    if char == '\t' or category.startswith('Z'):
        return ' ', 'normalized whitespace'
    if char == '\r':
        return '\n', 'normalized line ending'
    if char in INVISIBLE or category in ('Cf', 'Cc', 'Cs', 'Co', 'Cn'):
        return '', 'removed invisible/control character'
    if char in PUNCTUATION:
        return PUNCTUATION[char], 'normalized punctuation'
    if char in LATIN:
        return LATIN[char], 'transliterated Latin letter'
    normalized = unicodedata.normalize('NFKD', char)
    ascii_value = ''.join(c for c in normalized if ord(c) < 128 and not unicodedata.category(c).startswith('M'))
    if ascii_value:
        return ascii_value, 'transliterated Unicode character'
    if category.startswith('M'):
        return '', 'removed combining mark'
    if char.isalpha():
        if require_ascii:
            name = unicodedata.name(char, 'UNKNOWN')
            raise ValueError(f'Automatic lyric cleaning cannot safely convert {char!r} (U+{code:04X} {name}) to the English letters required by lyric alignment. Accents and invisible characters are cleaned automatically; use alignment weight 0 only for genuinely non-Latin lyrics.')
        return char, ''
    return '', 'removed unsupported symbol'


def clean_lyrics(text, *, require_ascii=True):
    """Return cleaned text and an exact character-level change receipt."""
    if not isinstance(text, str) or not text.strip() or '\x00' in text:
        raise ValueError('Lyrics must contain valid text before automatic cleaning.')
    output, changes = [], []
    line = column = 1
    index = 0
    while index < len(text):
        char = text[index]
        if char == '\r' and index + 1 < len(text) and text[index + 1] == '\n':
            replacement, reason = '\n', 'normalized line ending'
            consumed = 2
            original = '\r\n'
        else:
            replacement, reason = _replacement(char, require_ascii)
            consumed = 1
            original = char
        output.append(replacement)
        if original != replacement:
            changes.append({
                'line': line, 'column': column,
                'original': original, 'replacement': replacement,
                'codepoints': ['U+' + f'{ord(c):04X}' for c in original],
                'names': [unicodedata.name(c, 'UNKNOWN') for c in original],
                'reason': reason,
            })
        for consumed_char in original:
            if consumed_char == '\n':
                line, column = line + 1, 1
            elif consumed_char != '\r':
                column += 1
        index += consumed
    cleaned = ''.join(output)
    if not re.search(r'[A-Za-z]', cleaned) and require_ascii:
        raise ValueError('Automatic lyric cleaning produced no English lyric letters.')
    if require_ascii and any(c.isalpha() and c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ' for c in cleaned):
        raise ValueError('Automatic lyric cleaning left unsupported non-English letters.')
    return cleaned, changes


def clean_project(project, selected, *, require_ascii):
    """Freeze one cleaned project copy while retaining source-integrity fields."""
    value = deepcopy(project)
    selected_names = {row['name'] for row in selected}
    entries = []
    for row in value.get('tracks', []):
        if row.get('name') not in selected_names:
            continue
        cleaned, changes = clean_lyrics(row.get('lyrics'), require_ascii=require_ascii)
        original_hash = row.get('lyrics_sha256')
        if not isinstance(original_hash, str) or not re.fullmatch(r'[a-f0-9]{64}', original_hash):
            raise ValueError('Saved artist setup has an invalid source lyric hash: ' + str(row.get('name')))
        cleaned_raw = cleaned.encode('utf-8')
        cleaned_hash = hashlib.sha256(cleaned_raw).hexdigest()
        row.update(
            source_lyrics_sha256=original_hash,
            source_lyrics_bytes=row.get('lyrics_bytes'),
            source_lyrics_mtime_ns=row.get('lyrics_mtime_ns'),
            lyrics=cleaned,
            lyrics_sha256=cleaned_hash,
            lyrics_bytes=len(cleaned_raw),
            lyrics_cleaning_policy=POLICY,
        )
        entries.append({
            'audio': row['name'], 'lyrics_file': row.get('lyrics_name'),
            'source_sha256': original_hash, 'cleaned_sha256': cleaned_hash,
            'changed': bool(changes), 'changes': changes,
        })
    if len(entries) != len(selected_names):
        raise ValueError('Saved artist setup is missing a selected song during lyric cleaning.')
    report = {
        'schema': 1, 'policy': POLICY, 'require_ascii_letters': require_ascii,
        'songs_checked': len(entries),
        'songs_changed': sum(entry['changed'] for entry in entries),
        'changes_total': sum(len(entry['changes']) for entry in entries),
        'songs': entries,
    }
    value['lyrics_cleaning'] = {key: report[key] for key in ('schema', 'policy', 'require_ascii_letters', 'songs_checked', 'songs_changed', 'changes_total')}
    return value, report


def write_cleaning_artifacts(project, report, directory):
    """Persist cleaned sidecars and human/machine-readable receipts before GPU work."""
    result = Path(directory) / 'result'
    cleaned_folder = result / 'cleaned-lyrics'
    cleaned_folder.mkdir(parents=True, exist_ok=True)
    selected = {entry['audio']: entry for entry in report['songs']}
    lines = [
        f"Policy: {report['policy']}",
        f"Songs checked: {report['songs_checked']}",
        f"Songs changed: {report['songs_changed']}",
        f"Character changes: {report['changes_total']}",
    ]
    for row in project['tracks']:
        if row.get('name') not in selected:
            continue
        name = str(row.get('lyrics_name') or '')
        if not name or Path(name).name != name:
            raise ValueError('Invalid cleaned lyric filename.')
        target = cleaned_folder / name
        target.write_text(row['lyrics'], encoding='utf-8', newline='')
        entry = selected[row['name']]
        lines.append(f"\n{row['name']}: {len(entry['changes'])} change(s)")
        for change in entry['changes']:
            original = json.dumps(change['original'], ensure_ascii=False)
            replacement = json.dumps(change['replacement'], ensure_ascii=False)
            lines.append(f"  line {change['line']}, column {change['column']}: {original} -> {replacement} ({' '.join(change['codepoints'])}; {change['reason']})")
    write_json(result / 'lyrics-cleaning.json', report)
    (result / 'lyrics-cleaning.log').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f"[YuE2] Automatic lyric cleaning: {report['songs_changed']}/{report['songs_checked']} songs changed, {report['changes_total']} character changes. See result/lyrics-cleaning.log", flush=True)
    for line in lines[4:]:
        if line:
            print('[YuE2] ' + line, flush=True)
