"""Deterministic, non-alarm vibration comparison for MarineSense research demos.

Only compares synthetic, arbitrary-unit, one-minute summary records from the
same registered sensor point and operating speed. Does not diagnose faults,
calculate ISO severity or establish that the chosen baseline is healthy.
"""
from __future__ import annotations

from collections import defaultdict
import math
from statistics import median

BASELINE_COUNT = 3
COMPARISON_COUNT = 2
MIN_FRAMES_PER_MINUTE = 6
RPM_TOLERANCE_PCT = 5.0
RMS_CHANGE_PCT = 20.0   # EXPLORATORY demo threshold, not an equipment alarm
LARGE_RMS_CHANGE_PCT = 40.0  # EXPLORATORY demo threshold
HARMONIC_ABS_DELTA = 0.05  # arbitrary-demo FFT units, not an OEM limit


def _as_float(row: dict, key: str) -> float:
    number = float(row[key])
    if not math.isfinite(number):
        raise ValueError(f"Non-finite {key}")
    return number


def _quality_problem(row: dict, *, minimum_frames: int) -> str | None:
    """Reject partial/poor/inconsistent records instead of fabricating samples."""
    if row.get("partial_window") is True or str(row.get("partial_window")).lower() == "true":
        return "A selected minute is marked partial"
    if int(row.get("observed_frames") or 0) < minimum_frames:
        return f"Fewer than {minimum_frames} observed 5-second frames in a selected minute"
    if row.get("unit") != "arbitrary":
        return "Only synthetic arbitrary-unit records are supported in this demonstration"
    try:
        if _as_float(row, "avg_rms") <= 0:
            return "RMS is absent or non-positive"
        if _as_float(row, "rpm") <= 0:
            return "Operating RPM is missing or non-positive"
        for key in ("1x_amplitude", "4x_amplitude"):
            if _as_float(row, key) < 0:
                return f"{key} must not be negative"
    except (ValueError, TypeError, KeyError):
        return "A required measurement field is missing or invalid"
    return None


def _pct_change(current: float, reference: float) -> float:
    return 100.0 * (current - reference) / reference


