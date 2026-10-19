"""Deterministic vibration analysis for the MarineSense demonstration.

All signals must be equally spaced samples. No sensor calibration or fault diagnosis
is performed by this module.
"""

from __future__ import annotations

import numpy as np


def compute_vibration(signal, sample_rate_hz: float) -> dict:
    """Calculate RMS and exploratory amplitude-spectrum peaks."""
    values = np.asarray(signal, dtype=np.float64)
    if values.ndim != 1 or values.size < 128:
        raise ValueError("At least 128 vibration samples are required.")
    if values.size > 100_000:
        raise ValueError("For this demonstration, use no more than 100,000 samples per file.")
    if not np.isfinite(values).all():
        raise ValueError("Vibration samples must contain only finite numbers.")
    if not np.isfinite(sample_rate_hz) or sample_rate_hz <= 0:
        raise ValueError("The sampling rate must be a positive finite number.")

    rms = float(np.sqrt(np.mean(values ** 2)))
    # Remove DC offset for spectral analysis; Hann window reduces leakage.
    centered = values - values.mean()
    window = np.hanning(values.size)
    spectrum = 2.0 * np.abs(np.fft.rfft(centered * window)) / window.sum()
    frequency = np.fft.rfftfreq(values.size, d=1.0 / sample_rate_hz)
    # Exclude DC and Nyquist bins when finding local maxima.
    inner = (
        (spectrum[1:-1] > spectrum[:-2])
        & (spectrum[1:-1] >= spectrum[2:])
    )
    candidate = np.flatnonzero(inner) + 1
    max_spectrum = float(np.max(spectrum[1:])) if spectrum.size > 1 else 0.0
    min_height = max_spectrum * 0.1
    candidate = [int(i) for i in candidate if spectrum[i] >= min_height and spectrum[i] > 1e-10]
    candidate.sort(key=lambda i: spectrum[i], reverse=True)
    peaks = [
        {
            "frequency_hz": round(float(frequency[i]), 2),
            "amplitude": round(float(spectrum[i]), 4),
        }
        for i in candidate[:5]
    ]
    return {
        "rms": round(rms, 4),
        "peaks": peaks,
        "sample_count": int(values.size),
        "sample_rate_hz": float(sample_rate_hz),
        "duration_seconds": round(float(values.size / sample_rate_hz), 3),
        "frequency": frequency,
        "spectrum": spectrum,
        "values": values,
    }


def example_signals(sample_rate_hz: int = 1000) -> tuple[np.ndarray, np.ndarray]:
    """Replicate the Day 1 synthetic 30 Hz and 30+120 Hz demonstrations."""
    t = np.arange(0, 2, 1 / sample_rate_hz)
    rng = np.random.default_rng(42)
    baseline = 0.5 * np.sin(2 * np.pi * 30 * t) + 0.03 * rng.normal(size=t.size)
    changed = (
        0.5 * np.sin(2 * np.pi * 30 * t)
        + 0.4 * np.sin(2 * np.pi * 120 * t)
        + 0.03 * rng.normal(size=t.size)
    )
    return baseline, changed
