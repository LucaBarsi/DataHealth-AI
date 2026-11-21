# DataHealth AI — Phase 2 Data Quality Findings

## Scope and evidence

This report documents the **initial audit of transformed synthetic Synthea FHIR records**, based on `quality_summary.json` and `quality_issues.csv`. The audit did not change source files and does not establish clinical validity or complete FHIR conformance.

## Audit results

| Measure | Result |
|---|---:|
| Unique patient IDs | 112 |
| Encounter rows | 5,087 |
| Observation rows (component-normalized) | 51,366 |
| Unique Observation IDs | 34,024 |
| Diagnostic report rows | 9,281 |
| Clinical document rows | 5,087 |
| Recorded warning findings | 6 |
| Informational findings | 1 |
| Critical errors reported | 0 |

**Audit status:** `NO_CRITICAL_ISSUES_FOUND`. This indicates only that the implemented audit checks reported no `ERROR` findings; it does **not** mean the data are clinically correct or ready for unrestricted LLM retrieval.

## Findings and decisions

| Rule | Affected rows | Interpretation | Proposed handling |
|---|---:|---|---|
| `missing_quantity_unit_code` | 3 | Three numeric quantities have no unit code | Inspect the source FHIR resource; do not infer or invent units |
| `mixed_unit_codes`, LOINC `33914-3` | 611 | `mL/min` and `mL/min/{1.73_m2}` differ in body-surface-area indexing | Keep units distinct; assess code/unit compatibility before any normalization |
| `mixed_unit_codes`, LOINC `5803-2` | 274 | `[pH]` and `pH` are represented differently | Review unit-system metadata; normalize only if semantically equivalent |
| `mixed_unit_codes`, LOINC `5811-5` | 274 | `{SG}` and `{nominal}` appear for the same measurement code | Investigate coding and value types; retain original values |
| `mixed_unit_codes`, LOINC `788-0` | 303 | `%` and `fL` appear for the same code | Treat as a possible semantic mismatch; do not convert automatically |
| `mixed_unit_codes`, LOINC `89579-7` | 64 | `ng/L` and `pg/mL` appear for the same code | Verify the measurement definition; these mass-concentration units have a possible 1:1 numeric relationship, but normalize only after validation |
| `document_not_current` | 4,975 | Documents have a status other than `current` | Exclude from *default current-document* RAG retrieval; preserve historical documents and provenance |

**Important:** Affected-row counts represent each rule's scope, not the number of unique patients or the number of erroneous records. Multiple rules may overlap. The source audit groups observations by measurement code (and component code, if present); a flagged group can include rows that are individually valid.

## Relevance to the business problem

- **Data reliability:** resolving unit-code ambiguity is essential for accurate patient-specific comparisons and structured retrieval.
- **Clinical context:** excluding superseded documents from default *current-state* retrieval reduces the risk of presenting outdated information as current.
- **Traceability:** preserve `source_file`, FHIR IDs, observation codes, component codes, and original UCUM values through the transformation pipeline.
- **Operational efficiency:** a consistent Silver layer prepares structured data for SQL/API retrieval and improves the quality of context supplied to the LLM.

## Next actions

1. Run `src/review_quality_findings.py` on the **complete local transformed CSVs** to create record-level review files.
2. Examine unit-code conflicts against the corresponding original FHIR JSON and terminology definitions.
3. Record approved normalization rules in a transformation log; do **not** fabricate or automatically overwrite missing clinical values.
4. Distinguish `current` from historical document statuses before any RAG indexing. Ensure patient-scoped authorization and citation-based retrieval.
5. Re-run audit checks after implementing the approved Silver-layer transformations.

## Data architecture mapping

- **Bronze:** original Synthea FHIR JSON files; immutable source of truth.
- **Silver (candidate):** transformed CSVs, data-quality audit, reviewable normalization rules and validated joins.
- **Gold (future):** patient-centric SQL views, indicators for Power BI, and controlled retrieval endpoints for Qwen/RAG.

## Limitations

The source contains **synthetic** clinical records. This document does not establish patient safety, clinical equivalence of codes or units, compliance with applicable regulations, or security of future RAG access. Before production use, a clinical data steward and security owner must approve the relevant transformation and access-control policies.
