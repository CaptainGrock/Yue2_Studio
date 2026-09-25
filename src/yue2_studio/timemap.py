"""Audio-anchored score sync: build a piecewise-linear time map between the
score's nominal timeline and the rendered audio.

The rendered audio never follows the score's nominal BPM exactly (the semantic
model stretches phrases and inserts breathing room), so a linear map drifts by
seconds. This module cross-correlates onset envelopes of the rendered audio
and the score's expected onsets to find local anchors, then interpolates
between anchors. Cached in result/timemap.json; rebuilt if audio is newer.
"""
from __future__ import annotations

import json
import sys
import numpy as np
import soundfile as sf
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[2] / 'skills/yue2-music/scripts'
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

FRAME = 512          # samples per onset-envelope frame at 44.1kHz (~11.6ms)
SMOOTH = 9           # envelope smoothing window (frames)
MIN_SPACING = 0.25   # seconds between distinct onsets
ANCHOR_SPACING = 2.0  # target seconds between anchors (denser = steadier sync)
TOLERANCE = 0.6       # seconds: max |audio-skeleton - score-time| for an anchor


def _onset_envelope(samples, samplerate):
    """Energy-flux onset envelope (onset strength per frame)."""
    x = samples
    if x.ndim > 1:
        x = x.mean(axis=1)
    hop = FRAME
    n = (len(x) - FRAME) // hop
    frames = x[:n * hop].reshape(n, hop)
    # Energy in dB-ish domain
    energy = np.sqrt((frames ** 2).mean(axis=1) + 1e-12)
    loge = np.log(energy)
    # Positive first difference = energy flux
    flux = np.diff(loge, prepend=loge[0])
    flux[flux < 0] = 0
    # Smooth
    k = np.ones(SMOOTH) / SMOOTH
    env = np.convolve(flux, k, mode='same')
    return env, hop / samplerate


def _peaks(env, frame_s, min_spacing=MIN_SPACING):
    """Pick onset times (seconds) from an envelope."""
    if len(env) < 3:
        return []
    gap = max(1, int(min_spacing / frame_s))
    idx = []
    last = -gap
    for i in range(1, len(env) - 1):
        if env[i] >= env[i - 1] and env[i] > env[i + 1] and env[i] > env.max() * 0.08:
        # local max above threshold
            if i - last >= gap:
                idx.append(i)
                last = i
    out = [i * frame_s for i in idx]
    return out


def _score_onsets(job_dir: Path):
    """Score note onsets (seconds) in the score's nominal timeline."""
    from abc_tools import parse_abc
    score_text = None
    try:
        supplied = (job_dir / 'result/score.abc').read_text(encoding='utf-8')
        score_text = supplied if supplied.strip() else None
    except OSError:
        pass
    if not score_text:
        try:
            spec = json.loads((job_dir / 'input.json').read_text(encoding='utf-8'))
            score_text = spec.get('request', {}).get('abc') or None
        except (OSError, ValueError):
            return []
    if not score_text:
        return []
    score = parse_abc(score_text)
    bpm = score.bpm
    onsets = []
    vocal = score.voices.get('Vocal')
    if vocal is None:
        return []
    from fractions import Fraction
    spb = 60.0 / bpm  # seconds per quarter
    for t, p, d in vocal.notes:
        onsets.append(float(t) * spb)
    onsets.sort()
    # Collapse duplicates
    out = []
    for t in onsets:
        if not out or t - out[-1] > MIN_SPACING:
            out.append(t)
    return out


def build(job_dir: Path):
    """Build (or reuse) result/timemap.json. Returns dict or None."""
    result = job_dir / 'result'
    audio = result / 'audio.flac'
    if not audio.is_file():
        return None
    spec_path = job_dir / 'input.json'
    try:
        json.loads(spec_path.read_text(encoding='utf-8'))  # well-formed input required
    except (OSError, ValueError):
        return None
    cache = result / 'timemap.json'
    if cache.is_file() and cache.stat().st_mtime >= audio.stat().st_mtime:
        try:
            return json.loads(cache.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            pass
    try:
        data, sr = sf.read(audio, dtype='float32', always_2d=True)
    except Exception:
        return None
    if len(data) < sr:  # <1s audio: pointless
        return None
    env, frame_s = _onset_envelope(data, sr)
    audio_peaks = _peaks(env, frame_s)
    score_onsets = _score_onsets(job_dir)
    if not audio_peaks or not score_onsets:
        return None
    # Audio skeleton: re-beat the audio onsets against the score's onset pattern
    # by matching each score onset to the nearest audio peak within tolerance.
    audio_dur = len(data) / sr
    score_dur = score_onsets[-1] + 1.0
    scale = audio_dur / score_dur
    anchors = []
    last_audio = -1.0
    si = 0
    while si < len(score_onsets):
        t_score = score_onsets[si]
        expected = t_score * scale
        window = [p for p in audio_peaks if abs(p - expected) <= TOLERANCE]
        if window:
            p = min(window, key=lambda q: abs(q - expected))
            if p > last_audio:  # anchors must advance in audio time
                anchors.append((p, t_score))
                last_audio = p
            # Skip ahead to keep anchors spread out
            while si < len(score_onsets) and score_onsets[si] < t_score + ANCHOR_SPACING:
                si += 1
        else:
            si += 1
    if len(anchors) < 4:
        # Too few anchors: fall back to a global linear fit
        anchors = [(0.0, 0.0), (audio_dur, score_dur)]
    else:
        anchors = [(0.0, 0.0)] + anchors + [(audio_dur, score_dur)]
    # Sort by audio time and drop non-monotonic pairs (also dedupes the
    # synthetic endpoints if a matched anchor landed at 0 or audio_dur).
    anchors.sort(key=lambda a: (a[0], a[1]))
    clean = [anchors[0]]
    for a in anchors[1:]:
        if a[1] > clean[-1][1] and a[0] > clean[-1][0]:
            clean.append(a)
    anchors = clean
    # Second pass: re-match onsets against the coarse map instead of the raw
    # global scale. Local stretches the coarse map absorbed (ritardandi, phrase
    # gaps) no longer push expected times off the real peaks, so far more
    # onsets land within tolerance.
    coarse = anchors
    def _score_to_audio(s):
        xs = [c[1] for c in coarse]; ys = [c[0] for c in coarse]
        return float(np.interp(s, xs, ys))
    fine = []
    last_audio = -1.0
    si = 0
    while si < len(score_onsets):
        t_score = score_onsets[si]
        expected = _score_to_audio(t_score)
        window = [p for p in audio_peaks if abs(p - expected) <= TOLERANCE]
        if window:
            p = min(window, key=lambda q: abs(q - expected))
            if p > last_audio:
                fine.append((p, t_score))
                last_audio = p
            while si < len(score_onsets) and score_onsets[si] < t_score + ANCHOR_SPACING:
                si += 1
        else:
            si += 1
    if len(fine) >= 4:
        fine = [(0.0, 0.0)] + fine + [(audio_dur, score_dur)]
        fine.sort(key=lambda a: (a[0], a[1]))
        clean = [fine[0]]
        for a in fine[1:]:
            if a[1] > clean[-1][1] and a[0] > clean[-1][0]:
                clean.append(a)
        if len(clean) >= 4:
            anchors = clean
    out = {
        'anchors': [[round(a, 3), round(b, 3)] for a, b in anchors],
        'audio_duration': round(audio_dur, 3),
        'score_duration': round(score_dur, 3),
    }
    cache.write_text(json.dumps(out), encoding='utf-8')
    return out
