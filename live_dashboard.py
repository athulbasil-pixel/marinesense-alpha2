"""Interactive, session-only live sensor simulation for MarineSense Alpha 2.1.

Runs only when a browser session is connected and the simulation is enabled.
Does NOT save historical readings to Postgres or modify the Alpha 2.0 tables.
"""
from __future__ import annotations

from datetime import datetime, timezone
import time

import numpy as np
import pandas as pd
import streamlit as st

import registry as reg
from live_simulator import MAX_DEMO_HOURS, initial_parameters, synthesize_frame

TICK_SECONDS = 5
MAX_HISTORY_ROWS = MAX_DEMO_HOURS * 3600 // TICK_SECONDS * 4


def _point_name(point):
    return (point["sensor_code"] or f"Virtual #{point['id']}") + " · " + point["name"]


def _get_state(machine_id: int, points: list[dict]):
    key = f"alpha21_demo_{machine_id}"
    if key not in st.session_state:
        st.session_state[key] = {
            "running": False,
            "started_at": None,
            "last_bucket": None,
            "records": [],
            "latest": {},
            "frames": {},
            "previous_configs": {},
            "events": [],
            "params": {p["id"]: initial_parameters(i) for i, p in enumerate(points)},
        }
    state = st.session_state[key]
    for i, p in enumerate(points):
        state["params"].setdefault(p["id"], initial_parameters(i))
    return state


