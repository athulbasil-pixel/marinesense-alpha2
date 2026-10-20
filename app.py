"""MarineSense Alpha 2.0 - demo machinery registry + configuration-aware vibration analysis.

Not a validated diagnostic system or hardened multi-user fleet platform.
"""
from __future__ import annotations

import hmac
import io
import json
import os
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import streamlit as st
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

import registry as reg
from live_dashboard import render_live_dashboard
from analysis import compute_vibration, example_signals
from engineering import make_evidence, sha256_samples, SYSTEM_PROMPT

st.set_page_config(page_title="MarineSense | Alpha 2.1", page_icon="⚓", layout="wide")


def read_secret(key: str) -> str:
    try:
        return str(st.secrets.get(key, ""))
    except (FileNotFoundError, KeyError):
        return ""


st.title("⚓ MarineSense")
st.caption("Alpha 2.1 · Machinery registry + evidence-based analysis + live virtual sensors + history")
st.warning("Prototype only — not a certified monitoring, alarm, predictive-maintenance or safety system.")

# A single shared demo code is a temporary gate, NOT production user authentication.
passcode = read_secret("DEMO_PASSCODE")
if not passcode:
    st.error("Access closed: set DEMO_PASSCODE in Streamlit Secrets before using Alpha 2.0.")
    st.stop()

if not st.session_state.get("authorized_alpha2", False):
    with st.form("demo_login"):
        entered = st.text_input("MarineSense demonstration access code", type="password")
        submitted = st.form_submit_button("Enter Alpha 2.0")
    if submitted:
        if entered and hmac.compare_digest(entered, passcode):
            st.session_state["authorized_alpha2"] = True
            st.rerun()
        else:
            st.error("Invalid code.")
    st.stop()

with st.sidebar:
    st.success("Demo access enabled")
    if st.button("Sign out"):
        st.session_state.clear()
        st.rerun()
    st.caption("Use only synthetic or non-confidential authorised test records.")

# PostgreSQL is optional; SQLite fallback is non-durable on Streamlit Community Cloud.
db_url = read_secret("DATABASE_URL")
if not db_url:
    Path(".demo_data").mkdir(exist_ok=True)
    db_url = "sqlite:///./.demo_data/marinesense_alpha2.sqlite3"
    st.info("**Temporary demo storage:** no DATABASE_URL configured. Registry data may disappear after a Streamlit restart or redeployment. Export or use external PostgreSQL before relying on permanent machine IDs.")
else:
    st.caption("Registry connected to configured database. This is still a shared-passcode demonstration, not a production secure multi-tenant service.")

try:
    engine = reg.get_engine(db_url)
except (SQLAlchemyError, OSError) as exc:
    st.error("Database could not be started. Check the DATABASE_URL and database permissions. Do not share credentials in screenshots.")
    st.stop()


def labels(objects, label_field="name"):
    return {o["id"]: f"{o[label_field]} (ID {o['id']})" for o in objects}


def machine_label(m):
    return f"{m['ms_number']} · {m['name']} [{m['tag']}]"


def get_machine_selection(key):
    machines = reg.list_machines(engine)
    if not machines:
        st.warning("Register a machinery assembly first.")
        return None
    ids = [m["id"] for m in machines]
    selected = st.selectbox("Select registered machinery", ids, format_func=lambda i: machine_label(next(m for m in machines if m["id"] == i)), key=key)
    return next(m for m in machines if m["id"] == selected)


def show_machine(m):
    st.subheader(f"{m['ms_number']} · {m['name']}")
    st.caption(f"Equipment tag: {m['tag']} · {m['equipment_type']}")
    c1,c2,c3 = st.columns(3)
    c1.metric("Rated RPM (reference)", f"{m['rated_rpm']:g}" if m['rated_rpm'] else "Unknown")
    c2.metric("Rated kW", f"{m['rated_power_kw']:g}" if m['rated_power_kw'] else "Unknown")
    c3.metric("Serial", m["serial"] or "Unspecified")
    st.caption(f"Manufacturer: {m['manufacturer'] or 'Unknown'} · Model: {m['model'] or 'Unknown'}")
    if m["description"]:
        st.write(m["description"])


def numeric_or_none(n):
    return float(n) if n and n > 0 else None


