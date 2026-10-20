# MarineSense experimental condition review · installation

**Target GitHub branch:** `alpha-2.1-industrial-ui`  
**Do not upload to:** `main` or `alpha-2.1-live`.

## Installation

Upload these three files from `MarineSense_Condition_Review_Patch.zip` to the repository root on the industrial-UI branch:

- `app.py` — adds **◈ Condition Review** as a sixth tab.
- `condition_assessment.py` — independent, testable comparison calculations.
- `condition_dashboard.py` — read-only Streamlit review interface.

The existing `ui_theme.py`, logo PNG, `live_dashboard.py`, `live_simulator.py`, `live_history.py`, registry and other files are unchanged. No new SQL tables or Streamlit Secrets are needed. Your *separate* industrial-UI Streamlit deployment should rebuild automatically.

Suggested commit: **Add experimental vibration condition review**.

## First test: offline example (no database changes)

1. Open **◈ Condition Review**.
2. Choose **Offline illustrative example**.
3. Keep reference start at minute 0, comparison start at minute 5.
4. Confirm three unchanged sensors and one sensor (SEN-0003) with a sustained synthetic increase and 4× component growth.
5. Download the evidence-only JSON if desired. This does NOT save an AI report.

## Second test: stored history

1. In **Live Simulator**, enable recording before starting a *new* session.
2. Hold RPM constant (e.g. 1800) for the demonstration; do not change any settings during the reference period.
3. Record **at least three complete observed minutes** of initial reference values at each registered sensor position. Allow >=6 of the expected ~12 five-second frames per full minute. Keep your browser connected.
4. Increase SEN-0003 1× amplitude and optionally its 4× amplitude; leave all other sensors unchanged.
5. Record **at least two more complete observed minutes** with that change. Allow 5+ minutes total, preferably 6-7 minutes to ensure all required windows are complete.
6. Stop simulation. In **Condition Review**, choose **Saved Supabase simulation**, select the machine and the new recorded session. Choose reference minutes 0-2 and comparison minutes 3-4 (or whichever are full, uncontaminated windows).
7. Inspect the per-sensor evidence table, RMS plot, single-sensor evidence JSON and optional operator events.

If the first stored history only has two minutes, the software will correctly show **INSUFFICIENT DATA**. It does not invent a reference period. If there are gaps/partial rows, it rejects those rows.

## Interpretation rules

- RMS +20% in **both** comparison minutes: `SUSTAINED CHANGE`.
- RMS +40% in **both** comparison minutes: `LARGE SUSTAINED CHANGE`.
- 4× FFT amplitude rises by >=0.05 **arbitrary demo amplitude units** in both minutes: `SPECTRAL CHANGE` (or combined with RMS change).
- Only one of the two comparison minutes changes: `SINGLE-WINDOW CHANGE`.
- Missing, partial or sparse minutes: `INSUFFICIENT DATA`.
- Speed change >5% relative to reference: `OPERATING CHANGE`, quantitative comparisons withheld.
- These cut-offs are **illustrative demonstration rules**, **not equipment thresholds, ISO 20816 severity criteria, health scores, or validated fault diagnoses**. An operator-selected reference is not necessarily a healthy baseline.

No automatic Groq calls, background monitoring, machine fault classification, new database tables, or extra Supabase storage are introduced by this page. It reads the already stored simulation minute records on demand.
