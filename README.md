# MarineSense Alpha 2.0 — Machinery-aware condition monitoring (prototype)

**This is a research/demo application, not a validated marine diagnostic or safety system.**

## What's included

- Fleet → Vessel → Machinery Assembly registry; public machinery IDs like `MS-000001`, generated from primary keys (not browser counters).
- Machine components and registered sensor measurement positions, including optional OEM model/ID.
- Same synthetic vibration demo and CSV analysis that worked in Alpha 0.1 (RMS, FFT, 30/120 Hz).
- Actual operating RPM field (separate from nameplate RPM), and order calculations when supplied.
- Logged measurement summaries, checksums, configuration snapshots, and downloadable reports, linked to machine ID.
- Groq AI interpretation with machinery context; optional two-call comparison with context withheld.
- Private shared demo-code gate. **Not production-grade authentication or tenant isolation.**

## Important storage warning

Without a `DATABASE_URL` secret, the application uses a local SQLite file under `.demo_data/`.
That works for demonstrations and local tests, but **Community Cloud local storage is not durable**. It may be lost when the app restarts or redeploys. Do not claim machine IDs are permanent until connecting external Postgres.

Set `DATABASE_URL` to a server-side PostgreSQL SQLAlchemy connection URL for persistent storage, e.g. `postgresql+psycopg://...` supplied by your database provider. Do **not** commit this secret to GitHub. The application automatically creates its six database tables. Use a dedicated database/schema, limit DB credentials and restrict access before storing any real customer data.

For Supabase, pay attention to schema/API exposure, privileges and row-level security. A database connection from a public demo running with an administrator password is **not a production solution**. For real fleets, add per-user auth, organisation isolation and audit logging first.

## Deploy in a new repository, preserving Alpha 0.1

1. Create a separate public GitHub repository **`marinesense-alpha2`** (prototype code only, no secrets/data).
2. Upload the **contents** of this folder to repository root. In particular `app.py`, `analysis.py`, `engineering.py`, `registry.py`, `requirements.txt` must be at root.
3. On Streamlit Community Cloud select repo `marinesense-alpha2`, branch `main`, entrypoint `app.py`.
4. In **Advanced settings → Secrets**, add:

```toml
DEMO_PASSCODE = "CHOOSE_A_STRONG_PRIVATE_DEMO_CODE"
GROQ_API_KEY = "YOUR_EXISTING_GROQ_API_KEY"
# Optional, needed for durable registry on cloud:
# DATABASE_URL = "postgresql+psycopg://USER:PASSWORD@HOST:PORT/DATABASE?sslmode=require"
```

5. Deploy, sign in with your demo code, create the example registry, run the synthetic dataset, view history and generate an AI report.
6. If no external database is configured, use the app for *disposable testing only*. Do not enter real vessel records or rely on machine IDs surviving redeployment.

Do not put credentials in screenshots, code, `.env` or uploaded files. The `.gitignore` excludes local secrets and DB files.

## Local developer run

```bash
python -m pip install -r requirements.txt
streamlit run app.py
```

Configure `.streamlit/secrets.toml` locally, or cloud Secrets. Run `pytest -q` for numerical and registry tests.

## CSV format

Two separate CSV files, each with one numeric `vibration` column, equally sampled. Choose correct sample rate and units. The system stores **numerical summaries and SHA-256 hashes of sample arrays**, not raw uploaded files; keep original files safely outside this demo.

## Engineering safeguards

- Shaft orders are **only** calculated from the actual RPM entered with the measurement, not from rated RPM.
- With arbitrary units or unknown operating conditions, severity and fault classification are not valid.
- The AI receives structured numerical summary plus the explicitly entered machinery profile. Text from the model is exploratory, not an independently validated diagnostic result.
- No baseline matching/validated thresholds or bearing fault-frequency calculation is implemented yet.
- The side-by-side AI comparison is a **qualitative demonstration**, NOT a measurement of improved prediction accuracy. For that, independently labelled fault datasets and evaluation metrics are essential.
- Continuous sensor telemetry, sensor-node API, thermal imagery, durable raw waveform storage, true multi-user identity, and production security are not implemented.