def notice_exception(exc):
    if isinstance(exc, IntegrityError):
        st.error("This record conflicts with an existing name or tag. Use a unique value within its fleet/vessel.")
    else:
        st.error("Could not save this record. Please check the fields and connection.")


def upload_csv(upload) -> np.ndarray:
    table = pd.read_csv(io.BytesIO(upload.getvalue()), encoding="utf-8-sig")
    if table.empty:
        raise ValueError("CSV contains no rows")
    name_map = {str(c).strip().lower(): c for c in table.columns}
    if "vibration" in name_map:
        column = name_map["vibration"]
    elif "value" in name_map:
        column = name_map["value"]
    elif len(table.columns) == 1:
        column = table.columns[0]
    else:
        raise ValueError("Provide a column named 'vibration', or one numeric column")
    result = pd.to_numeric(table[column], errors="coerce").to_numpy(dtype=float)
    if not np.isfinite(result).all():
        raise ValueError("CSV contains non-numeric or missing values")
    return result


def plot_results(base, test, unit):
    fig, axes = plt.subplots(2, 2, figsize=(11, 5.5))
    for i, (r, title) in enumerate(((base, "Baseline"), (test, "Test"))):
        n = min(r["sample_count"], max(1, int(0.25 * r["sample_rate_hz"])))
        time_s = np.arange(n) / r["sample_rate_hz"]
        axes[i, 0].plot(time_s, r["values"][:n], lw=1.0)
        axes[i, 0].set(title=f"{title} · waveform", xlabel="Time (s)", ylabel=f"Vibration ({unit})")
        axes[i, 1].plot(r["frequency"], r["spectrum"], lw=1.0)
        axes[i, 1].set_xlim(0, min(250, r["sample_rate_hz"] / 2))
        axes[i, 1].set(title=f"{title} · FFT", xlabel="Frequency (Hz)", ylabel=f"Amplitude ({unit})")
        for a in axes[i]:
            a.grid(alpha=0.18)
    fig.tight_layout()
    return fig


def groq_interpret(payload, system=SYSTEM_PROMPT):
    from groq import Groq
    client = Groq(api_key=read_secret("GROQ_API_KEY"))
    resp = client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": json.dumps(payload, default=str)}],
        reasoning_effort="low",
        max_completion_tokens=1400,
    )
    answer = resp.choices[0].message.content
    if not answer:
        raise RuntimeError("The model returned no report text")
    return answer


tab_fleet, tab_machinery, tab_analysis, tab_history, tab_live = st.tabs([
    "1 · Fleet & vessels", "2 · Machinery registry", "3 · Analyse & AI",
    "4 · Measurements & reports", "5 · Live simulator (2.1)"
])

with tab_fleet:
    st.header("Fleet & vessel registry")
    with st.form("new_fleet", clear_on_submit=True):
        st.subheader("Register fleet")
        fleet_name = st.text_input("Fleet name *", max_chars=150)
        fleet_operator = st.text_input("Operator (optional)", max_chars=150)
        if st.form_submit_button("Create fleet"):
            if not fleet_name.strip():
                st.error("Fleet name is required")
            else:
                try:
                    fid = reg.create_fleet(engine, fleet_name, fleet_operator)
                    st.success(f"Fleet registered (ID {fid}).")
                except (SQLAlchemyError, ValueError) as exc:
                    notice_exception(exc)
    fleets = reg.list_fleets(engine)
    if fleets:
        with st.form("new_vessel", clear_on_submit=True):
            st.subheader("Register vessel")
            fleet_id = st.selectbox("Fleet *", [x["id"] for x in fleets],
                                    format_func=lambda i: next(x["name"] for x in fleets if x["id"] == i))
            vessel_name = st.text_input("Vessel name *", max_chars=150)
            imo = st.text_input("IMO number (optional)", max_chars=20,
                                help="Use non-confidential demo values while testing")
            if st.form_submit_button("Add vessel"):
                if not vessel_name.strip():
                    st.error("Vessel name is required")
                else:
                    try:
                        vid = reg.create_vessel(engine, fleet_id, vessel_name, imo)
                        st.success(f"Vessel registered (ID {vid}).")
                    except (SQLAlchemyError, ValueError) as exc:
                        notice_exception(exc)
        st.subheader("Registered fleets")
        st.dataframe(pd.DataFrame(fleets), hide_index=True, use_container_width=True)
        vessels = reg.list_vessels(engine)
        if vessels:
            st.subheader("Registered vessels")
            st.dataframe(pd.DataFrame(vessels), hide_index=True, use_container_width=True)
    else:
        st.info("Start by registering a fleet, or create an example demo hierarchy.")
        if st.button("Create sample fleet + vessel + pump + sensor", type="secondary"):
            try:
                reg.make_example_registry(engine)
                st.rerun()
            except SQLAlchemyError:
                st.error("Could not create demo records")

