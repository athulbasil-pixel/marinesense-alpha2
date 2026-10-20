"""MarineSense Alpha 2.1 pure synthetic vibration generator.

No hardware I/O, no diagnostic classification, and no database writes.
The selected 4x feature is a shaft-order harmonic that moves with RPM.
"""
from __future__ import annotations

import numpy as np
from analysis import compute_vibration

SAMPLE_RATE_HZ = 1000
WINDOW_SECONDS = 2
MAX_DEMO_HOURS = 3


def initial_parameters(sensor_index: int) -> dict:
    """Independent, deliberately slightly different starting amplitudes."""
    return {"one_x": round(0.38 + 0.04 * (sensor_index % 4), 2),
            "four_x": 0.0, "noise": 0.02, "impacts": 0.0}


def synthesize_frame(*, rpm: float, one_x: float, four_x: float,
                     noise: float = 0.02, impacts: float = 0.0,
                     seed: int = 0, sample_rate: int = SAMPLE_RATE_HZ,
                     seconds: int = WINDOW_SECONDS) -> dict:
    """Generate one synthetic time window and its evidence metrics.

    one_x/four_x are *peak amplitudes* in arbitrary demo units.
    impacts adds narrow pulses, deliberately not labelled as bearing damage.
    """
    if not (600 <= rpm <= 3000):
        raise ValueError("Simulated shaft speed must be 600–3000 RPM")
    if not (0 <= one_x <= 2 and 0 <= four_x <= 2):
        raise ValueError("Synthetic amplitude must be between 0 and 2")
    if not (0 <= noise <= 0.5 and 0 <= impacts <= 2):
        raise ValueError("Synthetic noise and impacts are outside permitted ranges")
    if not (sample_rate > 2 * (4 * rpm / 60)):
        raise ValueError("Sampling rate is insufficient for the 4x harmonic")
    n = int(sample_rate * seconds)
    t = np.arange(n, dtype=float) / sample_rate
    freq = rpm / 60.0
    rng = np.random.default_rng(seed)
    values = (one_x * np.sin(2 * np.pi * freq * t)
              + four_x * np.sin(2 * np.pi * 4 * freq * t)
              + noise * rng.standard_normal(n))
    if impacts > 0:
        # Engineered isolated pulses; not a bearing-defect simulator.
        for center in np.arange(0.16, seconds, 0.36):
            values += impacts * np.exp(-0.5 * ((t - center) / 0.003) ** 2)
    evidence = compute_vibration(values, sample_rate)
    return {
        "rms": evidence["rms"],
        "peaks": evidence["peaks"],
        "freq_hz": evidence["frequency"],
        "spectrum": evidence["spectrum"],
        "samples": evidence["values"],
        "sample_rate_hz": sample_rate,
        "shaft_hz": freq,
        "harmonic_hz": 4 * freq,
        "unit": "arbitrary",
    }
