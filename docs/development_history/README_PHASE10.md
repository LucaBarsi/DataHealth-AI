# DataHealth AI — Phase 10: Interactive Analytics Dashboard

Adds an independent analytics page to the existing **branded Phase 9 Streamlit application**. It does not replace `app.py`, alter the Gold database, or touch the Qwen/ChromaDB components.

> Synthetic Synthea data only. Educational exploration, not clinical use or live monitoring.

## Installation — Windows + VS Code

1. Stop all running Streamlit servers with `Ctrl+C` in the terminals where they are running.
2. Extract this ZIP.
3. Inside your existing `datahealth_ai_starter/` project:
   - Create `pages/` in the **project root** (the same level as `app.py`) if needed.
   - Copy `pages/1_Analytics_Dashboard.py` to `pages/`.
   - Copy `src/analytics_backend.py` to your existing `src/`.
   - Copy `assets/analytics_dashboard.css` to your existing `assets/`.
   - Copy `tests/test_analytics_backend.py` to your existing `tests/`.
   - Copy `docs/analytics_dashboard.md` to your existing `docs/`.
   - Copy `requirements_phase10.txt` and this README to the project root.
4. **Keep the existing** `app.py`, `assets/datahealth.css`, `src/ui_backend.py`, `data/gold/datahealth.db` and vector index unchanged.

## Install optional visualization dependencies

From the project root in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements_phase10.txt
```

## Run 10 backend tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_analytics_backend.py" -v
```

Expected: `Ran 10 tests` and `OK`.

## Launch both pages

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1
```

Open the `Local URL` printed by Streamlit. The sidebar's **page navigation** should show your original assistant and **Analytics Dashboard**. Select the new page.

If port 8501 is already in use, Streamlit may choose port 8502. Use the URL shown in the terminal.

## First walkthrough

1. Choose **All synthetic patients** and **All recorded dates**.
2. Check the count cards. Based on the previously reported Phase 3 Gold Layer, we expect about 112 patients, 5,087 encounters, 51,366 normalized observation value rows, and 1,529 rows flagged for review (assuming the same database version).
3. In **Dataset overview**, inspect activity and categories and download the sample CSV.
4. In **Patient trends**, select Abraham100 Hackett68; choose a measurement code/unit pair and explore the dates.
5. In **Data quality**, inspect the `MIXED_UNIT_CODING` and `MISSING_UNIT_CODE` flags.
6. In **Operations**, inspect encounter counts and current/superseded documents.

## Troubleshooting

- **Page not listed**: ensure `pages/` is immediately beside `app.py`; restart Streamlit.
- **`ModuleNotFoundError: plotly`**: install `requirements_phase10.txt` using `.venv`.
- **Missing database**: check that `data/gold/datahealth.db` exists and that Streamlit was launched from the original project root.
- **Empty chart**: adjust filters. The dates/measurements may not be present for that patient; this is not an error.
- **Confusing multiple servers**: stop duplicate Streamlit sessions (`Ctrl+C`), then launch one server and use its reported port.

## Testing performed before delivery

- 10 automated backend tests passed on a synthetic SQLite fixture matching the Gold schema.
- The dashboard page was statically checked for Python syntax.
- The interface itself must be smoke-tested on your Windows setup with your complete local Gold database.

See `docs/analytics_dashboard.md` for data semantics, security limitations and the relationship to the original enterprise architecture.