with tab_machinery:
    st.header("Machinery assembly registry")
    action = st.radio("Choose an option", ["Existing registered machinery", "Register new machinery"], horizontal=True)
    if action == "Register new machinery":
        vessels = reg.list_vessels(engine)
        if not vessels:
            st.warning("Create a fleet and vessel in the first tab before registering machinery.")
        else:
            with st.form("machine_form", clear_on_submit=True):
                vessel_id = st.selectbox("Vessel *", [v["id"] for v in vessels],
                                         format_func=lambda i: next(v["name"] for v in vessels if v["id"] == i))
                c1,c2 = st.columns(2)
                name = c1.text_input("Machinery assembly name *", max_chars=150)
                tag = c2.text_input("Vessel machinery tag *", max_chars=100, placeholder="ACWP-01")
                eqtype = st.selectbox("Machinery type *", ["Centrifugal Pump Assembly", "Electric Motor", "Fan Assembly", "Air Compressor", "Diesel Generator", "Other"])
                c1,c2,c3 = st.columns(3)
                maker = c1.text_input("Manufacturer", max_chars=120)
                model = c2.text_input("Model", max_chars=120)
                serial = c3.text_input("Manufacturer serial number", max_chars=120)
                c1,c2 = st.columns(2)
                rated_rpm = c1.number_input("Rated RPM (nameplate; 0 if unknown)", min_value=0.0, max_value=100000.0, value=0.0, step=50.0)
                power = c2.number_input("Rated power kW (0 if unknown)", min_value=0.0, max_value=100000.0, value=0.0, step=1.0)
                note = st.text_area("Configuration notes (optional)", max_chars=1000)
                if st.form_submit_button("Register machinery and generate MarineSense number", type="primary"):
                    if not name.strip() or not tag.strip():
                        st.error("Machinery name and equipment tag are required")
                    else:
                        try:
                            num = reg.create_machine(engine, vessel_id=vessel_id, name=name.strip(), tag=tag.strip(),
                                equipment_type=eqtype, manufacturer=maker.strip(), model=model.strip(),
                                serial=serial.strip(), rated_rpm=numeric_or_none(rated_rpm),
                                rated_power_kw=numeric_or_none(power), description=note.strip())
                            st.success(f"Registered machinery ID: **{num}**. It is generated by the database.")
                        except (SQLAlchemyError, ValueError) as exc:
                            notice_exception(exc)
    else:
        m = get_machine_selection("existing_registry_machine")
        if m:
            show_machine(m)
            st.caption("You may also find a machine by typing its exact MarineSense number below.")
            search_no = st.text_input("Find by MarineSense number", placeholder="MS-000001", max_chars=20)
            if search_no:
                found = reg.get_machine_by_number(engine, search_no)
                st.success(f"Found: {machine_label(found)}") if found else st.warning("No machine matches that number")
            components = reg.list_components(engine, m["id"])
            st.subheader("Components")
            if components:
                st.dataframe(pd.DataFrame(components), hide_index=True, use_container_width=True)
            with st.form(f"component_{m['id']}", clear_on_submit=True):
                st.markdown("**Add component**")
                c1,c2 = st.columns(2)
                c_name = c1.text_input("Component name *", placeholder="Electric Motor")
                c_type = c2.selectbox("Component category", ["Motor", "Pump", "Coupling", "Gearbox", "Bearing Assembly", "Other"])
                c1,c2,c3 = st.columns(3)
                c_maker = c1.text_input("Component manufacturer")
                c_model = c2.text_input("Component model")
                bearing = c3.text_input("Bearing model (if known)")
                c_notes = st.text_input("Component notes (optional)")
                if st.form_submit_button("Add component"):
                    if not c_name.strip():
                        st.error("Component name is required")
                    else:
                        try:
                            reg.create_component(engine, machine_id=m["id"], name=c_name.strip(), category=c_type,
                                                 manufacturer=c_maker.strip(), model=c_model.strip(), bearing_model=bearing.strip(), notes=c_notes.strip())
                            st.success("Component saved")
                            st.rerun()
                        except (SQLAlchemyError, ValueError) as exc:
                            notice_exception(exc)
            if components:
                with st.form(f"point_{m['id']}", clear_on_submit=True):
                    st.markdown("**Register sensor location**")
                    cid = st.selectbox("Component", [c["id"] for c in components],
                                      format_func=lambda i: next(c["name"] for c in components if c["id"] == i))
                    point_name = st.text_input("Measurement position *", placeholder="Motor drive-end bearing")
                    direction = st.selectbox("Measurement direction", ["Horizontal", "Vertical", "Axial", "Radial", "Other"])
                    c1,c2 = st.columns(2)
                    sensor_code = c1.text_input("Sensor identifier (optional)", placeholder="SEN-0001")
                    sensor_oem = c2.text_input("OEM sensor supplier (optional)")
                    c1,c2 = st.columns(2)
                    sensor_model = c1.text_input("OEM model (optional)")
                    unit = c2.selectbox("Measurement unit", ["arbitrary", "g", "m/s²", "mm/s", "µm"])
                    if st.form_submit_button("Add sensor location"):
                        if not point_name.strip():
                            st.error("A measurement position is required")
                        else:
                            try:
                                reg.create_sensor_point(engine, component_id=cid, name=point_name.strip(),
                                                        direction=direction, sensor_code=sensor_code.strip(),
                                                        oem=sensor_oem.strip(), sensor_model=sensor_model.strip(),
                                                        sensor_type="Accelerometer" if unit in ("g", "m/s²", "arbitrary") else "Other vibration transducer", unit=unit)
                                st.success("Measurement position saved")
                                st.rerun()
                            except (SQLAlchemyError, ValueError) as exc:
                                notice_exception(exc)
                points = reg.list_sensor_points(engine, [c["id"] for c in components])
                if points:
                    st.subheader("Registered sensor locations")
                    st.dataframe(pd.DataFrame(points), hide_index=True, use_container_width=True)

