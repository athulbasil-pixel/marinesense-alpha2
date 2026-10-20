"""MarineSense Alpha 2.1 — four virtual sensors and optional saved summaries.

Everything is synthetic; no physical sensor, safety alert, background worker or
validated fault diagnosis. Stored data consist of observed frames' one-minute
aggregates only, with events and an explicit simulation-session identifier.
"""
from __future__ import annotations

from datetime import datetime, timezone
import time

import numpy as np
import pandas as pd
import streamlit as st
from sqlalchemy.exc import SQLAlchemyError

import registry as reg
# Imports the three new metadata tables before registry.get_engine().
import live_history as history
from live_simulator import MAX_DEMO_HOURS, initial_parameters, synthesize_frame

TICK_SECONDS = 5
MAX_HISTORY_ROWS = MAX_DEMO_HOURS * 3600 // TICK_SECONDS * 4


def _point_name(point):
    return (point["sensor_code"] or f"Virtual #{point['id']}") + " · " + point["name"]


def _get_state(machine_id: int, points: list[dict]):
    key = f"alpha21_demo_{machine_id}"
    if key not in st.session_state:
        st.session_state[key] = {
            "running": False, "started_at": None, "started_utc": None,
            "last_bucket": None, "records": [], "latest": {}, "frames": {},
            "previous_configs": {}, "previous_rpm": None, "events": [],
            "params": {p["id"]: initial_parameters(i) for i, p in enumerate(points)},
            "recording": False, "session_id": None, "minute_acc": None,
            "store_error": None, "saved_rows": 0,
        }
    state = st.session_state[key]
    for i, p in enumerate(points):
        state["params"].setdefault(p["id"], initial_parameters(i))
    return state


def _remember_event(engine, state: dict, machine_id: int, kind: str, detail: str,
                    point_id: int | None = None):
    entry = {"timestamp_utc": datetime.now(timezone.utc).isoformat(),
             "point_id": point_id, "event": detail}
    if state["recording"]:
        history.log_event(engine, state["session_id"], machine_id, kind, detail,
                          point_id=point_id)
    state["events"].append(entry)


def _save_pending_window(engine, state: dict, machine_id: int, partial: bool):
    if not state["recording"] or not state["minute_acc"]:
        return
    accumulator = state["minute_acc"]
    saved = history.save_minute(engine, state["session_id"], machine_id,
                                state["started_utc"], accumulator, partial=partial)
    state["saved_rows"] += saved
    state["minute_acc"] = None


def _stop_demo(engine, state: dict, machine_id: int, reason: str):
    if not state["running"]:
        return
    if state["recording"]:
        _save_pending_window(engine, state, machine_id, partial=True)
        _remember_event(engine, state, machine_id, "simulation_stopped", reason)
        history.close_session(engine, state["session_id"], machine_id)
    state["running"] = False


