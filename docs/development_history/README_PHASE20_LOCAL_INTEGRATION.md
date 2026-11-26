# DataHealth AI — Phase 20: Local Pipeline Integration Audit

## Purpose

This module **does not rebuild, merge, or replace** the existing Python/SQLite and Spark pipelines. It performs a **read-only, reproducible consistency audit** across:

1. Bronze synthetic FHIR Bundle file count;
2. Phase 19 Spark Silver Parquet resources;
3. Five Phase 19 Spark Gold aggregate Parquet tables;
4. The Phase 19 run summary (`reports/spark/phase19_summary.json`);
5. The existing normalized SQLite Gold database, when available.

The new integration report includes **aggregate counts only**, never patient names or resource identifiers. The source data must be **synthetic only**. Checks cover internal consistency, **not medical/clinical correctness** and **not full HL7 FHIR validation**.

## Requirements

- Ubuntu / WSL 2, from the project root.
- The existing `datahealth-spark-venv` virtual environment with PySpark 4.3.0.
- Completed Phase 19 ETL (Silver/Gold Parquet directories and Phase 19 summary).
- Optionally, existing SQLite database at `data/gold/datahealth.db`.

## Installation

Copy these files to the **existing** DataHealth AI project, without replacing other modules:

- `src/validate_local_pipeline.py` → `src/`
- `tests/test_validate_local_pipeline.py` → `tests/`
- `README_PHASE20_LOCAL_INTEGRATION.md` → project root.

## Run tests (inside Ubuntu)

```bash
cd /mnt/c/Users/Users/Documents/DataHealth_AI_Etapa_1/datahealth_ai_starter
source ~/datahealth-spark-venv/bin/activate
python -m unittest discover -s tests -p 'test_validate_local_pipeline.py' -v
```

Expected: **5 tests, OK**. These helper tests do not start Spark.

## Run the full local integration audit

```bash
python -m src.validate_local_pipeline
```

Expected summary: `"audit_status": "PASS"` and `"checks_passed": 12`. It writes a new report to:

`reports/integration/phase20_validation.json`

All 12 checks reconcile the raw file count, Silver counts and five Spark Gold aggregate tables. The optional normalized SQLite counts appear in `sqlite_reconciliation` as **informational**, not pass/fail: e.g., raw Observation resources do not necessarily equal normalized observation value rows.

### Notes

- The audit does **not** modify any existing FHIR, Parquet, SQLite, Power BI, or Streamlit data.
- To rerun the audit after changing raw bundles, first rerun Phase 19 ETL; otherwise a stale Phase 19 report should cause an explicit consistency check failure.
- A successful run is not evidence of medical validation or that the project was tested at distributed-cluster scale.
- Do **not** automatically commit generated Parquet files, raw FHIR files, large data, secrets, or local `.db` files to the public GitHub repository. Review `git status` and `.gitignore` before publishing.
- The new code and documentation are in English; discussions may remain in Portuguese.

## If a check fails

Send the final lines showing `audit_status` and the `checks` section (the output contains aggregate counts only). Do not send private files, credentials, or raw data. Investigate any discrepancies before finalizing Phase 20.