with tab_analysis:
    st.header("Machinery-aware vibration analysis")
    m = get_machine_selection("analysis_machine")
    if m:
        components = reg.list_components(engine, m["id"])
        points = reg.list_sensor_points(engine, [c["id"] for c in components])
        if not points:
            st.warning("Add a component and sensor location in the Machinery registry tab first.")
        else:
            point_id = st.selectbox("Sensor location", [p["id"] for p in points],
                                   format_func=lambda i: next(f"{p['name']} · {p['direction']} (ID {i})" for p in points if p["id"] == i))
            sensor = next(p for p in points if p["id"] == point_id)
            component = next(c for c in components if c["id"] == sensor["component_id"])
            show_machine(m)
            st.markdown(f"**Component:** {component['name']} · **Sensor location:** {sensor['name']} ({sensor['direction']})")
            use_demo = st.toggle("Use built-in synthetic Day 1 vibration signals", value=True)
            c1,c2,c3 = st.columns(3)
            fs = c1.number_input("Sampling rate (Hz)", min_value=2, max_value=20000, value=1000, step=100, disabled=use_demo)
            units = c2.selectbox("Units for uploaded waveform", ["arbitrary", "g", "m/s²", "mm/s", "µm"],
                                 index=0 if use_demo else (["arbitrary", "g", "m/s²", "mm/s", "µm"].index(sensor["unit"])), disabled=use_demo)
            actual_known = c3.checkbox("Actual operating RPM known", value=False, help="Actual observed RPM, not rated/nameplate RPM")
            rpm = st.number_input("RPM at measurement (not rated RPM)", min_value=1.0, max_value=100000.0,
                                  value=1800.0, step=10.0, disabled=not actual_known)
            load = st.text_input("Operating load / condition (if known)", placeholder="e.g. 70% load, steady state", max_chars=120)
            base_upload = test_upload = None
            if not use_demo:
                c1,c2 = st.columns(2)
                base_upload = c1.file_uploader("Baseline waveform CSV", type="csv", key="alpha2_base")
                test_upload = c2.file_uploader("Test waveform CSV", type="csv", key="alpha2_test")
                st.caption("CSV files must share calibrated units, comparable operating conditions and the specified sample rate. The app cannot independently verify these assumptions.")
            else:
                units = "arbitrary"
                st.info("Synthetic signal: 30 Hz baseline and added 120 Hz component in test. Synthetic sensor data never constitutes a real condition alarm.")

            if st.button("📈 Analyse and save measurement summary", type="primary"):
                try:
                    if use_demo:
                        raw_base, raw_test = example_signals()
                        fs_actual = 1000
                    else:
                        if base_upload is None or test_upload is None:
                            raise ValueError("Upload both baseline and test files")
                        raw_base = upload_csv(base_upload)
                        raw_test = upload_csv(test_upload)
                        fs_actual = int(fs)
                    base = compute_vibration(raw_base, fs_actual)
                    test = compute_vibration(raw_test, fs_actual)
                    evidence = make_evidence(m, component, sensor, base, test,
                        "synthetic simulation" if use_demo else "user-uploaded, unvalidated",
                        units, float(rpm) if actual_known else None, load)
                    measurement_id = reg.create_measurement(engine,
                        machine_id=m["id"], point_id=sensor["id"],
                        source=evidence["source"], unit=units, sample_rate_hz=float(fs_actual),
                        sample_count_baseline=base["sample_count"], sample_count_test=test["sample_count"],
                        actual_rpm=float(rpm) if actual_known else None, operating_load=load,
                        baseline_rms=base["rms"], test_rms=test["rms"],
                        rms_change_pct=evidence["rms_change_percent"],
                        peaks_baseline_json=json.dumps(base["peaks"]),
                        peaks_test_json=json.dumps(test["peaks"]),
                        baseline_sha256=sha256_samples(raw_base),
                        test_sha256=sha256_samples(raw_test),
                        configuration_snapshot_json=json.dumps(evidence, ensure_ascii=False),
                    )
                    st.session_state["alpha2_results"] = {
                        "machine_id": m["id"], "point_id": point_id,
                        "baseline": base, "test": test, "evidence": evidence,
                        "measurement_id": measurement_id, "unit": units,
                    }
                    st.session_state.pop("alpha2_report", None)
                    st.session_state.pop("alpha2_comparison", None)
                    st.success(f"Measurement #{measurement_id} saved against {m['ms_number']}.")
                except (ValueError, pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeDecodeError) as exc:
                    st.error(f"Cannot analyse input: {exc}")
                except SQLAlchemyError:
                    st.error("Measurement could not be saved; check database connectivity.")

            result = st.session_state.get("alpha2_results")
            if result and result["machine_id"] == m["id"] and result["point_id"] == point_id:
                base, test, evidence = result["baseline"], result["test"], result["evidence"]
                st.subheader("Signal analysis")
                a,b,c = st.columns(3)
                a.metric("Baseline RMS", f"{base['rms']:.4f}")
                b.metric("Test RMS", f"{test['rms']:.4f}")
                c.metric("RMS change", f"{evidence['rms_change_percent']:+.1f}%")
                fig = plot_results(base, test, result["unit"])
                st.pyplot(fig, clear_figure=True)
                plt.close(fig)
                if evidence["operating_rpm_measured_or_operator_entered"]:
                    st.write("**Frequency peaks and calculated shaft orders (using operator-supplied actual RPM)**")
                    st.dataframe(pd.DataFrame(evidence["test"]["peaks"]), hide_index=True)
                else:
                    st.caption("Shaft-order analysis unavailable because actual operating RPM was not supplied.")
                for issue in evidence["validation_notes"]:
                    st.caption("⚠️ " + issue)
                with st.expander("See engineering evidence passed to AI"):
                    st.json(evidence)
                st.download_button("Download measurement analysis (JSON)", json.dumps(evidence, indent=2),
                                   file_name=f"{m['ms_number']}_analysis.json", mime="application/json")
                st.subheader("AI engineering interpretation")
                st.caption("Only summary metrics and entered configuration are sent to Groq, not the uploaded waveform. Avoid entering real confidential vessel details during public demo testing.")
                groq_key = read_secret("GROQ_API_KEY")
                if not groq_key:
                    st.warning("Add GROQ_API_KEY in Streamlit Secrets to enable AI reports. Signal analysis still works.")
                elif st.button("🤖 Generate machinery-aware AI report"):
                    try:
                        with st.spinner("Generating grounded engineering report..."):
                            body = groq_interpret(evidence)
                        reg.create_report(engine, result["measurement_id"], "openai/gpt-oss-120b", body)
                        st.session_state["alpha2_report"] = body
                    except Exception:
                        st.error("AI report failed; check configured secrets, model access and service limits. No API key should be shared.")
                if st.session_state.get("alpha2_report"):
                    st.markdown(st.session_state["alpha2_report"])
                    st.download_button("Download AI engineering report", st.session_state["alpha2_report"],
                        file_name=f"{m['ms_number']}_engineering_report.md", mime="text/markdown")
                if groq_key:
                    with st.expander("Experimental: compare AI with and without machinery configuration"):
                        st.caption("Two API requests. This measures specificity of explanations, NOT fault prediction accuracy.")
                        if st.button("Run comparison (two AI calls)"):
                            no_context = {"source": evidence["source"], "unit": evidence["unit"],
                                "baseline": evidence["baseline"], "test": evidence["test"],
                                "rms_change_percent": evidence["rms_change_percent"],
                                "note": "Machine speed, type, bearing, location are intentionally withheld"}
                            # Avoid exposing derived shaft orders in no-context condition.
                            for key in ("baseline", "test"):
                                no_context[key] = {"rms": no_context[key]["rms"], "peaks": [
                                    {k: v for k,v in p.items() if k != "shaft_order"}
                                    for p in no_context[key]["peaks"]]}
                            try:
                                with st.spinner("Generating side-by-side explanations..."):
                                    a = groq_interpret(no_context)
                                    b = groq_interpret(evidence)
                                st.session_state["alpha2_comparison"] = {"no_context": a, "context": b}
                            except Exception:
                                st.error("Comparison could not complete (API limits or network).")
                        comparison = st.session_state.get("alpha2_comparison")
                        if comparison:
                            c1,c2 = st.columns(2)
                            c1.markdown("**Without machinery configuration**")
                            c1.markdown(comparison["no_context"])
                            c2.markdown("**With machinery configuration**")
                            c2.markdown(comparison["context"])
                            st.info("Neither output is a validated fault classification. A labelled dataset is required to measure diagnostic accuracy.")

