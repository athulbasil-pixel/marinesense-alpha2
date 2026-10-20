"""MarineSense presentation components — phases A and B.

Visuals only. No database writes, signal calculations or diagnostic claims.
"""
from __future__ import annotations

import base64
from html import escape
from pathlib import Path

import streamlit as st

_BRAND = Path(__file__).with_name("marinesense_brand_header.png")


def install_theme():
    """Apply restrained industrial yellow/charcoal styles throughout Streamlit."""
    st.markdown("""<style>
    :root { --ms-navy:#13212e; --ms-navy2:#1b2f3d; --ms-yellow:#ffcb27;
            --ms-ink:#17222f; --ms-muted:#64748b; --ms-border:#e1e7ed; }
    /* Keep the masthead below the floating Streamlit/Grok toolbar on desktop and mobile. */
    .block-container { max-width:1580px; padding-top:5.0rem !important; padding-bottom:1.5rem; }
    #MainMenu {visibility:hidden;}
    .ms-brandbar { display:flex; align-items:center; justify-content:space-between;
        gap:1.4rem; padding: .8rem 1.1rem; background:linear-gradient(110deg,#111d29,#22384b 85%,#13212e);
        border-radius:12px 12px 0 0; border-bottom:3px solid var(--ms-yellow); }
    .ms-brandbar img {display:block;width:min(100%,390px);height:auto;max-height:62px;object-fit:contain;object-position:left center;}
    .ms-brandtitle {font-size:.60rem;font-weight:800;letter-spacing:.2em;color:#c0cfdd;margin-top:5px;}
    .ms-version {color:#ffd447;font-size:.68rem;letter-spacing:.08em;font-weight:800;text-align:right;white-space:nowrap;}
    .ms-version small {display:block;color:#b9c7d4;font-size:.65rem;letter-spacing:0;margin-top:5px;font-weight:500;}
    .ms-warning {color:#26200c;background:#ffdb63;border-left:5px solid #ca8a04;
        padding:.55rem 1rem;font-weight:750;font-size:.82rem;border-radius:0 0 8px 8px;margin-bottom:.6rem;}
    .ms-warning span {font-weight:500;}
    div[data-testid="stTabs"] [data-baseweb="tab-list"] {
        background:#172635; border-radius:9px; padding:.22rem .25rem; gap:.24rem;
        overflow-x:auto; scrollbar-width:thin; }
    div[data-testid="stTabs"] [data-baseweb="tab-list"] button[role="tab"] {
        background:transparent; color:#d7e2e9; border-radius:6px; padding:.58rem .78rem;
        font-size:.85rem; font-weight:700; white-space:nowrap; min-height:43px;
        border:1px solid transparent; }
    div[data-testid="stTabs"] [data-baseweb="tab-list"] button[role="tab"][aria-selected="true"] {
        background:#ffcb27; color:#12212b; border-color:#efb918; }
    div[data-testid="stTabs"] [data-baseweb="tab-list"] button[role="tab"]:hover:not([aria-selected="true"]) {
        background:#2b4053; color:#fff; }
    div[data-testid="stTabs"] [data-baseweb="tab-highlight"],
    div[data-testid="stTabs"] [data-baseweb="tab-border"] { display:none; }
    /* Asset identity: registered values only. */
    .ms-asset {display:grid;grid-template-columns:120px minmax(190px,2fr) minmax(220px,1.7fr);
        align-items:center;gap:1.1rem;padding:.7rem 1rem;border:1px solid var(--ms-border);
        background:linear-gradient(135deg,#fff,#f7fafc);border-radius:11px;margin:.5rem 0 .8rem;
        box-shadow:0 3px 12px rgba(23,34,47,.05);}
    .ms-asset-illustration {height:95px;border-radius:7px;display:flex;align-items:center;justify-content:center;
        background:radial-gradient(circle at 30% 25%,#456072,#192c3a);color:#f5cd40;position:relative;}
    .ms-asset-illustration svg {height:70px;width:95px;}
    .ms-asset-illustration small {position:absolute;bottom:4px;color:#cbd5e1;font-size:8px;letter-spacing:.1em;}
    .ms-asset-eyebrow {color:#64748b;font-size:.65rem;font-weight:800;letter-spacing:.13em;}
    .ms-asset-name {font-size:1.25rem;color:#152335;font-weight:800;line-height:1.22;margin:.22rem 0;}
    .ms-asset-detail {font-size:.77rem;color:#52657a;line-height:1.5;overflow-wrap:anywhere;}
    .ms-asset-facts {display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:.6rem .85rem;
        border-left:1px solid #dde5ec;padding-left:1rem;}
    .ms-asset-fact .label {font-size:.62rem;color:#64748b;letter-spacing:.05em;text-transform:uppercase;}
    .ms-asset-fact .value {font-size:.83rem;font-weight:750;color:#152335;overflow-wrap:anywhere;}
    .ms-operational-note {font-size:.76rem;color:#536579;margin:.28rem 0 .6rem;}
    .ms-sensors-heading {font-weight:800;color:#172637;font-size:1.05rem;margin:.8rem 0 .4rem;}
    .ms-readout {border:1px solid #dae3ec;border-top:4px solid var(--ms-accent,#ffcb27);
        border-radius:10px;background:#fff;padding:.75rem .85rem;min-height:138px;
        box-shadow:0 2px 10px rgba(30,45,66,.045);}
    .ms-readout-head {display:flex;justify-content:space-between;align-items:center;gap:.25rem;}
    .ms-readout-code {font-size:.78rem;font-weight:800;color:#1f3247;letter-spacing:.03em;}
    .ms-readout-dot {width:9px;height:9px;background:var(--ms-accent);border-radius:99px;flex:none;}
    .ms-readout-name {font-size:.72rem;color:#64748b;line-height:1.35;min-height:30px;margin:.3rem 0 .2rem;}
    .ms-readout-num {font-size:1.8rem;color:#111f2d;font-weight:800;line-height:1.12;
        font-variant-numeric:tabular-nums;letter-spacing:-.04em;}
    .ms-readout-units {font-size:.7rem;color:#65778a;margin-top:.25rem;}
    .ms-status {display:flex;flex-wrap:wrap;gap:.4rem;margin:.25rem 0 .6rem;}
    .ms-status span {border-radius:6px;padding:.33rem .58rem;font-size:.71rem;font-weight:800;
        background:#e9eef3;color:#273a4b;border:1px solid #d6e0e8;}
    .ms-status span.ms-highlight {background:#fff5d8;border-color:#f1d473;color:#73500a;}
    .ms-note {font-size:.78rem;color:#64748b;margin:.38rem 0;}
    @media (max-width:950px) { .ms-asset{grid-template-columns:100px 1fr;}
        .ms-asset-facts {grid-column:1/-1;border-left:0;border-top:1px solid #dde5ec;padding: .55rem 0 0;}
        .ms-asset-name{font-size:1.07rem;} .ms-brandbar img{max-width:290px;} }
    @media (max-width:560px) { .block-container{padding-top:5.5rem !important;} .ms-brandbar{padding:.65rem;gap:.5rem;} .ms-brandbar img{max-width:210px;}
        .ms-brandtitle{font-size:.46rem;} .ms-version{font-size:.57rem;}
        .ms-asset{grid-template-columns:1fr;gap:.5rem;} .ms-asset-illustration{display:none;}
        .ms-asset-facts{grid-column:auto;} .ms-readout{min-height:128px;} }
    </style>""", unsafe_allow_html=True)


