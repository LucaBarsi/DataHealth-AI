# DataHealth AI — Phase 18.1: ML Forecasting Dashboard

**Goal:** a small, read-only Streamlit page that visualizes Phase 18's *already generated* experimental workload forecasting results. This is a local UI test, **not another ML training phase**.

## What is included

- `pages/2_ML_Forecasting.py` — adds an **ML Forecasting** page to the local Streamlit navigation
- `src/ml_dashboard_data.py` — reads and validates aggregated CSV/JSON reports (read-only)
- `tests/test_ml_dashboard_data.py` — seven tests, no Streamlit server or ML training needed

The dashboard displays: historical monthly counts, observed vs predicted test counts (optional naive baselines), model comparison and evaluation limitations. It does **not** load patient records, query SQLite, contact Qwen or change the public Cloud Demo.

## Copy into the project

Place the three files in the respective `pages/`, `src/`, and `tests/` folders under `datahealth_ai_starter`. Keep your existing `pages/1_Analytics_Dashboard.py` unchanged. The dashboard automatically reads these existing Phase 18 files:

```text
reports/ml/phase18/
  data_audit.json
  evaluation_summary.json
  monthly_encounters.csv
  test_predictions.csv
```

If these files are present, **do not rerun the training**. PNGs are optional because the page generates interactive Plotly charts directly from the CSVs.

## Test

In the VS Code PowerShell terminal, from your project's root directory:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_ml_dashboard_data.py" -v
```

The expected result is `Ran 7 tests` followed by `OK`.

## Run locally

If you already have a Streamlit session running, stop it with `Ctrl+C` in its terminal or use a new port:

```powershell
.\.venv\Scripts\python.exe -m streamlit run Clinical_Assistant.py --server.address 127.0.0.1 --server.port 8506
```

Open `http://127.0.0.1:8506` and select **ML Forecasting** in the sidebar. This page should appear alongside the existing Clinical Assistant and Analytics Dashboard. Alternatively, run the page independently:

```powershell
.\.venv\Scripts\python.exe -m streamlit run pages/2_ML_Forecasting.py --server.address 127.0.0.1 --server.port 8506
```

### Notes

- Uses the existing `pandas` and `plotly` dependencies of the local Analytics Dashboard; no additional packages are required if Phase 10 is working.
- The selected model is determined by **validation MAE** in Phase 18. Test metrics for other models are displayed for diagnostic purposes only.
- The test plot represents **rolling one-step-ahead** evaluation using known earlier observations. It is not a prospective multi-month forecast.
- All records are synthetic and should not be used for real clinical or operational decisions.
- **Do not deploy or publish generated local reports to GitHub** for this test. Only publish the source code later if desired.
- The existing public Streamlit Cloud Demo remains unchanged.
