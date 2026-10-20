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
    st.subheader("Historical Record · Recorded Demonstration Sessions")
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
        st.line_chart(trend, height=300)
    else:
        st.info("Session opened but no minute summaries have been saved yet.")
    events = history.list_events(engine, session_id)
    if events:
        st.caption("Operator changes and session-stop events (synthetic test inputs).")
        st.dataframe(pd.DataFrame(events), hide_index=True, use_container_width=True)


def _shipboard_style():
    """Display-only CSS; no status colours imply validated machinery severity."""
    st.markdown("""
    <style>
      .ms-hero { background:linear-gradient(115deg,#102b3f,#183f54); padding:1.15rem 1.3rem;
          border-radius:13px; color:#f2f8fb; margin:.4rem 0 1rem; border:1px solid #315567; }
      .ms-eyebrow {font-size:.73rem;letter-spacing:.13em;font-weight:700;color:#a5d4e1;}
      .ms-title {font-size:1.85rem;font-weight:730;line-height:1.15;margin:.35rem 0;}
      .ms-sub {color:#d8e8ed;font-size:.87rem;margin-top:.45rem;}
      .ms-strip {display:flex;gap:.45rem;flex-wrap:wrap;margin:.6rem 0 .9rem;}
      .ms-chip {padding:.4rem .65rem;border-radius:7px;background:#e9f1f4;
          border:1px solid #cadce4;color:#173d4f;font-weight:650;font-size:.8rem;}
      .ms-card {padding:.85rem 1rem;border:1px solid #cbdae2;border-top:4px solid #29758b;
          border-radius:10px;background:#f6fafc;min-height:128px;}
      .ms-card-id {font-size:.75rem;letter-spacing:.06em;color:#3b6276;font-weight:750;}
      .ms-card-value {font-size:1.7rem;font-weight:770;color:#123648;margin:.5rem 0 .15rem;
          font-variant-numeric:tabular-nums;}
      .ms-card-caption {font-size:.8rem;color:#436474;line-height:1.4;}
      .ms-note {font-size:.8rem;color:#5e7180;margin:.55rem 0;}
      @media (prefers-color-scheme: dark) {
        .ms-chip {background:#1e3948;color:#d8eef5;border-color:#426372;}
        .ms-card {background:#183040;border-color:#355364;border-top-color:#4eacc5;}
        .ms-card-id,.ms-card-value,.ms-card-caption,.ms-note {color:#e1edf4;}
      }
    </style>""", unsafe_allow_html=True)


def _sensor_cards(points, latest):
    """Render four fixed-position readouts. Unmeasured sensors remain unclassified."""
    import html
    cols = st.columns(len(points))
    for col, point in zip(cols, points):
        with col:
            val = latest.get(point["id"])
            reading = f"{val:.4f}" if val is not None else "—"
            name = html.escape(str(point["name"]))
            code = html.escape(str(point["sensor_code"] or f"POINT-{point['id']}"))
            st.markdown(f"""<div class="ms-card"><div class="ms-card-id">{code}</div>
               <div class="ms-card-value">{reading}</div>
               <div class="ms-card-caption">RMS · arbitrary units<br>{name}</div></div>""",
               unsafe_allow_html=True)


def render_live_dashboard(engine):
    _shipboard_style()
    st.markdown("""<div class="ms-hero"><div class="ms-eyebrow">MARINESENSE | MACHINERY MONITORING</div>
    <div class="ms-title">Live Machinery Overview</div>
    <div class="ms-sub">Four-point vibration monitoring · engineering demonstration environment</div></div>""",
    unsafe_allow_html=True)
    st.warning("SIMULATED SIGNALS · NO OEM SENSORS · NO CERTIFIED ALARMS OR FAULT DIAGNOSIS")
    st.caption("Active-browser simulator only. Persistent summaries are stored only when recording is enabled; "
               "no unattended monitoring is performed.")
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
    st.markdown(f"**Selected asset:** {machine['ms_number']} · {machine['name']}")
    st.caption("SIMULATION ONLY · 1× and 4× are simulated shaft-related frequencies · RMS in arbitrary units")
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
        status = "SIMULATION ACTIVE" if state["running"] else "SIMULATION STOPPED"
        recording_status = "RECORDING ON" if state["recording"] and state["running"] else (
            "RECORDED SESSION CLOSED" if state["recording"] else "RECORDING OFF")
        st.markdown('<div class="ms-strip"><span class="ms-chip">' + status +
                    '</span><span class="ms-chip">' + recording_status +
                    '</span><span class="ms-chip">4 SENSOR POSITIONS (MAX)</span></div>',
                    unsafe_allow_html=True)
        if state["recording"]:
            st.caption(f"Saved sensor-minute rows: {state['saved_rows']} · "
                       f"Session: {state['session_id'][:8] if state['session_id'] else 'none'}")
        else:
            st.caption("Recording OFF · live readings held temporarily in this browser session")

        st.subheader("Machinery Overview · Four Sensor Positions")
        _sensor_cards(points, state["latest"])
        st.caption("Numeric signal indicators only. No alarm limits, health scoring or condition severity categories are applied.")
        if state["records"]:
            df = pd.DataFrame(state["records"])
            st.subheader("RMS Time Trend · All Measurement Positions")
            trend = df.pivot_table(index="time_utc", columns="sensor", values="rms", aggfunc="last")
            st.line_chart(trend, height=305)
            st.caption("UTC timestamps · Five-second observed updates · gaps are not reconstructed")
            frame = state["frames"].get(selected_point_id)
            if frame:
                st.subheader("Selected Sensor · Waveform and Frequency Spectrum")
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
