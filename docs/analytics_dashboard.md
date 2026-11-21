# DataHealth AI — Phase 10: Analytics Dashboard

## Objective

Add a separate, interactive **Analytics Dashboard** page to the existing Streamlit clinical assistant. It explores **synthetic Synthea records** using read-only queries against the Phase 4 SQLite Gold Layer. The page retains the Phase 9 brand and does not alter existing SQL/RAG/LLM code.

## Why this matters

The initial DataHealth business case emphasized integration, exploratory data analysis, metadata transformations and analytics. This dashboard exposes auditable, reproducible aggregate and patient-level analyses. It is not a predictive ML model or live sensor monitoring system.

## Architecture

```text
Synthea JSON (original Bronze source)
  -> FHIR transformation + Silver structural quality checks
  -> SQLite Gold Layer (read-only views and tables)
  -> analytics_backend.py (fixed, parameterized queries)
  -> pages/1_Analytics_Dashboard.py (Streamlit + Plotly)
```

The application remains local. Azure/AWS, Kafka, Spark and Power BI are components of the larger proposed enterprise architecture and are **not implemented by this dashboard**. A future Power BI report may use a properly curated export or supported connector.

## Features

1. **Dataset overview**: scoped patient count, encounter count, normalized observation value rows, flagged row count; activity by year/month; category distribution; most frequent measurement codes; latest source rows.
2. **Patient trends**: select one patient, measurement **code and unit together**, time filter and optional flagged-row inclusion; export the visible rows.
3. **Data quality**: structural status distribution, reasons for review and a sample of the newest flagged records.
4. **Operations**: encounter volume over time and current/superseded document status.

### Filter behavior

- `Population scope`: all synthetic patients or one synthetic patient.
- `Observation category`: filters **observation** charts and rows, not encounters or document counts.
- `Date range`: filters time-stamped observations, encounters and documents. The patient-count KPI counts the selected cohort regardless of date.
- `Last 365 days of dataset`: anchored to the **latest recorded observation**, not to the system clock.
- `Observation event` differs from `normalized observation value row` (e.g., systolic/diastolic components), so their counts are not interchangeable.

### Data safety and semantics

- All database connections use `mode=ro` plus `PRAGMA query_only=ON`.
- SQL identifiers/queries are predefined in code; filter values are bound parameters.
- The dashboard only uses synthetic records, selected by patient ID when applicable.
- Patient trends never merge different measurement codes or different unit codes.
- Structural flags `REVIEW_REQUIRED` remain visible, are excluded from numeric trend charts by default, and can be included explicitly with differentiated markers.
- No unit conversions, clinical reference ranges, diagnoses or predictions are generated.
- Superseded documents remain countable as historical records. They are not interpreted as current clinical content.
- CSV exports contain only the displayed, filtered rows; string cells starting with spreadsheet formula prefixes are escaped.
- This app is **not authenticated**. Keep the local server restricted to `127.0.0.1` and do not process real patient information.

## Key source tables

- `patients` — synthetic patient identifiers and demographics
- `encounters` — synthetic encounter events
- `observation_events` — one row per FHIR observation event
- `observation_values` — one row per simple or component value
- `clinical_documents` — status and metadata only; the raw texts are not needed for analytics

## Known limitations

- The `latest_observations` table shows at most 100 rows; the quality table shows at most 100 **flagged** rows. These are samples, not full-dataset exports.
- The trends show up to 750 newest rows for one measurement-code/unit pair.
- Dates are taken from stored UTC timestamps. Records without valid timestamps are omitted from date-based charts and filters.
- The data are synthetic; aggregate distributions are demonstrations, not real-world epidemiology.
- The page reports historical observations, not real-time sensor signals.
- Structural quality flags do not establish clinical accuracy or terminology correctness.

## Future extensions

- Stream ingestion simulation with Kafka and Spark; materialized Gold aggregates.
- Power BI reporting that reuses the same validated semantics.
- A dedicated metadata/data-lineage panel and monitoring of refresh timestamps.
- Data quality rule coverage and reproducible benchmark notebooks.
- Guarded and tested visualization handoff from the conversational assistant.