def _tick(engine, state: dict, machine_id: int, points: list[dict], now: float,
          rpm: float):
    """At most once per 5-second wall-clock bucket, per active browser session."""
    bucket = int(now // TICK_SECONDS)
    if bucket == state["last_bucket"]:
        return
    elapsed_minute = int(max(0, (now - state["started_at"]) // 60))
    if state["recording"]:
        acc = state["minute_acc"]
        if acc is not None and acc["minute_index"] != elapsed_minute:
            # This is the summary of frames actually observed during the last
            # elapsed minute; browser downtime is not filled with fake data.
            _save_pending_window(engine, state, machine_id, partial=False)
        if state["minute_acc"] is None:
            state["minute_acc"] = history.make_accumulator(elapsed_minute)

    if state["previous_rpm"] is not None and rpm != state["previous_rpm"]:
        _remember_event(engine, state, machine_id, "shaft_speed_changed",
                        f"Simulated RPM: {state['previous_rpm']} → {rpm}")
    state["previous_rpm"] = rpm

    timestamp = datetime.now(timezone.utc)
    for point in points:
        point_id = point["id"]
        config = state["params"][point_id]
        signature = (config["one_x"], config["four_x"], config["noise"], config["impacts"])
        previous = state["previous_configs"].get(point_id)
        if previous is not None and signature != previous:
            labels = ("1×", "4×", "noise", "impulses")
            changes = ", ".join(f"{label}: {old:g} → {new:g}" for label, old, new
                                in zip(labels, previous, signature) if old != new)
            _remember_event(engine, state, machine_id, "sensor_input_changed",
                            f"Synthetic input changed: {changes}", point_id=point_id)
        state["previous_configs"][point_id] = signature
        frame = synthesize_frame(rpm=rpm, seed=bucket * 1000 + point_id,
                                 one_x=config["one_x"], four_x=config["four_x"],
                                 noise=config["noise"], impacts=config["impacts"])
        state["latest"][point_id] = frame["rms"]
        state["frames"][point_id] = frame  # only latest short waveform in memory
        state["records"].append({
            "time_utc": timestamp, "sensor": point["sensor_code"] or f"POINT-{point_id}",
            "point_id": point_id, "rms": frame["rms"], "rpm": rpm,
            "shaft_hz": round(frame["shaft_hz"], 3), "source": "synthetic_live_demo",
        })
        if state["recording"]:
            history.observe(state["minute_acc"], point, frame, rpm)
    if len(state["records"]) > MAX_HISTORY_ROWS:
        state["records"] = state["records"][-MAX_HISTORY_ROWS:]
    state["last_bucket"] = bucket


def _historical_view(engine, machine_id: int):
    st.divider()
    st.subheader("Saved live demonstration history")
    st.caption("These are simulation-session records from Supabase, not raw waveforms or validated fault events.")
    sessions = history.list_sessions(engine, machine_id)
    if not sessions:
        st.info("No stored simulation session yet. Enable database recording before pressing Start.")
        return
    session_id = st.selectbox("Historical simulation session", [s["id"] for s in sessions],
                              format_func=lambda sid: next(f"{s['started_utc']} · {sid[:8]}" for s in sessions
                                                           if s["id"] == sid),
                              key=f"alpha21_history_session_{machine_id}")
    st.caption("This history includes partial minutes and records only actual browser-connected observations.")
    rows = history.list_minutes(engine, session_id)
    if rows:
        df = pd.DataFrame(rows).sort_values("time_utc")
        st.dataframe(df, hide_index=True, use_container_width=True)
        st.download_button("Download stored live summaries (CSV)", df.to_csv(index=False),
                           file_name=f"{session_id}_live_summaries.csv", mime="text/csv",
                           key=f"alpha21_persist_download_{machine_id}")
        trend = df.pivot_table(index="time_utc", columns="sensor", values="avg_rms", aggfunc="last")
        st.line_chart(trend)
    else:
        st.info("Session opened but no minute summaries have been saved yet.")
    events = history.list_events(engine, session_id)
    if events:
        st.caption("Operator changes and session-stop events (synthetic test inputs).")
        st.dataframe(pd.DataFrame(events), hide_index=True, use_container_width=True)


def render_live_dashboard(engine):
    st.header("Alpha 2.1 · Live virtual sensor demonstration")
    st.warning("SIMULATED DATA ONLY — no OEM sensor connected; no physical machinery fault diagnosis or safety alarm.")
    st.caption("This simulator runs only in an active browser session. Optional one-minute summary recording "
               "does not make Streamlit a continuous, unattended data-acquisition system.")
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
        st.info("Alpha 2.1's first simulator displays the first four registered sensor locations only.")
    points = points[:4]
    if len(points) < 4:
        st.info(f"{len(points)} sensor location(s) registered; the initial target is four.")
    st.caption(f"Machine: {machine['ms_number']} · {machine['name']} · SIMULATION only; RMS values are arbitrary.")
    state = _get_state(machine_id, points)

    @st.fragment(run_every=f"{TICK_SECONDS}s")
    def _live_panel():
        now = time.time()
        st.subheader("Simulation operator controls")
        persist_option = st.checkbox("Save one-minute simulation summaries and operator events to Supabase",
                                     value=False, disabled=state["running"],
                                     key=f"alpha21_record_{machine_id}")
        if persist_option:
            st.caption("A new recorded session is created on Start. One summary per sensor per observed minute; "
                       "a partial final minute is saved on Stop. No raw waveforms or AI calls are saved.")
            if engine.dialect.name != "postgresql":
                st.warning("A permanent PostgreSQL DATABASE_URL is required. SQLite fallback is temporary.")
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
            if persist_option and engine.dialect.name != "postgresql":
                st.error("Cannot start persistent recording without the permanent PostgreSQL database.")
            else:
                session_id = None
                try:
                    if persist_option:
                        session_id = history.open_session(engine, machine_id, [p["id"] for p in points])
                    state.update(running=True, started_at=now,
                                 started_utc=datetime.now(timezone.utc), last_bucket=None,
                                 recording=bool(persist_option), session_id=session_id,
                                 minute_acc=None, store_error=None, saved_rows=0,
                                 previous_rpm=None)
                    for key in ("records", "latest", "frames", "events", "previous_configs"):
                        state[key].clear()
                except (SQLAlchemyError, OSError, ValueError) as exc:
                    st.error("Could not open a recorded session. Nothing was started or written; "
                             "check the database connection and registered sensor IDs.")
        if stop:
            try:
                _stop_demo(engine, state, machine_id, "Operator stopped the simulated session")
            except (SQLAlchemyError, OSError, ValueError):
                state["running"] = False
                state["store_error"] = "Recording could not be finalised; inspect database connectivity. " \
                                       "Current browser-session CSV is still available."
        if state["running"] and now - state["started_at"] >= MAX_DEMO_HOURS * 3600:
            try:
                _stop_demo(engine, state, machine_id, "Three-hour maximum demo reached")
            except (SQLAlchemyError, OSError, ValueError):
                state["running"] = False
                state["store_error"] = "Maximum duration reached but the last summary could not be saved."
            st.info("Three-hour maximum reached; simulation stopped.")

        selected_point_id = st.selectbox("Adjust virtual sensor", [p["id"] for p in points],
                                         format_func=lambda i: _point_name(next(p for p in points if p["id"] == i)),
                                         key=f"alpha21_sensor_selector_{machine_id}")
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
        st.caption("Changes affect only the selected virtual sensor. The 4× component follows simulated RPM.")

        if state["running"]:
            try:
                _tick(engine, state, machine_id, points, now, rpm)
            except (SQLAlchemyError, OSError, ValueError):
                state["running"] = False
                state["store_error"] = ("Database recording failed. Live simulation was paused instead "
                                       "of silently losing history. Export browser-session CSV if needed.")
        if state["store_error"]:
            st.error(state["store_error"])
        if state["running"]:
            elapsed = now - state["started_at"]
            st.success(f"SIMULATION RUNNING · {int(elapsed // 60)} min {int(elapsed % 60):02d} s elapsed · "
                       f"Updates every {TICK_SECONDS} seconds while this browser stays connected")
        else:
            st.info("SIMULATION STOPPED. Start to generate live data. Previous session readings "
                    "remain temporarily available in this browser session.")
        if state["recording"]:
            st.caption(f"Database recording: {'ACTIVE' if state['running'] else 'SESSION ENDED'} · "
                       f"Saved minute rows: {state['saved_rows']} · "
                       f"Session: {state['session_id'][:8] if state['session_id'] else 'none'}")
        else:
            st.caption("Database recording OFF: browser-session readings are not persistent.")

        st.subheader("Live RMS — four measurement locations")
        cols = st.columns(len(points))
        for col, point in zip(cols, points):
            with col:
                st.metric(point["sensor_code"] or f"Point {point['id']}",
                          f"{state['latest'][point['id']]:.4f}" if point["id"] in state["latest"] else "—")
                st.caption(point["name"])
        st.caption("Arbitrary-unit synthetic readings; no condition limits or fault severity classifications.")
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
                           "Simulated shaft-related components, not identified mechanical faults.")
            st.download_button("Download current browser-session summaries (CSV)",
                               data=df.to_csv(index=False).encode("utf-8"),
                               file_name=f"{machine['ms_number']}_synthetic_live_session.csv",
                               mime="text/csv", key=f"alpha21_download_{machine_id}")
            if state["events"]:
                with st.expander("Recent simulation adjustments"):
                    st.dataframe(pd.DataFrame(state["events"][-50:]), use_container_width=True, hide_index=True)

        if st.checkbox("Browse persistent live history (including after reboot)", value=False,
                       key=f"alpha21_browse_{machine_id}"):
            try:
                _historical_view(engine, machine_id)
            except (SQLAlchemyError, OSError):
                st.error("Couldn't read historical records from Supabase. Check the database connection.")
        st.caption("No automatic Groq calls, OEM connections, unattended monitoring or physical alarms "
                   "are performed on this tab.")

    _live_panel()
