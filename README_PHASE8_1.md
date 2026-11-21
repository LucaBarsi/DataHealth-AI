# DataHealth AI — Phase 8.1: Citation Reliability

## Purpose
Improve **citation-ID reliability** for the existing Qwen 3.5 4B + Ollama + SQLite + ChromaDB prototype. This is a synthetic-data educational application, NOT a clinical decision support system.

The Phase 8 evaluation found two unknown citation markers (`[SQL: ...]` and a document ID without `#chunk:0`). We add a separate, citation-guarded assistant without replacing the working Phase 7 scripts or any Bronze/Silver/Gold records.

## Add these files
- `src/reliable_assistant.py` — guarded Qwen generation, exact citation-ID audit, one retry, evidence-only fallback.
- `src/evaluate_reliability.py` — reruns the **same six Phase 8 questions** and produces a new report, without overwriting `full_run`.
- `tests/test_reliable_assistant.py` — offline, mocked tests.
- `docs/reliability_citation_policy.md` — security and evaluation policy.

Keep `src/hybrid_assistant.py`, `src/evaluate_hybrid.py`, your Gold SQLite database and ChromaDB index unchanged.

## Requirements
The existing project's `.venv` (Python 3.12), Ollama models `qwen3.5:4b` and `nomic-embed-text`, and earlier project dependencies. No additional pip packages are needed.

From `datahealth_ai_starter`, with the regular PowerShell terminal:

### 1. Run the new offline tests
```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_reliable_assistant.py" -v
```
Expected: **10 tests, OK**. These tests mock Ollama and do not verify clinical accuracy.

### 2. Test the reliability guard for one patient
```powershell
.\.venv\Scripts\python.exe -m src.reliable_assistant --patient-id "e34fa1e8-0cbc-0d22-89d4-6996de874bd8" --mode hybrid --topic medications --question "Compare medication requests in structured records with what the latest clinical note says about medications. Cite both sources and note any missing evidence."
```
The output ends with one of the following:
- `CITATION_IDS_VALID` — all displayed citation IDs matched retrieved sources; **not** a claim-level correctness guarantee.
- `EVIDENCE_ONLY_FALLBACK` — after a retry the model still used invalid IDs; the unverified response was discarded, and structured evidence was displayed instead.
- `NO_ELIGIBLE_EVIDENCE` — the LLM was not called.

### 3. Re-run all six questions in a NEW directory
```powershell
.\.venv\Scripts\python.exe -m src.evaluate_reliability --patient-id "e34fa1e8-0cbc-0d22-89d4-6996de874bd8" --max-cases 6 --baseline "reports/llm_evaluation/full_run/evaluation_results.jsonl" --output "reports/llm_evaluation/reliability_run"
```

New reports:
- `reports/llm_evaluation/reliability_run/evaluation_summary.json`
- `reports/llm_evaluation/reliability_run/evaluation_results.jsonl`
- `reports/llm_evaluation/reliability_run/comparison_to_baseline.json`
- `reports/llm_evaluation/reliability_run/manual_review.csv`

**Do not copy/rename/replace** your previous `full_run/manual_review.csv`. This is a new experiment and the review CSV begins blank.

If you need to repeat the run, specify a fresh output directory, e.g. `reliability_run_2`. Existing output is intentionally never overwritten.

## Interpretation
The comparison measures exact source marker IDs; it does **not** measure factual accuracy, clinical safety, or whether citations substantively support every statement. A fallback is counted separately from a successful LLM-generated answer and must not be reported as a successful generation.

## Safety
Only SYNTHETIC Synthea data. Avoid real patient data, secrets and published database files. Patient ID selection is not real-world authorization; a production deployment would require authentication, authorization, audit logging, secure storage and more robust validation.
