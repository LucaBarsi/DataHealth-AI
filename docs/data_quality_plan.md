# DataHealth AI — Phase 2: Data Cleaning & Validation

## Business purpose

Before clinical data are made searchable through SQL or an LLM with RAG, we must verify that the transformed data are traceable, internally consistent, and suitable for controlled retrieval. Poor data quality can produce incorrect patient associations and misleading answers.

## Architecture alignment

- **Bronze:** immutable Synthea FHIR JSON source files (`data/raw/`).
- **Silver candidates:** transformed CSV tables (`data/processed/fhir/`).
- **Quality gate:** this audit; its findings require review before Silver approval.
- **Gold (later):** task-specific analytical views and patient-centric retrieval datasets.
- **Enterprise roadmap:** Kafka/APIs for ingestion, Spark for scaling transformations, Azure/AWS Lakehouse for deployment, SQL for structured queries, Qwen + Ollama and RAG/ChromaDB for grounded language queries, and Power BI for operational visualization.

## Quality rules implemented

1. Table presence, schema presence, and required-field completeness.
2. Business-key uniqueness (using `observation_id + component_index` for observations).
3. References to known patient, encounter, observation, and report identifiers.
4. Consistent patient ownership for records linked to encounters.
5. Parseable timestamps and chronological encounter start/end.
6. Numeric quantity integrity; missing and mixed unit codes require review.
7. Unsupported/missing observation values require source-level inspection.
8. Non-current clinical documents are flagged as ineligible for automatic RAG indexing.
9. Row-count comparison with the transformation summary, when present.

## Important safeguards

- The audit reports findings; it does **not** delete, impute, normalize, or change any clinical values.
- Empty FHIR optional fields are not automatically treated as errors.
- A missing `unit_code` may be valid for a unitless measurement; it is a warning, not an automatic defect.
- A `DiagnosticReport` can reference an `Observation` that has multiple component rows. Only the observation ID must resolve.
- This is a structural audit, not a full FHIR validator or clinical correctness check.
- Synthetic data only; authorization and patient scoping must still be designed for the future LLM app.

## Run locally (Windows PowerShell, from the repository root)

```powershell
python -m pip install pandas matplotlib
python -m src.validate_fhir --input "data/processed/fhir" --output "reports/data_quality"
```

Generated files:

- `quality_summary.json` — row counts, unique IDs, and high-level findings.
- `quality_issues.csv` — auditable findings with example IDs and severities.
- `quality_report.md` — English Markdown report for the project.
- `record_counts.png` — optional visualization of the transformed tables.

## Next decisions

Read the findings, inspect original FHIR JSON for each error category, and propose documented transformations. Only then create an approved Silver dataset. For SQL and RAG, preserve provenance and do not silently index superseded documents.
