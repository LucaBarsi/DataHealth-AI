# DataHealth AI — Phase 21: Contextual Charts

**Scope:** Evidence-linked, patient-scoped measurement exploration in the local Streamlit Clinical Assistant.

**Status (November 23, 2026):** Previous unit tests and manual UI checks passed. The presentation refinement in this package has passed syntax and isolated branch checks, but still requires a final Streamlit check in the project environment.

## Architecture and safeguards

- Chart targets are derived from retrieved **SQL evidence**, not from generated Qwen response text or RAG passages.
- Measurement history is read from the local **Gold Layer SQLite** database by the existing `src.contextual_charts` and `src.analytics_backend` modules.
- Patient ID, measurement code, and unit remain scoped independently; different patients or incompatible units must not be combined.
- Records with `REVIEW_REQUIRED` are excluded by default and may be shown only when the user explicitly selects **Include records flagged for review**.
- Citation IDs, quality flags, and structural checks do **not** establish clinical accuracy. Synthetic data only; not for clinical use.

## Verified results before the UI refinement

| Validation | Observed result | Evidence source |
| --- | --- | --- |
| Contextual Charts unit tests | 11/11 passed | User's `python -m unittest discover -s tests -p "test_contextual_charts.py" -v` output |
| Apache Spark ETL unit tests | 3/3 passed on Ubuntu/WSL | User's `test_spark_etl.py` output (PySpark 4.3.0) |
| Clinical Assistant load | Streamlit interface loaded; 112 synthetic patients shown | User screenshots |
| Vital-sign chart | Three respiratory-rate measurements rendered | User screenshots |
| Laboratory measurement | Single MCH point displayed without claiming a longitudinal trend | User screenshots |
| Quality filter | Flagged laboratory measurement hidden by default; visible when the checkbox is enabled | User screenshots |
| Full regression suite | Not confirmed | Windows run encountered a native Hadoop/Spark error before final summary |

## Presentation refinements delivered

Updated file: `Clinical_Assistant.py`.

1. **No eligible records:** the existing explanatory message remains, without a chart.
2. **Exactly one eligible record:** a summary panel replaces the single-point Plotly chart. It shows the measurement, original unit, recorded UTC time (when timezone-aware), quality status, any quality flags, and the exact observation ID. It explicitly says that a single point is not a longitudinal trend.
3. **Two or more eligible records:** the original Plotly time-series visualization is retained, including separate markers for records requiring review. Axis margins, spacing, and date labels have been adjusted for legibility.
4. **Auditability remains:** the exact-observation table, Gold Layer record count, truncation warning, and Analytics Dashboard link are retained.
5. **Data handling is unchanged:** no SQL queries, model routing, patient selection, or quality-filter logic were modified.

## Verification of this code package

- Python syntax compilation: **passed**.
- Isolated checks (without starting Streamlit): **passed** for empty measurements, one passing measurement, hidden flagged measurement, an explicitly included flagged measurement, multiple passing measurements, and mixed-quality multiple measurements.
- UTC timestamp formatting checks: **passed** for timezone-aware and timezone-naive values.
- Full dependency-backed regression and browser verification **remain to be performed** after replacement in the project.

## Install and validate

1. Back up the original project-root `Clinical_Assistant.py`.
2. Replace it with the updated file from this package. Do not modify the files in `src/` or the Gold Layer database.
3. In the **Windows PowerShell** terminal, activate the project's existing `.venv` and run:

   ```powershell
   python -m unittest discover -s tests -p "test_contextual_charts.py" -v
   python -m streamlit run Clinical_Assistant.py
   ```

4. Select a synthetic patient and run **Laboratory results**. A measurement with one eligible observation should show the summary panel, not a one-point chart.
5. Select a `REVIEW_REQUIRED` measurement. Check that it is absent with the flag checkbox off, then visible with the checkbox on. Check that quality details and the observation ID are displayed.
6. Run **Latest vital signs**. A measurement with two or more records should still show the timeline with readable axes and hoverable observation IDs.
7. Review the full regression suite, running Spark-specific tests with the existing Ubuntu/WSL Spark virtual environment to avoid Windows native-Hadoop issues.

## Remaining acceptance criteria

- Updated Streamlit UI confirmed visually in the project's Windows environment.
- Existing Contextual Charts tests rerun against the modified interface.
- Full regression test results recorded with a platform-aware approach (Windows for general Python tests; Ubuntu/WSL for Spark).
- Optional follow-up: verify any synthetic measurements apparently recorded before a patient's listed birth date; do not treat unverified chart labels as proof of a data error.

**Safety notice:** This is an educational prototype using synthetic records. It is not authenticated or validated for clinical decisions. Keep access on localhost and do not load real patient data.