def render_live_dashboard(engine):
    st.header("Alpha 2.1 · Live virtual sensor demonstration")
    st.warning("SIMULATED DATA ONLY — no OEM sensor connected; no actual machinery fault diagnosis or safety alarm.")
    st.caption("The simulator runs in this active browser session. It does NOT operate unattended, "
               "and measurements on this tab are NOT automatically stored in Supabase yet.")
    machines = reg.list_machines(engine)
    if not machines:
        st.info("Register a machinery assembly before starting the simulator.")
        return
    machine_ids = [m["id"] for m in machines]
    machine_id = st.selectbox("Simulated machinery", machine_ids,
                              format_func=lambda i: next(m["ms_number"] + " · " + m["name"] for m in machines if m["id"] == i),
                              key="alpha21_machine_selector")
    machine = next(m for m in machines if m["id"] == machine_id)
    components = reg.list_components(engine, machine_id)
    points = reg.list_sensor_points(engine, [c["id"] for c in components])
    if not points:
        st.warning("This machinery has no registered sensor locations.")
        return
    if len(points) > 4:
        st.info("Alpha 2.1's first simulator displays the first four sensor locations only.")
    points = points[:4]
    if len(points) < 4:
        st.info(f"{len(points)} sensor location(s) currently registered. The initial target is four.")
    st.caption(f"Machine: {machine['ms_number']} · {machine['name']} · "
               "SIMULATION only; RMS values are arbitrary, not calibrated physical readings.")
    state = _get_state(machine_id, points)

    @st.fragment(run_every=f"{TICK_SECONDS}s")
    def _live_panel():
        now = time.time()
        st.subheader("Simulation operator controls")
        col_a, col_b, col_c = st.columns([1, 1, 2])
        with col_a:
            start = st.button("▶ Start 3-hour maximum session", disabled=state["running"],
                              key=f"alpha21_start_{machine_id}")
        with col_b:
            stop = st.button("■ Stop", disabled=not state["running"],
                             key=f"alpha21_stop_{machine_id}")
        with col_c:
            rpm = st.slider("Simulated shaft RPM (shared)", 600, 3000, 1800, 60,
                            key=f"alpha21_rpm_{machine_id}")
        if start:
            state["running"] = True
            state["started_at"] = now
            state["last_bucket"] = None
            state["records"].clear()
            state["latest"].clear()
            state["frames"].clear()
            state["events"].clear()
            state["previous_configs"].clear()
        if stop:
            state["running"] = False
        if state["running"] and now - state["started_at"] >= MAX_DEMO_HOURS * 3600:
            state["running"] = False
            st.info("Three-hour maximum reached; simulation stopped.")

        selected_point_id = st.selectbox("Adjust virtual sensor", [p["id"] for p in points],
                                         format_func=lambda i: _point_name(next(p for p in points if p["id"] == i)),
                                         key=f"alpha21_sensor_selector_{machine_id}")
        selected = next(p for p in points if p["id"] == selected_point_id)
        current = state["params"][selected_point_id]
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            current["one_x"] = st.slider("1× amplitude", 0.0, 1.5, float(current["one_x"]), 0.05,
                                         key=f"alpha21_one_{machine_id}_{selected_point_id}")
        with c2:
            current["four_x"] = st.slider("4× harmonic amplitude", 0.0, 1.0, float(current["four_x"]), 0.05,
                                          key=f"alpha21_four_{machine_id}_{selected_point_id}")
        with c3:
            current["noise"] = st.slider("Noise", 0.0, 0.2, float(current["noise"]), 0.01,
                                         key=f"alpha21_noise_{machine_id}_{selected_point_id}")
        with c4:
            current["impacts"] = st.slider("Synthetic impulses", 0.0, 1.0, float(current["impacts"]), 0.1,
                                           key=f"alpha21_impacts_{machine_id}_{selected_point_id}")
        st.caption("Change the selected sensor's controls while running. The other sensors retain their settings. "
                   "The 4× spectral component follows the selected RPM (rather than remaining fixed at 120 Hz).")

        if state["running"]:
            elapsed = now - state["started_at"]
            bucket = int(now // TICK_SECONDS)
            if bucket != state["last_bucket"]:
                timestamp = datetime.now(timezone.utc)
                for p in points:
                    sensor_id = p["id"]
                    config = state["params"][sensor_id]
                    signature = (rpm, config["one_x"], config["four_x"],
                                 config["noise"], config["impacts"])
                    previous = state["previous_configs"].get(sensor_id)
                    if previous is not None and signature != previous:
                        state["events"].append({"timestamp_utc": timestamp.isoformat(),
                                                "sensor": _point_name(p),
                                                "event": "Operator adjusted synthetic input"})
                    state["previous_configs"][sensor_id] = signature
                    frame = synthesize_frame(rpm=rpm, seed=bucket * 1000 + sensor_id,
                                             one_x=config["one_x"], four_x=config["four_x"],
                                             noise=config["noise"], impacts=config["impacts"])
                    state["latest"][sensor_id] = frame["rms"]
                    # Store only the latest short frame for display, not raw waveforms in DB.
                    state["frames"][sensor_id] = frame
                    state["records"].append({
                        "time_utc": timestamp,
                        "sensor": p["sensor_code"] or f"POINT-{sensor_id}",
                        "point_id": sensor_id,
                        "rms": frame["rms"],
                        "rpm": rpm,
                        "shaft_hz": round(frame["shaft_hz"], 3),
                        "source": "synthetic_live_demo",
                    })
                if len(state["records"]) > MAX_HISTORY_ROWS:
                    state["records"] = state["records"][-MAX_HISTORY_ROWS:]
                state["last_bucket"] = bucket
            st.success(f"SIMULATION RUNNING · {int(elapsed // 60)} min {int(elapsed % 60):02d} s elapsed · "
                       f"Updates every {TICK_SECONDS} seconds while this browser stays connected")
        else:
            st.info("SIMULATION STOPPED. Click Start to generate live data. "
                    "Previously generated readings remain available in this browser session.")

        st.subheader("Live RMS — four measurement locations")
        cols = st.columns(len(points))
        for col, p in zip(cols, points):
            with col:
                st.metric(p["sensor_code"] or f"Point {p['id']}",
                          f"{state['latest'][p['id']]:.4f}" if p["id"] in state["latest"] else "—")
                st.caption(p["name"])
        st.caption("All values are synthetic arbitrary-unit RMS readings; no condition limits are applied.")

        if state["records"]:
            df = pd.DataFrame(state["records"])
            st.subheader("Live RMS trend (UTC)")
            trend = df.pivot_table(index="time_utc", columns="sensor", values="rms", aggfunc="last")
            st.line_chart(trend)
            frame = state["frames"].get(selected_point_id)
            if frame:
                st.subheader("Selected sensor — waveform and spectrum")
                c1, c2 = st.columns(2)
                with c1:
                    t = np.arange(len(frame["samples"])) / frame["sample_rate_hz"]
                    st.line_chart(pd.DataFrame({"Time (s)": t[:250], "Vibration": frame["samples"][:250]}),
                                  x="Time (s)", y="Vibration")
                with c2:
                    keep = frame["freq_hz"] <= 250
                    st.line_chart(pd.DataFrame({"Frequency (Hz)": frame["freq_hz"][keep],
                                                "Amplitude": frame["spectrum"][keep]}),
                                  x="Frequency (Hz)", y="Amplitude")
                st.caption(f"At {rpm} RPM: 1× = {rpm / 60:.1f} Hz; 4× = {4 * rpm / 60:.1f} Hz. "
                           "These are simulated shaft-related components, not identified mechanical faults.")
            st.download_button("Download current session summaries (CSV)",
                               data=df.to_csv(index=False).encode("utf-8"),
                               file_name=f"{machine['ms_number']}_synthetic_live_session.csv",
                               mime="text/csv", key=f"alpha21_download_{machine_id}")
            if state["events"]:
                with st.expander("Simulation adjustments"):
                    st.dataframe(pd.DataFrame(state["events"][-50:]), use_container_width=True, hide_index=True)
        st.caption("No automatic Groq calls, Supabase writes, remote sensor connections or physical machinery alarms are performed in this tab.")

    _live_panel()
