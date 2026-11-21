# Phase 4 — Gold Layer and SQL Database Integration

## 1. Business objective

Create a patient-centered, queryable relational layer over the DataHealth AI Silver dataset. The local SQLite database supports reproducible demonstrations of retrieving synthetic patient information before introducing an LLM or RAG system. It does not validate clinical measurements or act as a clinical decision-support system.

## 2. Enterprise architecture alignment

- **Bronze:** Original Synthea FHIR JSON bundles remain unchanged in `data/raw/`.
- **Silver:** Parsed and structurally reviewed resources reside in `data/silver/fhir/`.
- **Gold:** This phase materializes SQL tables and views in `data/gold/datahealth.db`.
- **Cloud translation:** Production could use managed relational stores and cloud lakehouse tables in Azure or AWS, after re-evaluating scaling, security, and governance.
- **Future integration:** Apache Kafka, Apache Spark, APIs/HL7 FHIR, Power BI, Qwen 3.5 4B via Ollama, and RAG/ChromaDB remain within the proposed architecture; they are **not deployed by this script**.

## 3. Data model

| SQL table / view | Purpose |
|---|---|
| `patients` | Synthetic patient identifiers and basic attributes |
| `encounters` | Encounter history linked to patients |
| `observation_events` | Unique parent FHIR Observation events |
| `observation_values` | One row per normalised observation component or stand-alone measurement |
| `conditions` | Recorded conditions |
| `diagnostic_reports` | Report metadata and references |
| `diagnostic_report_results` | Many-to-many report-to-observation links |
| `medication_requests` | Prescription/order metadata (not confirmed administration) |
| `clinical_documents` | **Metadata only**; no clinical document body |
| `v_observations` | Joined, patient-searchable measurement rows with quality flags |
| `v_patient_overview` | Patient-level event counts |
| `v_rag_preliminary_document_metadata` | Non-authorizing metadata shortlist for later RAG review |

## 4. Transformation rules and rationale

1. Keep original Bronze and Silver files unchanged.
2. Apply SQLite primary keys and foreign keys to detect duplicate or orphan identifiers during data loading.
3. Separate the parent `observation_events` from `observation_values`. This retains the fact that a blood pressure panel can contain two linked values. A raw source count of Observation events need not match the count of component rows.
4. Keep standard FHIR/LOINC identifiers and units as provided. **Do not convert values or recode clinical terminology** without an independently verified mapping.
5. Parse valid timezone-aware timestamps into UTC for chronological queries. Never invent a timezone for a naive or invalid timestamp; preserve the original observation timestamp string for review.
6. Carry over the `quality_status` and `quality_flags` produced by the Silver audit. `PASS_STRUCTURAL_CHECKS` does **not** indicate clinical validity.
7. Keep source value strings and traceable `source_file` fields when available. `value_numeric` is a typed SQL `REAL` field, not a replacement for the source value.
8. Store metadata only for clinical documents; text remains in Silver. Expose a *preliminary* candidate view restricted to `status = 'current'` and `PRELIMINARY_ONLY_NOT_AUTHORIZED`. Authorization, consent, and patient-scoping must be enforced separately before any RAG indexing.
9. Use parameterized SQL through pre-approved read-only queries. Do not let a generative model construct unrestricted SQL against the database.

## 5. Quality gates

- All eight expected Silver input tables must exist.
- Every normalized observation row must be loaded, with no component-row loss.
- All patient/encounter/report/result foreign keys must resolve or the build fails.
- Duplicated primary-key values fail the build.
- The SQLite build must complete in a separate temporary file before replacing the Gold database.
- Test queries must return expected synthetic patient results with quality flags.

## 6. Limitations and next phases

This implementation is a local, single-user SQLite MVP. It contains synthetic data but no user authentication, production-grade access controls, row-level policies, streaming ingestion, Spark orchestration, or clinically reviewed terminology normalization. The current preliminary document metadata view is **not permission to index the underlying text**. Further work must evaluate terminology, unit normalization, clinical safety, patient authorization, and query privacy before real-world use.
