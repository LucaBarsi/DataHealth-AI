# DataHealth AI — Phase 8: Hybrid Assistant Evaluation

This package adds a **reproducible evaluation script** to the existing project. It does not replace any Phase 5–7 modules and does not modify the Gold Layer or vector index.

## 1. Install the files

- Copy `src/evaluate_hybrid.py` into the existing `src/` folder.
- Copy `tests/test_evaluate_hybrid.py` into the existing `tests/` folder.
- Copy `docs/llm_evaluation_methodology.md` into the existing `docs/` folder.
- Put this README in the repository root.

**All commands are run from the repository root in Windows PowerShell.** Use the Python 3.12 virtual environment already configured for Phase 6.

## 2. Run automated tests first

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_evaluate_hybrid.py" -v
```

## 3. Run a retrieval-only preflight test (no Qwen inference)

```powershell
.\.venv\Scripts\python.exe -m src.evaluate_hybrid run --patient-id "e34fa1e8-0cbc-0d22-89d4-6996de874bd8" --max-cases 2 --dry-run --output "reports/llm_evaluation/preflight"
```

This creates `evaluation_summary.json` and `evaluation_results.jsonl`. No LLM answer is generated. The RAG index and local Ollama embedding endpoint are needed only for cases using RAG; the first two cases use SQL only.

## 4. Evaluate the hybrid assistant with Qwen

Make sure Ollama is running, with `qwen3.5:4b` and `nomic-embed-text` installed:

```powershell
ollama list
```

Then start with **three cases**:

```powershell
.\.venv\Scripts\python.exe -m src.evaluate_hybrid run --patient-id "e34fa1e8-0cbc-0d22-89d4-6996de874bd8" --max-cases 3 --output "reports/llm_evaluation/first_run"
```

If this works, run the full six-case set in a **new output folder**:

```powershell
.\.venv\Scripts\python.exe -m src.evaluate_hybrid run --patient-id "e34fa1e8-0cbc-0d22-89d4-6996de874bd8" --max-cases 6 --output "reports/llm_evaluation/full_run"
```

Each run produces:

- `evaluation_results.jsonl`: questions, exact retrieved evidence, full answers, source markers, latency.
- `evaluation_summary.json`: counts, latency summary, basic marker checks. Does not claim factual accuracy.
- `manual_review.csv`: one blank scoring row for each generated answer.

The script refuses to overwrite an existing nonempty output directory. Use a new folder for subsequent runs.

## 5. Review the factual statements

Fill `manual_review.csv` with evidence-grounded scores, using the [evaluation methodology](../llm_evaluation_methodology.md). Example labels:

- `factual_accuracy`: `correct` / `partial` / `incorrect`
- `citation_support`: `supported` / `partial` / `unsupported`
- `patient_isolation`: `pass` / `fail`
- `unsafe_clinical_advice`: `yes` / `no`
- `factual_claims`, `unsupported_claims`: nonnegative integers

Run:

```powershell
.\.venv\Scripts\python.exe -m src.evaluate_hybrid review --output "reports/llm_evaluation/first_run"
```

The aggregated, manually scored metrics are written to `manual_review_summary.json`. Empty rows are not scored. Each metric clearly displays its population/denominator.

## 6. Review outputs with ChatGPT

Share `evaluation_summary.json` and `evaluation_results.jsonl` from the first run. We can review each generated answer, compare it with the included evidence, then fill in the manual scoring rubric together.

**Do not interpret a successful source-ID check as a verified clinical fact.** This is synthetic-data-only research and a prototype, not a medical device or a clinically validated system.
