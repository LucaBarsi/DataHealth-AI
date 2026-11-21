# DataHealth AI — Initial FHIR Mapping and Transformation Rules

## Scope

This initial ETL extracts a selected set of FHIR R4 resources from Synthea-generated **synthetic** bundles into CSV tables for downstream exploration and a future LLM assistant. It does not validate clinical correctness or fully implement the FHIR specification.

## Findings from the examined bundle

- Bundle type: `transaction`; 67 entries in this bundle, including 1 Patient, 3 Encounters, 41 Observations, 4 DiagnosticReports, 1 Condition, 3 DocumentReferences and 7 Immunizations.
- Observation value representations: 35 `valueQuantity`, 3 `valueCodeableConcept`, and 3 observations with `component` arrays. Each blood-pressure panel has separate diastolic (`8462-4`) and systolic (`8480-6`) components.
- The examined DiagnosticReport for a CBC panel references 11 Observation resources using `result[].reference`. Three other reports contain no `result` links.
- Three DocumentReference resources contain Base64-encoded `text/plain` attachments. Their statuses are `superseded`, `superseded` and `current`. Only suitable, authorized, non-superseded records should be considered for future RAG retrieval.
- This particular bundle contains **no** MedicationRequest. The dataset overall may contain such resources.

## Mapping rules and rationale

1. **Patient identity:** normalize `urn:uuid:<id>` to `<id>` only for recognized ID-based references. Do not use a patient's display name as a join key. Preserve source JSON for traceability.
2. **Patient minimization:** export only patient ID, gender, and date of birth. Do not export synthetic SSN, telephone or address even for a demo.
3. **Temporal provenance:** preserve original FHIR ISO-8601 date/time strings including time-zone offsets. Do not silently convert or truncate dates.
4. **Clinical codes:** preserve the original code system, code and display for each resource. The first coding is used in this prototype; future support should handle multiple coding entries.
5. **Quantities:** separate numeric value, human-readable unit, UCUM code and unit system. Do not automatically convert units before reviewing their semantics.
6. **Composite observations:** emit one CSV row per `Observation.component`, retaining the original `observation_id` and an explicit `component_index`.
7. **Coded observations:** keep terminology code and display rather than coercing categorical observations to numbers.
8. **Diagnostic report relationships:** store `DiagnosticReport.result[].reference` in a separate join table; a report may have zero results.
9. **Document content:** decode embedded Base64 text only when `contentType` starts with `text/plain`; do not attempt to decode PDF or image attachments as plain text.
10. **Lineage:** include `source_file` and FHIR profile metadata where available in exported rows.

## Current limitations / next validations

- **Not a FHIR validator:** check references, identifier uniqueness, correct code-to-unit mapping and terminology against the applicable FHIR profiles before production use.
- **No unit normalization yet:** require explicit mapping with tests before harmonizing units (e.g. UCUM).
- **Incomplete resource coverage:** additional resource types, including Immunization, Procedure, claims and provenance, are not yet flattened.
- **Clinical documents for RAG:** filter by document status (`current` vs. `superseded`), remove any identifying fields when working beyond synthetic data, and enforce per-patient authorization before indexing/retrieval. Treat retrieved documents as untrusted content.
- **Safe model behavior:** an LLM should use structured queries for measurements, cite underlying resources and abstain when evidence is insufficient. This prototype does not provide medical diagnosis or emergency alerts.

## Run locally

Place `src/transform_fhir.py` in the project's existing `src` directory. From the project root:

```powershell
python -m src.transform_fhir --input "data/raw/synthea_sample_data_fhir_latest" --output "data/processed/fhir"
```

To test just one bundle:

```powershell
python -m src.transform_fhir --input "data/raw/synthea_sample_data_fhir_latest/Abraham100_Hackett68_e34fa1e8-0cbc-0d22-89d4-6996de874bd8.json" --output "data/processed/patient_demo"
```

The first command exports all available Synthea JSON files (when present). The second command is a small validation run on the inspected bundle.
