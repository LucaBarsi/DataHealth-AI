# DataHealth AI — Phase 18: Machine Learning Integration

This release adds an **isolated local ML experiment** for monthly encounter workload based on the existing synthetic SQLite Gold Layer. It does not modify `Clinical_Assistant.py`, the Streamlit Cloud Demo, or the Qwen/RAG code.

## Installation

Copy the package files into `datahealth_ai_starter` preserving the shown structure:

- `src/workload_forecast.py` — add
- `tests/test_workload_forecast.py` — add
- `docs/phase18_workload_forecasting.md` — add
- `requirements_phase18.txt` — add to project root

Do not move files into `.venv`.

## Setup and tests

From the project root in VS Code PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements_phase18.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_workload_forecast.py" -v
```

## First: feasibility audit (no ML training)

```powershell
.\.venv\Scripts\python.exe -m src.workload_forecast audit --database "data/gold/datahealth.db" --as-of 2026-11-22 --window 60 --output "reports/ml/phase18"
```

Inspect `reports/ml/phase18/data_audit.json` before proceeding. This phase uses only fully completed UTC calendar months before November 2026 and a fixed 60-month window. A nonzero monthly count is not evidence of operational representativeness. If audit shows `INSUFFICIENT_FOR_MEANINGFUL_MODELING`, do not force training; examine data coverage with the assistant.

## Then: experimental baseline and ML models

If the audit is adequate for a **limited synthetic experiment**:

```powershell
.\.venv\Scripts\python.exe -m src.workload_forecast run --database "data/gold/datahealth.db" --as-of 2026-11-22 --window 60 --output "reports/ml/phase18"
```

This compares two simple baselines with Ridge and Random Forest under chronological validation and test blocks. It produces JSON, CSV, Markdown, and PNG outputs. The model is selected using **validation MAE**, not test metrics. We do not claim any deployment or real-world predictive ability.

Review documentation in `docs/phase18_workload_forecasting.md` before interpreting metrics.

## Git and public app

No changes to the public Streamlit app or its API Key are required. Do not commit `data/gold/datahealth.db` or generated reports without explicitly reviewing them. Publish this code to GitHub **only after** the local audit, tests, and review.