with tab_history:
    st.header("Machine-linked measurements and reports")
    m = get_machine_selection("history_machine")
    if m:
        st.caption(f"History for {m['ms_number']}; only numeric summaries and generated reports are stored. Raw waveforms are not retained on the server.")
        measurements = reg.get_recent_measurements(engine, m["id"])
        if measurements:
            st.dataframe(pd.DataFrame(measurements), hide_index=True, use_container_width=True)
            st.download_button("Download recent measurement summary (JSON)",
                json.dumps(measurements, indent=2),
                file_name=f"{m['ms_number']}_measurement_history.json", mime="application/json")
        else:
            st.info("No measurement summaries saved for this machine yet.")
        reports = reg.get_reports_for_machine(engine, m["id"])
        if reports:
            for report in reports:
                with st.expander(f"Report #{report['id']} · Measurement #{report['measurement_id']} · {report['created_at']}"):
                    st.caption(f"Model: {report['model_name']}")
                    st.markdown(report["text"])
                    st.download_button("Download report", report["text"],
                        file_name=f"{m['ms_number']}_report_{report['id']}.md",
                        mime="text/markdown", key=f"download_report_{report['id']}")
        else:
            st.caption("No AI reports saved yet.")

with tab_live:
    render_live_dashboard(engine)

st.divider()
st.caption("MarineSense Alpha 2.1 · Research demonstration. Optional one-minute live simulation summaries and events may be stored in the configured database; continuous background monitoring, calibrated units and validated diagnoses are future work.")
