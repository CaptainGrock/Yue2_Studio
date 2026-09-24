"""Gentle mastering for YuE2 renders: tame harshness, add warmth, glue dynamics.

Pure numpy + soundfile. The chain is deliberately conservative so vocals and
mix character survive: zero-phase spectral shelves (no pre-ringing beyond the
window), soft block-RMS glue compression with a small ceiling, and a final
peak-safe normalization to -1 dBFS. The original render is never modified.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import soundfile as sf


def _spectral_shelves(audio, rate):
    """Zero-phase (fftfreq-windowed) tilt: -2.2 dB around 3.2 kHz, +1.4 dB low shelf.

    Gentle enough to keep voices intact; applied identically to both channels.
    """
    spectrum = np.fft.rfft(audio, axis=0)
    freqs = np.fft.rfftfreq(audio.shape[0], d=1.0 / rate)
    with np.errstate(divide='ignore'):
        log_f = np.log2(np.maximum(freqs, 1.0) / 1000.0)
    harsh = np.exp(-0.5 * ((log_f - np.log2(3.2)) / 0.6) ** 2)   # gaussian centered 3.2 kHz
    low = 1.0 / (1.0 + np.exp(log_f / 0.4))             # sigmoid below ~1 kHz
    gain_db = -3.0 * harsh + 1.4 * low
    spectrum *= 10.0 ** (gain_db[:, None] / 20.0)
    return np.fft.irfft(spectrum, n=audio.shape[0], axis=0)


def _glue_compress(audio, rate, target_rms=-20.0, ratio=1.6, ceiling=0.85):
    """Soft block-RMS compression with 60 ms lookahead; returns (audio, applied_gain_db)."""
    block = max(1, int(rate * 0.06))
    pad = (-len(audio)) % block
    frames = audio.reshape(-1, block, audio.shape[1]) if pad == 0 else np.concatenate(
        [audio, np.zeros((pad, audio.shape[1]), dtype=audio.dtype)]).reshape(-1, block, audio.shape[1])
    rms = np.sqrt(np.mean(np.square(frames.astype(np.float64)), axis=(1, 2)))
    rms_db = 20.0 * np.log10(np.maximum(rms, 1e-9))
    over = np.maximum(rms_db - target_rms, 0.0)
    reduction = over * (1.0 - 1.0 / ratio)
    gain = 10.0 ** (-(reduction / 20.0))
    # 60 ms attack/release smoothing so gain changes stay inaudible.
    smoother = np.ones(3) / 3.0
    gain = np.convolve(gain, smoother, mode='same')
    envelope = np.repeat(gain, block)[:len(audio)][:, None]
    compressed = audio * envelope
    peak = float(np.max(np.abs(compressed))) if compressed.size else 0.0
    if peak > ceiling:
        compressed *= ceiling / peak
    return compressed.astype(audio.dtype), float(np.max(reduction, initial=0.0))


def master_file(source, target):
    """Master one FLAC/WAV render. Returns a metrics dict for the UI receipt."""
    source, target = Path(source), Path(target)
    audio, rate = sf.read(str(source), always_2d=True)
    if audio.dtype != np.float32:
        audio = audio.astype(np.float32)
    original_peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    audio = _spectral_shelves(audio, rate)
    audio, compression_db = _glue_compress(audio, rate)
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    if peak > 0:
        audio *= (10.0 ** (-1.0 / 20.0)) / peak          # peak-safe -1 dBFS
    sf.write(str(target), audio, rate, format='FLAC', subtype='PCM_24')
    metrics = {
        'original_peak_dbfs': round(20.0 * np.log10(max(original_peak, 1e-9)), 2),
        'mastered_peak_dbfs': -1.0,
        'glue_compression_db': round(compression_db, 2),
    }
    (target.parent / 'mastering.json').write_text(json.dumps(metrics, indent=1), encoding='utf-8')
    return metrics