def compare_sensor(
    rows: list[dict],
    reference_minutes: list[int],
    comparison_minutes: list[int],
    *,
    minimum_frames: int = MIN_FRAMES_PER_MINUTE,
    rpm_tolerance_pct: float = RPM_TOLERANCE_PCT,
) -> dict:
    """Return transparent evidence for ONE sensor, never a fault diagnosis.

    Reference contains exactly three consecutive FULL minutes and comparison
    exactly two later consecutive FULL minutes, selected by the operator.
    Each window is judged individually; the label 'sustained' requires both
    compared minutes to exceed the same demonstration criterion.
    """
    result = {"status": "NOT ASSESSED", "reason": "", "point_id": None,
              "sensor": "Unknown", "evidence": {}, "limitations": [
                  "Chosen reference is not a verified healthy machine baseline",
                  "Thresholds are illustrative only, not calibrated alarms or diagnoses",
                  "No continuous unattended monitoring or fault attribution",
              ]}
    if rows:
        result["point_id"] = rows[0].get("point_id")
        result["sensor"] = str(rows[0].get("sensor") or "Unknown")
    if (len(reference_minutes) != BASELINE_COUNT or len(comparison_minutes) != COMPARISON_COUNT
            or len(set(reference_minutes)) != BASELINE_COUNT
            or len(set(comparison_minutes)) != COMPARISON_COUNT
            or sorted(reference_minutes) != list(range(min(reference_minutes), max(reference_minutes) + 1))
            or sorted(comparison_minutes) != list(range(min(comparison_minutes), max(comparison_minutes) + 1))
            or max(reference_minutes) >= min(comparison_minutes)
            or set(reference_minutes).intersection(comparison_minutes)):
        result.update(status="NOT COMPARABLE", reason="Choose three consecutive reference minutes followed by two consecutive comparison minutes")
        return result

    by_index = {}
    for row in rows:
        index = int(row["minute_index"])
        if index in by_index:
            result.update(status="NOT COMPARABLE", reason="Duplicate minute for this sensor; ambiguous source records")
            return result
        by_index[index] = row
    selected = reference_minutes + comparison_minutes
    if any(index not in by_index for index in selected):
        result.update(status="INSUFFICIENT DATA", reason="One or more selected minutes are missing for this sensor")
        return result
    ref_rows = [by_index[idx] for idx in reference_minutes]
    cur_rows = [by_index[idx] for idx in comparison_minutes]
    for row in ref_rows + cur_rows:
        quality = _quality_problem(row, minimum_frames=minimum_frames)
        if quality:
            result.update(status="INSUFFICIENT DATA", reason=quality)
            return result
    ref_rpm = median(_as_float(row, "rpm") for row in ref_rows)
    rpm_deviations = [abs(_as_float(row, "rpm") / ref_rpm - 1.0) * 100 for row in ref_rows + cur_rows]
    if max(rpm_deviations) > rpm_tolerance_pct:
        result.update(status="OPERATING CHANGE", reason=f"RPM differs by more than {rpm_tolerance_pct:g}% from reference; signal levels not compared",
                      evidence={"reference_rpm": round(ref_rpm, 2),
                                "maximum_rpm_difference_percent": round(max(rpm_deviations), 2)})
        return result

    ref_rms = median(_as_float(row, "avg_rms") for row in ref_rows)
    cur_rms = median(_as_float(row, "avg_rms") for row in cur_rows)
    changes = [_pct_change(_as_float(row, "avg_rms"), ref_rms) for row in cur_rows]
    ref_one = median(_as_float(row, "1x_amplitude") for row in ref_rows)
    cur_one = median(_as_float(row, "1x_amplitude") for row in cur_rows)
    ref_four = median(_as_float(row, "4x_amplitude") for row in ref_rows)
    cur_four = median(_as_float(row, "4x_amplitude") for row in cur_rows)
    four_changes = [_as_float(row, "4x_amplitude") - ref_four for row in cur_rows]
    # Require an absolute amplitude rise; relative ratios close to zero are unstable.
    new_four = all(delta >= HARMONIC_ABS_DELTA for delta in four_changes)
    large_rms = all(change >= LARGE_RMS_CHANGE_PCT for change in changes)
    rising_rms = all(change >= RMS_CHANGE_PCT for change in changes)
    intermittent = any(change >= RMS_CHANGE_PCT for change in changes) or any(
        delta >= HARMONIC_ABS_DELTA for delta in four_changes)
    if large_rms:
        label, reason = "LARGE SUSTAINED CHANGE", "RMS exceeded the illustrative +40% deviation band in both comparison minutes"
    elif rising_rms and new_four:
        label, reason = "SUSTAINED CHANGE", "RMS increased and the 4× spectral component strengthened in both comparison minutes"
    elif rising_rms:
        label, reason = "SUSTAINED CHANGE", "RMS exceeded the illustrative +20% deviation band in both comparison minutes"
    elif new_four:
        label, reason = "SPECTRAL CHANGE", "The 4× component increased in both comparison minutes"
    elif intermittent:
        label, reason = "SINGLE-WINDOW CHANGE", "A deviation appeared in only one comparison minute; persistence not demonstrated"
    else:
        label, reason = "NO SUSTAINED CHANGE", "Neither illustrative RMS nor 4× change condition was met twice"
    result.update(status=label, reason=reason, evidence={
        "reference_minutes": reference_minutes,
        "comparison_minutes": comparison_minutes,
        "reference_rpm": round(ref_rpm, 2),
        "maximum_rpm_difference_percent": round(max(rpm_deviations), 2),
        "reference_rms": round(ref_rms, 5),
        "comparison_rms": round(cur_rms, 5),
        "rms_change_percent": round(_pct_change(cur_rms, ref_rms), 1),
        "comparison_minute_changes_percent": [round(x, 1) for x in changes],
        "reference_1x_amplitude": round(ref_one, 5),
        "comparison_1x_amplitude": round(cur_one, 5),
        "reference_4x_amplitude": round(ref_four, 5),
        "comparison_4x_amplitude": round(cur_four, 5),
        "4x_amplitude_delta": round(cur_four - ref_four, 5),
        "observed_reference_frames": sum(int(x["observed_frames"]) for x in ref_rows),
        "observed_comparison_frames": sum(int(x["observed_frames"]) for x in cur_rows),
        "unit": "arbitrary",
    })
    return result


def compare_session(rows: list[dict], reference_start: int,
                    comparison_start: int, minimum_frames: int = MIN_FRAMES_PER_MINUTE) -> list[dict]:
    """Compare all registered sensor point IDs independently in one session."""
    per_sensor: dict[int, list[dict]] = defaultdict(list)
    for row in rows:
        per_sensor[int(row["point_id"])].append(row)
    refs = list(range(int(reference_start), int(reference_start) + BASELINE_COUNT))
    curs = list(range(int(comparison_start), int(comparison_start) + COMPARISON_COUNT))
    return [compare_sensor(own_rows, refs, curs, minimum_frames=minimum_frames)
            for _, own_rows in sorted(per_sensor.items())]


def example_session() -> list[dict]:
    """Explicitly fictional example to preview the UI; NEVER stored as measurements."""
    samples = []
    for minute in range(7):
        for point_id, (sensor, amplitude) in enumerate(
                (("SEN-0001", .270), ("SEN-0002", .298),
                 ("SEN-0003", .326), ("SEN-0004", .354)), 1):
            changed = point_id == 3 and minute >= 4
            rms = amplitude * (1.46 if changed else 1.0) + .0003 * (minute % 2)
            samples.append({
                "minute_index": minute, "point_id": point_id, "sensor": sensor,
                "time_utc": f"2026-01-01T00:{minute:02d}:00+00:00",
                "avg_rms": round(rms, 5), "rpm": 1800,
                "1x_amplitude": .46 if changed else .40,
                "4x_amplitude": .28 if changed else .002,
                "observed_frames": 12, "partial_window": False,
                "unit": "arbitrary",
            })
    return samples
