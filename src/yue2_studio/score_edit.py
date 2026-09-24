"""Helpers for editing scores on the rendered sheet (drag pitch, source splicing).

All pitch math uses *sounding* pitches: the key signature is parsed from the
ABC's K: line, so a B in K:Bb sounds as B-flat and is re-emitted correctly
(with an explicit natural/sharp/flat only when the key doesn't already
provide it).
"""
from __future__ import annotations
import re

# Position of each major key on the circle of fifths.
_MAJOR_FIFTHS = {
    'C': 0, 'G': 1, 'D': 2, 'A': 3, 'E': 4, 'B': 5, 'F#': 6, 'C#': 7,
    'G#': 8, 'D#': 9, 'A#': 10,
    'F': -1, 'Bb': -2, 'Eb': -3, 'Ab': -4, 'Db': -5, 'Gb': -6, 'Cb': -7,
}
_SHARP_ORDER = ['F', 'C', 'G', 'D', 'A', 'E', 'B']
_FLAT_ORDER = ['B', 'E', 'A', 'D', 'G', 'C', 'F']
_LETTER = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}
# Flat-preferred spelling for each pitch class: (letter, accidental).
_FLAT_NAMES = ['C', ('D', -1), 'D', ('E', -1), 'E', 'F', ('G', -1),
               'G', ('A', -1), 'A', ('B', -1), 'B']


def key_signature(abc: str) -> dict[str, int]:
    """Letter -> semitone alteration from the first K: line (e.g. K:Bb -> {'B': -1, 'E': -1})."""
    m = re.search(r'^\s*K:\s*([A-G])([#b]?)\s*(m?)\s*$', abc, re.M)
    if not m:
        return {}
    letter, acc, minor = m.group(1), m.group(2), m.group(3)
    name = letter + ('#' if acc == '#' else 'b' if acc == 'b' else '')
    fifths = _MAJOR_FIFTHS.get(name)
    if fifths is None:
        return {}
    if minor:
        fifths -= 3
    alt: dict[str, int] = {}
    if fifths > 0:
        for l in _SHARP_ORDER[:min(fifths, 7)]:
            alt[l] = 1
    elif fifths < 0:
        for l in _FLAT_ORDER[:min(-fifths, 7)]:
            alt[l] = -1
    return alt


def _valid_token(text: str) -> bool:
    return bool(re.fullmatch(r"[=_^]?[A-Ga-g][#b]?[,']*\d*/?\d*", text))


def locate_note_token(text: str, start: int, end: int) -> tuple[int, int] | None:
    """Find the exact ABC note/pitch token covering or nearest to [start, end)."""
    n = len(text)
    if start < 0 or end > n or start >= end:
        return None

    def absorb(s: int, e: int) -> tuple[int, int]:
        # Absorb a preceding accidental so we never cut '=B' into 'B'.
        while s > 0 and text[s - 1] in '=_^' and _valid_token(text[s - 1:e]):
            s -= 1
        return (s, e)

    if _valid_token(text[start:end]):
        return absorb(start, end)
    for shrink in range(1, 4):  # abcjs spans may include trailing barline/articulation text.
        if start + shrink < end and _valid_token(text[start:end - shrink]):
            return absorb(start, end - shrink)
    for a in range(5):
        for b in range(4):
            s, e = start - a, end + b
            if s < 0 or e > n or s >= e:
                continue
            if _valid_token(text[s:e]):
                return absorb(s, e)
    return None


def parse_note(token: str, keysig: dict[str, int] | None = None) -> dict | None:
    """Parse an ABC note (Bb,3/2, ^f, c'4, G, ...) into a sounding MIDI pitch."""
    keysig = keysig or {}
    m = re.fullmatch(r"([=_^]?)([A-Ga-g])([#b]?)([,']*)(\d*/?\d*)", token)
    if not m:
        return None
    prefix, letter, acc, marks, rhythm = m.groups()
    lower = letter.islower()
    upper = letter.upper()
    base = _LETTER[upper]
    if prefix == '=':
        semi = base
    elif prefix == '^':
        semi = base + 1
    elif prefix == '_':
        semi = base - 1
    elif acc == '#':
        semi = base + 1
    elif acc == 'b':
        semi = base - 1
    else:
        semi = base + keysig.get(upper, 0)
    octave = (5 if lower else 4) + marks.count("'") - marks.count(',')
    midi = (octave + 1) * 12 + semi
    return {'midi': midi, 'rhythm': rhythm}


def emit_note(midi: int, rhythm: str, keysig: dict[str, int]) -> str | None:
    """Emit an ABC token sounding `midi`, minimal accidentals given the key."""
    if midi < 12 or midi > 120:
        return None
    pc = midi % 12
    spelled = _FLAT_NAMES[pc]
    letter, acc = (spelled, 0) if isinstance(spelled, str) else spelled
    octave = midi // 12 - 1
    core: str
    if octave >= 5:
        core = letter.lower() + "'" * (octave - 5)
    else:
        core = letter + ',' * (4 - octave)
    if keysig.get(letter, 0) == acc:
        prefix = ''  # the key signature already provides this alteration
    elif acc == 0:
        prefix = '='
    elif acc == 1:
        prefix = '^'
    else:
        prefix = '_'
    return prefix + core + rhythm


def shift_note_token(token: str, semitones: int, octaves: int,
                     keysig: dict[str, int] | None = None) -> str | None:
    """Return `token` transposed by semitones/octaves, re-spelled for `keysig`."""
    keysig = keysig or {}
    info = parse_note(token, keysig)
    if info is None:
        return None
    shift = semitones + 12 * octaves
    if shift == 0:
        return token
    return emit_note(info['midi'] + shift, info['rhythm'], keysig)


def adjust_pitch(abc: str, start: int, end: int,
                 semitones: int = 0, octaves: int = 0) -> dict:
    """Adjust the sounding pitch of the note token at/near [start, end)."""
    if semitones == 0 and octaves == 0:
        raise ValueError('Nothing to change.')
    keysig = key_signature(abc)
    found = locate_note_token(abc, int(start), int(end))
    if not found:
        raise ValueError('Could not locate a note token at that position.')
    s, e = found
    new_token = shift_note_token(abc[s:e], int(semitones), int(octaves), keysig)
    if new_token is None:
        raise ValueError('That adjustment would push the note out of range or is not a plain note.')
    return {'abc': abc[:s] + new_token + abc[e:], 'start': s, 'end': s + len(new_token)}
