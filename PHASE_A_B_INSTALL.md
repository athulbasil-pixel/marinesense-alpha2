# MarineSense Alpha 2.1 — Industrial Interface (Phases A + B)

Development patch for the **existing** Streamlit Alpha 2.1 app, based on the logo and approved dashboard mockup. This implements only the header/navigation and machinery overview. Charts/FFT layout and condition assessment remain later work.

## Branch safety
1. Go to GitHub repository `athulbasil-pixel/marinesense-alpha2`.
2. With `alpha-2.1-live` selected, create a branch named `alpha-2.1-industrial-ui` **from this branch** (not from `main`).
3. Open the new branch, select **Add file → Upload files**.
4. Extract the patch ZIP; upload **only** `app.py`, `live_dashboard.py`, `ui_theme.py` and `marinesense_brand_header.png` to the repository **root**.
5. Commit with message: `Phase A+B: industrial branding and machinery overview` to the `alpha-2.1-industrial-ui` branch.
6. Deploy a separate test Streamlit app with repository `athulbasil-pixel/marinesense-alpha2`, branch `alpha-2.1-industrial-ui`, main file `app.py`; or temporarily repoint your **test** app only. Use your existing Streamlit Secrets; do not put credentials in GitHub.

## Expected
- Logo is white/yellow on a dark masthead, with an always-visible synthetic-data warning.
- All **five existing tabs** continue to function; industrial themed tab bar.
- Live Simulator displays registered machinery ID, name, equipment tag, type, manufacturer, rated RPM, simulated RPM and number of sensor points shown.
- Four compact readout cards show the **actual simulated RMS state**. Empty state shows a dash; stopped state indicates last browser-session readings.
- The old start/stop, RPM, sensor-adjustment and Supabase-recording controls remain in a collapsed expander, ready to open.
- Existing live trend, waveform/FFT, saved session browsing and CSV export still work.

## What this does not add
No real OEM sensor integration, fault diagnosis, severity categories, new database tables, fabricated baseline percentages, sample history records or automatic database writes beyond the already existing recording function.

## Validation
Existing 13 engineering/backend tests plus 3 new UI data/escaping checks are run in this package. A deployment/browser visual test is still required; CSS selectors may vary between Streamlit releases.

## Optional global control-theme setting
After verifying the app, you can edit `.streamlit/config.toml` in GitHub (preserving its location) to set `primaryColor = "#E4A900"` under `[theme]`. This is **not required** for the patch; the brand, navigation and cards are styled by `ui_theme.py` regardless.
