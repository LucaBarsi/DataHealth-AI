# Phase 18 — Exploratory Synthetic Workload Forecasting

## Research question

Can simple models predict the **next month’s number of recorded encounters** using lagged encounter counts in the project's synthetic Gold Layer? This is an educational, operational **time-series** problem, not a patient-specific, clinical-outcome, resource-allocation, or real hospital demand forecasting tool.

## Data lineage and grain

- Input: `data/gold/datahealth.db`, table `encounters`.
- Minimal source fields: `encounter_id`, `start_time_utc` (UTC).
- Each distinct encounter ID is counted once in the month of its start timestamp.
- Missing, invalid, or unzoned timestamps and duplicate identifiers are excluded and counted in the audit.
- The entire current UTC month and future months are excluded, even if synthetic records already exist in those periods.
- The default experiment covers the 60 most recent **complete** UTC calendar months at `--as-of` time. Months without encounters remain zero, with an explicit warning that these may represent missing synthetic coverage rather than genuine zero activity.
- No names, birth dates, demographics, diagnoses, medication details, or identifiable patient information are loaded.
- The SQLite source is opened in **read-only** mode.

## Audit before training

`audit` produces `data_audit.json` and `monthly_encounters.csv`. It reports coverage, excluded rows, proportion of zero months, longest zero streak, and data warnings. The model run blocks when fewer than 100 encounters or too few nonzero months are found; other sparse-data warnings remain visible. This is a heuristic suitability gate, not a claim of statistical adequacy.

## Forecast formulation

The task is a **one-month-ahead rolling-origin evaluation**: when predicting month *t*, the model may use actual counts through month *t-1*. It is **not** a multi-step prediction without future observations.

Features are calculated strictly from earlier periods:

- Lagged counts: `t-1`, `t-2`, `t-3`, `t-6`, `t-12`.
- Rolling means ending at `t-1`: three and six months.
- Calendar month sine/cosine and a chronological time index.

No same-month encounters, clinical event content, or future aggregates are predictors.

## Validation protocol

1. Drop the first 12 months to allow lag creation.
2. Chronologically split the remaining labeled months into approximately 60% training, 20% validation, and 20% test.
3. Fit each ML candidate only on the training block; score each on validation.
4. **Choose the model using validation MAE only** (RMSE and predefined candidate order break ties).
5. Refit that candidate on training plus validation, evaluate once on the later test block.
6. Also report test metrics for the other pre-registered models as diagnostics, **not** to reselect a winner after inspecting the test.

Candidates:

- Last-month naive baseline (`t-1`).
- Last-year seasonal naive baseline (`t-12`).
- Ridge regression with feature scaling.
- Random Forest regression with a fixed seed and fixed hyperparameters.

Primary metric: **MAE** (encounters/month). Secondary: **RMSE** and **WAPE**, which is `null` if total actual volume is zero. Predictions are clipped at zero. No patient-level predictions are made.

## Execution

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements_phase18.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_workload_forecast.py" -v
.\.venv\Scripts\python.exe -m src.workload_forecast audit --database "data/gold/datahealth.db" --as-of 2026-11-22 --window 60 --output "reports/ml/phase18"
.\.venv\Scripts\python.exe -m src.workload_forecast run --database "data/gold/datahealth.db" --as-of 2026-11-22 --window 60 --output "reports/ml/phase18"
```

Use another explicit `--as-of` date as appropriate for later reruns. Do not choose the as-of date after looking at test results to improve the scores.

## Outputs

| File | Description |
|---|---|
| `data_audit.json` | Structural and temporal coverage validation |
| `monthly_encounters.csv` | Full calendar-month series, including zero months |
| `evaluation_summary.json` | Selected model, split boundaries, validation/test metrics, limitations |
| `test_predictions.csv` | Observed versus held-out one-step-ahead predictions |
| `evaluation_report.md` | Human-readable technical report |
| `monthly_encounters.png` | Historical encounter counts |
| `test_predictions.png` | Observed and predicted test series |

All outputs remain under `reports/ml/` and should not be committed to a public repository without review. The synthetic Gold SQLite database remains local and excluded from Git.

## Threats to validity

- Synthea patient histories and encounter rates are not representative of hospital workload. Synthetic sampling, nonstationarity, and generated periods may cause misleading temporal patterns.
- Patient histories span long and possibly sparse time ranges; counting occurrences is not a surrogate for actual demand.
- Months with zero records cannot be distinguished from true zero activity without additional completeness metadata.
- A 60-month sample provides very little information for multiple time-series regressors.
- Temporal drift, seasonal effects, and the train/test split can strongly affect performance.
- No external, real-world, prospective, or clinical validation has been performed.
- Prediction intervals, monitoring, alternative windows/frequencies, and cloud deployment are **out of scope** for this initial phase.

## Decision gate

If the source audit is sparse, unstable, or yields very few recent encounters, **do not promote the model**. Preserve the audit as the result and consider a different synthetic experiment with more suitable time-series data. The phase is successful if it demonstrates careful feasibility assessment, leakage prevention, and transparent reporting — even if no model is trained.
