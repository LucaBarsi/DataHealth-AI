# Phase 5 — Local LLM Integration (SQL-grounded MVP)

## Business goal

Reduce time spent finding synthetic patient information spread across multiple clinical record types. Deliver a conversational interface based on verifiable, read-only Gold Layer queries. The assistant does **not** predict disease or make clinical decisions.

## Scope and constraints

- **Local model:** Qwen 3.5 4B served through Ollama (`qwen3.5:4b`).
- **Data source:** local SQLite Gold Layer built from Synthea FHIR synthetic records.
- **Tool boundary:** Python selects only predefined SQL queries. Users explicitly supply a synthetic `patient_id` and a `topic`. The LLM cannot run arbitrary SQL or independently browse the database.
- **Evidence:** selected results contain source record identifiers, timestamps, units and quality flags where present. Not all results have units or timestamps.
- **Privacy:** do not use real health records. This prototype has no user authorization system; real clinical usage is prohibited.
- **RAG:** postponed to the next phase. This version does not retrieve `DocumentReference` text or create embeddings.
- **No cloud:** inference and queries run locally. Azure/AWS, Spark and Kafka remain documented enterprise architecture components for later implementation.

## Data flow

`User question + patient ID + allowlisted topic -> Python/SQLite (read-only) -> limited evidence -> local Ollama HTTP API -> generated summary`

The source database and previous Bronze/Silver/Gold outputs are not modified.

## Query topics

`overview`, `observations`, `laboratory`, `vitals`, `conditions`, `medications`, `reports`.

The interface uses a two-step query pattern: inspect with `context` first; then request a model-produced explanation with `ask`.

## Quality and clinical safeguards

1. SQL uses bound parameters and opens the database in read-only mode.
2. The model receives a bounded set of rows (at most 25); it cannot choose another patient or run SQL.
3. Flagged observations keep their original quality metadata; the assistant is told not to erase the caveat.
4. Medication prescriptions are not proof of ingestion or administration.
5. Outputs are not medically validated. The model may still hallucinate; verify all values against the returned evidence.
6. Data and metadata are handled strictly as untrusted content. Prompt injection remains a risk in future document retrieval; additional filtering, access control, auditing and evaluation are required before real deployment.

## Manual validation checklist

- Ensure the patient identifier is valid and scoped to the expected synthetic patient.
- Run `context` and verify the counts, timestamps, units and quality flags.
- Run `ask` and compare every stated value to the `context` output.
- Test a patient with no medication records; no data should be fabricated.
- Test an unknown patient ID; no database records should be retrieved.
- Test when Ollama is stopped; the script should fail with a useful error.
- Evaluate time to response and factual accuracy before adding RAG.

## Next phase

Build a separate RAG pipeline using approved *synthetic* clinical document content. Index only explicitly vetted documents, keep source references and patient filtering, use ChromaDB, and evaluate retrieval separately from generation.
