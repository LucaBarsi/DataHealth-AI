# DataHealth AI — Phase 7: Hybrid SQL + RAG Assistant

## Business problem and scope

DataHealth AI reduces the manual effort needed to locate a synthetic patient's structured clinical records and narrative notes across different data representations. The Phase 7 prototype combines a read-only Gold SQLite query layer with patient-filtered retrieval from the Phase 6 ChromaDB index and a local Qwen 3.5 4B model running through Ollama.

**This is an educational demonstration using synthetic Synthea data. It is not a clinical decision-support or authorized production EHR system.**

## End-to-end flow

1. The caller supplies a `patient_id` and a question.
2. The application checks that the patient exists in Gold SQLite.
3. A deterministic rule-based router chooses `sql`, `rag`, or `hybrid` retrieval. The user may override the mode, and may select a fixed SQL topic.
4. SQL records are retrieved through predefined, parameterized, read-only statements from the Gold Layer. The LLM never writes or executes SQL.
5. RAG passages are retrieved from the existing ChromaDB index, filtered by `patient_id`, and restricted to previously indexed current-document candidates.
6. Evidence with stable `[SQL:...]` and `[DOC:...]` markers is sent to local Qwen 3.5 4B.
7. The CLI prints the answer and a separately generated list of retrieved source markers. A retrieved-marker list does **not** prove that a generated claim is factually supported; output review remains necessary.

## Data provenance and semantics

- Structured data: SQLite is the authoritative source for quantitative values and medication *requests* in this prototype.
- Narrative data: Indexed FHIR `DocumentReference` text provides statements from dated notes; these statements are not substitutes for current SQL records.
- A medication order is not proof of administration or adherence.
- A note stating “No Active Medications” does not establish the absence of medication requests or subsequent medications.
- Source dates, observation IDs, document IDs, units, and quality flags must be preserved.
- `PASS_STRUCTURAL_CHECKS` is not clinical validation. Rows flagged for semantic review should not be silently normalized.
- All source records remain in Bronze/Silver/Gold; Phase 7 is read-only.

## Scope and limitations

The router uses simple English keyword rules, not an evaluated language-model tool-selection mechanism. Topic coverage is limited, and some questions may require manually setting `--mode hybrid` or `--topic`. SQL results are limited per topic, and RAG retrieval is limited by `--top-k`; absence from the returned context does not prove absence from the dataset.

Document candidates are filtered by source status and patient identity, **not** by a real authenticated user's authorization. No genuine protected health information may be used without an additional access-control architecture, auditing, data protection and clinical validation. Embeddings and notes must remain local in this prototype.

## Quality gates for the next phase

- Verify each SQL value, unit, timestamp and marker against the SQLite source.
- Verify each documentary assertion against the retrieved excerpt and timestamp.
- Test cross-patient isolation and unknown-patient behavior.
- Evaluate at least ten known-answer questions across SQL-only, RAG-only and hybrid retrieval; log errors and missing evidence.
- Record response latency for SQL, embedding retrieval and Qwen separately before claiming performance improvements.
- Handle authentication and authorization before any non-synthetic deployment.

## Enterprise architecture mapping

This hybrid assistant consumes Gold analytical/serving data produced by the proposed Bronze/Silver/Gold Data Lakehouse. Python/Pandas currently perform local transformations; Apache Spark, Kafka, HL7 FHIR APIs and Azure/AWS remain planned enterprise-scale components, not claims of completed cloud deployment. Power BI will use appropriate analytics outputs and will not directly replace source-verifiable clinical queries.