def render_masthead():
    if _BRAND.is_file():
        logo_src = "data:image/png;base64," + base64.b64encode(_BRAND.read_bytes()).decode("ascii")
        wordmark = f'<img src="{logo_src}" alt="MarineSense industrial monitoring" />'
    else:
        wordmark = '<strong style="font-size:1.5rem;color:white">Marine<span style="color:#ffcb27">Sense</span></strong>'
    st.markdown(f'''<div class="ms-brandbar"><div>{wordmark}<div class="ms-brandtitle">MACHINERY INTELLIGENCE PLATFORM</div></div>
       <div class="ms-version">ALPHA 2.1 <small>ENGINEERING DEMONSTRATION</small></div></div>
       <div class="ms-warning">⚠ &nbsp; PROTOTYPE / SIMULATED-DATA ENVIRONMENT<br>
       <span>No OEM sensor feeds, certified alarms, validated fault diagnoses or operational safety decisions.</span></div>''',
       unsafe_allow_html=True)


# Asset graphic is deliberately a technical silhouette, not a photograph of an unverified OEM model.
_PUMP_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 130 80" aria-hidden="true">
    <g fill="none" stroke="#d4e3ec" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round">
      <rect x="5" y="23" width="51" height="39" rx="5"/><path d="M5 35H56 M5 49H56 M16 23V15H48V23"/>
      <path d="M56 43H75 M75 33H87 M75 53H87"/><circle cx="103" cy="43" r="21"/>
      <circle cx="103" cy="43" r="10"/><path d="M103 22V12H118V29 M87 65H118"/>
      <path d="M11 70H124" stroke="#ffcb27"/>
    </g></svg>'''


def render_asset_header(machine: dict, number_of_sensors: int, rpm: float | None):
    """Registered machinery metadata: never invent a vessel or measured operating state."""
    machine_num = escape(str(machine.get('ms_number') or 'Unnumbered'))
    name = escape(str(machine.get('name') or 'Unnamed machinery'))
    tag = escape(str(machine.get('tag') or 'Unspecified'))
    machinery_type = escape(str(machine.get('equipment_type') or 'Unspecified'))
    maker = escape(str(machine.get('manufacturer') or 'Not entered'))
    rated = machine.get('rated_rpm')
    rating = f"{float(rated):g} RPM" if rated is not None and rated > 0 else 'Not entered'
    rpm_text = f"{float(rpm):g} RPM" if rpm is not None else 'Not started'
    st.markdown(f'''<section class="ms-asset">
      <div class="ms-asset-illustration">{_PUMP_SVG}<small>REGISTERED ASSET</small></div>
      <div><div class="ms-asset-eyebrow">SELECTED MACHINERY · SIMULATION</div>
      <div class="ms-asset-name">{machine_num} · {name}</div>
      <div class="ms-asset-detail">Equipment tag: {tag} &nbsp;·&nbsp; {machinery_type}</div>
      <div class="ms-asset-detail">Manufacturer: {maker}</div></div>
      <div class="ms-asset-facts">
        <div class="ms-asset-fact"><div class="label">Measurement positions</div><div class="value">{number_of_sensors} displayed</div></div>
        <div class="ms-asset-fact"><div class="label">Rated speed</div><div class="value">{rating}</div></div>
        <div class="ms-asset-fact"><div class="label">Simulation setting</div><div class="value">{rpm_text}</div></div>
        <div class="ms-asset-fact"><div class="label">Signal source</div><div class="value">Synthetic · arbitrary units</div></div>
      </div></section>''', unsafe_allow_html=True)


def render_sensor_cards(points: list[dict], latest: dict, running: bool):
    """Cards show observed simulator RMS only; never manufacture missing measurements."""
    colors = ('#E6AE00', '#009A73', '#2563EB', '#E83B63')
    st.markdown('<div class="ms-sensors-heading">Machinery Overview · Sensor Positions</div>', unsafe_allow_html=True)
    cols = st.columns(len(points))
    for i, (col, point) in enumerate(zip(cols, points)):
        with col:
            value = latest.get(point['id'])
            reading = f"{float(value):.4f}" if value is not None else '—'
            name = escape(str(point.get('name') or 'Unnamed position'))
            code = escape(str(point.get('sensor_code') or f"POINT-{point['id']}"))
            st.markdown(f'''<div class="ms-readout" style="--ms-accent:{colors[i % 4]}">
              <div class="ms-readout-head"><span class="ms-readout-code">{code}</span><span class="ms-readout-dot"></span></div>
              <div class="ms-readout-name">{name}</div>
              <div class="ms-readout-num">{reading}</div>
              <div class="ms-readout-units">RMS · arbitrary units {'' if running else '· last session' if value is not None else '· no reading'}</div>
              </div>''', unsafe_allow_html=True)
