# DataHealth AI — Phase 17.3: RRF Error Analysis and Held-Out Tuning

This package contains **only new files**. It is designed to be dropped into the existing `datahealth_ai_starter` repository **after Phases 17.1 and 17.2**. It does not replace the public Cloud Demo or modify the deployed LLM.

## Installation

Copy the following files preserving their relative paths:

```text
cloud_demo/rrf_weight_analysis.py
tests/test_rrf_weight_analysis.py
docs/phase17_3_rrf_weight_analysis.md
README_PHASE17_3.md
```

## Test

From the project root in VS Code PowerShell:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_rrf_weight_analysis.py" -v
```

Expected: `Ran 18 tests ... OK`.

Optional check of previous benchmarks:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*benchmark.py" -v
```

## Run the genuine FastEmbed experiment

```powershell
.\.venv\Scripts\python.exe -m cloud_demo.rrf_weight_analysis run --output "reports/rag_benchmark/phase17_3"
```

Outputs:

```text
reports/rag_benchmark/phase17_3/
  weight_analysis_summary.json
  weight_analysis_results.csv
  weight_analysis_results.jsonl
  weight_analysis_report.md
```

These metrics have **not** been executed with a real embedding model in the package author's environment. Run them on your machine as in Phases 17.1–17.2. The supplied unit tests use fake vectors and must not be interpreted as performance evidence.

## What is different from Phase 17.2?

Phase 17.2 compared 1:1 RRF with lexical and semantic retrieval on the **same 28 queries**. Phase 17.3 defines a small grid before evaluation and uses **leave-one-fictional-patient-out selection**, reporting held-out results rather than selecting a globally best weight from those same evaluation queries.

Because the dataset is small and topics are reused, even this design is exploratory. It does **not** justify switching the live app. Keep the existing semantic retriever in production.

## Version control (only if tests pass and files are reviewed)

```powershell
git add cloud_demo/rrf_weight_analysis.py tests/test_rrf_weight_analysis.py docs/phase17_3_rrf_weight_analysis.md README_PHASE17_3.md
git diff --cached --check
git diff --cached --name-only
git commit -m "Evaluate RRF weights with held-out fictional patients"
git push
```

Review the staged files before committing. Do not add API keys, local model caches, or benchmark outputs to Git unless explicitly reviewed and intended for publication.

## Next phase — ML integration

**Proceed to Phase 18 regardless of the RRF outcome.** Keep the retrieval system as currently deployed. Phase 18 will implement an independent exploratory ML workflow for **synthetic healthcare operations**, with time-aware validation, explicit baselines, and no claims of clinical deployment readiness.
