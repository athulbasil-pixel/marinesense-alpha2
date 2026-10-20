"""Read-only research assessment of saved MarineSense simulation records."""
from __future__ import annotations

import json
from html import escape

import pandas as pd
import streamlit as st
from sqlalchemy.exc import SQLAlchemyError

import registry as reg
import live_history as history
from condition_assessment import (
    BASELINE_COUNT, COMPARISON_COUNT, MIN_FRAMES_PER_MINUTE,
    compare_session, example_session,
)


def render_condition_dashboard(engine):
    st.caption("ENGINEERING / NUMERICAL CONDITION REVIEW · Prototype 0.1")
    st.subheader("Vibration condition assessment")
    st.info("Research comparison only. This page does NOT classify machine health, detect faults, "
            "apply ISO 20816 limits, or generate operational alarms. All readings here are synthetic "
            "and use arbitrary units.")
    st.markdown("**Method:** Select three reference minutes and two later comparison minutes "
                "for each sensor. The software checks sample coverage, RPM comparability, "
                "RMS deviation and 4× spectral changes before displaying its evidence.")

    mode = st.radio("Data source", ["Saved Supabase simulation", "Offline illustrative example"],
                    horizontal=True, key="ms22_assessment_source")
    machine = None
    events = []
    if mode == "Saved Supabase simulation":
        machines = reg.list_machines(engine)
        if not machines:
            st.warning("No machinery registered. Use the offline example to preview the assessment.")
            return
        machine_ids = [m["id"] for m in machines]
        mid = st.selectbox("Registered machine", machine_ids,
                           format_func=lambda i: next(f"{m['ms_number']} · {m['name']}" for m in machines if m['id'] == i),
                           key="ms22_assessment_machine")
        machine = next(m for m in machines if m["id"] == mid)
        try:
            sessions = history.list_sessions(engine, mid)
        except (SQLAlchemyError, OSError):
            st.error("Unable to load simulation history from Supabase. Check the database connection.")
            return
        valid = [s for s in sessions if s.get("source") == "synthetic_browser_demo"]
        if not valid:
            st.warning("No synthetic sessions found for this machine. You can preview an offline example.")
            return
        ids = [s["id"] for s in valid]
        session_id = st.selectbox("Recorded simulation session", ids,
                 format_func=lambda sid: next(f"{s['started_utc']} · {sid[:8]}" for s in valid if s['id'] == sid),
                 key=f"ms22_session_{mid}")
        try:
            rows = history.list_minutes(engine, session_id, limit=1000)
            events = history.list_events(engine, session_id)
        except (SQLAlchemyError, OSError):
            st.error("Unable to read selected session. Existing saved data has not been changed.")
            return
        st.caption(f"Read-only assessment of saved session {session_id[:8]} · Machine {machine['ms_number']}")
    else:
        rows = example_session()
        st.caption("Fixed invented seven-minute example. No database access, writes or actual sensor measurements.")

    if not rows:
        st.warning("No minute summaries found for the selected session.")
        return
    minute_ids = sorted(set(int(x["minute_index"]) for x in rows))
    if len(minute_ids) < BASELINE_COUNT + COMPARISON_COUNT:
        st.warning(f"Only {len(minute_ids)} minute index(es) available. This assessment requires at least "
                   f"{BASELINE_COUNT + COMPARISON_COUNT} observed minutes "
                   "(three reference + two comparison). Short runs remain safely stored but cannot be assessed yet.")
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        return

    first, last = minute_ids[0], minute_ids[-1]
    possible_baselines = list(range(first, last - (BASELINE_COUNT + COMPARISON_COUNT) + 2))
    first_start = st.selectbox("Reference window starts at minute", possible_baselines,
                               key=f"ms22_reference_{mode}_{machine['id'] if machine else 'example'}")
    possible_comparisons = list(range(first_start + BASELINE_COUNT, last - COMPARISON_COUNT + 2))
    comparison_start = st.selectbox("Comparison window starts at minute", possible_comparisons,
                                    index=len(possible_comparisons) - 1,
                                    key=f"ms22_comparison_{mode}_{machine['id'] if machine else 'example'}")
    with st.expander("Data-quality and comparison settings", expanded=False):
        min_frames = st.slider("Minimum observed 5-second frames per selected minute", 6, 12,
                               MIN_FRAMES_PER_MINUTE, key="ms22_quality_frames")
        st.caption("A full minute is expected to have about 12 frames when the browser remains connected; "
                   "missing observations are never invented. Partial windows are excluded.")
    reference_indices = list(range(first_start, first_start + BASELINE_COUNT))
    comparison_indices = list(range(comparison_start, comparison_start + COMPARISON_COUNT))
    st.caption(f"Reference: minutes {reference_indices} · Comparison: minutes {comparison_indices} · "
               "Simulated speed must remain within ±5% · Both comparison minutes are checked")

    results = compare_session(rows, first_start, comparison_start, minimum_frames=min_frames)
    if not results:
        st.warning("No linked sensor points were found in the selected records.")
        return
    view = []
    for result in results:
        proof = result["evidence"]
        view.append({
            "Sensor": result["sensor"], "Result": result["status"],
            "Reference RMS": proof.get("reference_rms"),
            "Compared RMS": proof.get("comparison_rms"),
            "RMS change %": proof.get("rms_change_percent"),
            "4× Δ": proof.get("4x_amplitude_delta"),
            "Reason / data-quality finding": result["reason"],
        })
    st.markdown("#### Per-sensor evidence summary")
    st.dataframe(pd.DataFrame(view), use_container_width=True, hide_index=True)
    st.caption("Change indicators are for this synthetic experiment, not severity ratings or equipment alarms. "
               "A single change does not demonstrate persistence or a mechanical fault.")

    plotted = pd.DataFrame(rows)
    if not plotted.empty:
        st.markdown("#### Stored RMS trend · all sensor locations")
        # Minute index avoids malformed timestamps and makes missing minutes visible.
        trend = plotted.pivot_table(index="minute_index", columns="sensor", values="avg_rms", aggfunc="last")
        st.line_chart(trend, height=320)
        st.caption("Horizontal axis: observed minute index. Reference and comparison periods are selected above.")

    selected = st.selectbox("Inspect one sensor", [r["point_id"] for r in results],
                    format_func=lambda point_id: next(r["sensor"] for r in results if r["point_id"] == point_id),
                    key=f"ms22_point_{mode}_{machine['id'] if machine else 'example'}")
    item = next(r for r in results if r["point_id"] == selected)
    st.markdown(f"**{escape(item['sensor'])}: {escape(item['status'])}**")
    st.write(item["reason"])
    if item["evidence"]:
        st.json(item["evidence"], expanded=False)
    for caveat in item["limitations"]:
        st.caption("• " + caveat)

    if events and mode == "Saved Supabase simulation":
        with st.expander("Operator actions in this session (not fault diagnoses)"):
            st.dataframe(pd.DataFrame(events), hide_index=True, use_container_width=True)

    payload = {"version": "MarineSense experimental comparison 0.1",
               "source": "synthetic_demo_recorded" if mode == "Saved Supabase simulation" else "fictional_offline_example",
               "machine_number": machine["ms_number"] if machine else "EXAMPLE_ONLY",
               "reference_minute_indices": reference_indices,
               "comparison_minute_indices": comparison_indices,
               "results": results,
               "note": "Numerical experimental evidence; not a machine fault or alarm report."}
    st.download_button("Download evidence-only assessment (JSON)",
                       json.dumps(payload, indent=2), file_name="marinesense_condition_evidence.json",
                       mime="application/json", key="ms22_assessment_json")
    st.caption("No AI call or database write is performed by this assessment page.")
