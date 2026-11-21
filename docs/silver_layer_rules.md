# Silver Layer — Transformation Rules and Governance

## Objective

Create traceable, conservative Silver tables from the FHIR-derived CSVs generated in the previous phase of DataHealth AI. The raw Synthea FHIR JSON files remain the original source of truth (Bronze). The source-derived intermediate CSVs remain unchanged.

## Rules

| Rule | Implementation | Rationale |
|---|---|---|
| Preserve provenance | Retain `source_file`, resource identifiers, original LOINC code, original units, and numeric values | Allow reinspection of the source record |
| Validate patient/encounter links | Flag missing or unresolved observation references and summarize cross-table reference failures | Prevent unsupported patient-specific results |
| Validate measurement structure | Flag missing unit code, invalid numeric value, and inconsistent unit coding within a coded measurement group | Avoid silent conversion or aggregation of incompatible measurements |
| Preserve compound observations | Retain `observation_id` and `component_index` for blood-pressure components | Avoid collapsing systolic and diastolic results |
| Validate observation dates | Flag missing/invalid ISO timestamps | Support traceable, time-based queries |
| Preserve potentially problematic observations | Append `quality_status` and `quality_flags`; never drop flagged rows | Make anomalies auditable |
| Handle document status | Only `current`, text-bearing, patient-linked documents become preliminary RAG candidates | Avoid indexing superseded content as current evidence |

## Known semantic review cases (from initial quality investigation)

- LOINC `33914-3`: `mL/min` vs `mL/min/{1.73_m2}` — do not assume equivalence.
- LOINC `5803-2`: `[pH]` vs `pH` — inspect source representation before canonicalization.
- LOINC `5811-5`: `{SG}` vs `{nominal}` — review coding semantics.
- LOINC `788-0`: `%` vs `fL` — likely distinct RDW reporting forms; verify code mapping.
- LOINC `89579-7`: `ng/L` vs `pg/mL` — potential unit equivalence should be assessed with terminology and validation rules.

## RAG safety boundary

`rag_preliminary_candidates.csv` is **not** an authorized RAG index. Before retrieving patient data, implement user identity, patient-level authorization, audit logging, secure storage, and source citations. Exclude superseded content from default *current* searches while allowing separately authorized historical review.

## Validation limitations

The pipeline provides structural flags only. It does not establish clinical validity, comprehensive FHIR conformance, correct LOINC semantics, acceptable clinical ranges, or suitability for clinical decision-making. All data in this educational prototype must be synthetic.
