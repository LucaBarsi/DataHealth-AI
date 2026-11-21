# Patient Display Names — FHIR to Gold Layer

## Business objective

Expose **synthetic** patient display names in the local DataHealth AI SQL prototype while retaining `patient_id` as the sole reliable lookup and join key. Names must not be used for identity matching, authorization, or patient record linkage.

## FHIR source and transformation

- Source: `Patient.name`, a FHIR `HumanName` list in the unmodified Synthea JSON bundles (Bronze).
- Choose the `HumanName` element with `use = "official"`, if present; otherwise use the first valid name element.
- `first_name`: first non-empty string in `name.given`.
- `last_name`: `name.family`, if present.
- `full_name`: `name.text` if explicitly provided; otherwise concatenate all `name.given` values and `name.family` with single spaces. This retains additional given names in the display label.
- If the source lacks these fields, store blank values in the transformed CSV and `NULL` in SQL. Do not invent patient names.
- Preserve `patient_id`, `gender`, `birth_date`, `source_file`, and `fhir_profiles` unchanged.

## Lineage

1. **Bronze:** `data/raw/synthea_sample_data_fhir_latest/*.json` is read-only.
2. **Processed FHIR:** `src.transform_fhir` exports `first_name`, `last_name`, and `full_name` to `data/processed/fhir/patients.csv`.
3. **Silver:** the existing `src.build_silver` propagates these columns to `data/silver/fhir/patients.csv` without altering its clinical quality controls.
4. **Gold:** `src.build_gold` creates the new columns in the SQLite `patients` table and `v_patient_overview` view. The read-only `src.query_gold list-patients` displays them.

## Acceptance checks

- Synthetic names match the chosen FHIR `Patient.name` values.
- The number of patient IDs and other record counts is unchanged.
- `PRAGMA foreign_key_check` returns no errors.
- Clinical values and existing `quality_flags` remain untouched.
- Full names are visible in SQLite Viewer, `list-patients`, and `patient-overview`.

## Limitations

This dataset is synthetic. In any real healthcare deployment, displaying names or accessing clinical records requires authentication, patient-level authorization, privacy controls, auditing, and an appropriate legal basis. Avoid exposing identifiable patient data in logs, exports, or prompts to external services.
