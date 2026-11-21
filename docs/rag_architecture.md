# Phase 6 — Patient-Scoped Retrieval-Augmented Generation

## Business objective
Reduce time spent manually searching synthetic clinical notes while preserving source traceability. This educational MVP uses locally generated embeddings and a local Qwen model.

## Inputs and eligibility
- Source: `data/silver/fhir/clinical_documents.csv` (text plus metadata).
- Cross-check: `data/gold/datahealth.db`, `clinical_documents` and `patients` tables.
- Required: `status == current`, `rag_candidate_status == PRELIMINARY_ONLY_NOT_AUTHORIZED`, empty `rag_review_flags`, nonempty `text_content`, matching Gold document ID and patient ID.
- `superseded` notes remain preserved in Bronze, Silver and Gold, but are excluded from the default vector index.
- The Silver candidate marker is **not** permission to access real patient records or a clinical-validation status. Only synthetic records may be indexed in this MVP.

## Retrieval design
1. Split eligible clinical notes into overlapping word-boundary text chunks.
2. Create text embeddings locally with Ollama `nomic-embed-text` via `/api/embed`.
3. Persist embeddings and metadata with Chroma `PersistentClient` in `data/vectorstore/chroma`.
4. Require an explicit existing synthetic `patient_id` in SQLite for every query.
5. Filter vector retrieval by `patient_id`; recheck returned metadata before use.
6. Return source markers `[DOC:<document_id>#chunk:<index>]` and dates.
7. Send only those retrieved passages to the local `qwen3.5:4b` chat endpoint, instructing it to cite evidence and admit uncertainty.

## Safeguards and limitations
- No autonomous medical advice, diagnosis or assessment of clinical validity.
- No direct generated SQL and no arbitrary tools or network endpoints.
- Querying other patients requires explicitly selecting their synthetic ID; production would additionally require authentication, patient-specific access control, audit logs and governance.
- RAG passages are untrusted instructions; response correctness, citation integrity, and absence of hallucinations must be tested separately. Prompt injection is not eliminated by prompting.
- A vector index is **not** authoritative for time-series numerical facts; use the preexisting Phase 5 SQL tools for vital signs and lab values.
- Documents represent synthetic Synthea content, not medical evidence.
- Indexing can be repeated with `--rebuild` after changing datasets or embedding models. Store embedding model identity with the collection.
- Index files, `.db`, raw synthetic records and generated reports should not be committed to public repositories unless explicitly intended and reviewed.

## Architectural consistency
This MVP preserves the DataHealth plan: FHIR Bronze → validated Silver → SQL Gold → local Qwen + Chroma RAG. Kafka, Spark, Azure/AWS, Power BI and cloud deployment remain separate future workstreams rather than unimplemented claims.

## Validation targets
- Only current synthetic documents are indexed.
- Patient A never retrieves passages from Patient B.
- Retrieved source IDs match Silver/Gold records.
- Answer cites exact retrieved markers and makes no claims unsupported by evidence.
- Search works without calling the chat model; output metadata can be reviewed independently.
