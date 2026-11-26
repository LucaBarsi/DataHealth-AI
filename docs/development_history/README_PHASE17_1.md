# DataHealth AI — Phase 17.1: RAG Retrieval Benchmarking

## Purpose

This isolated experiment compares the Cloud Demo's existing keyword-overlap retrieval with the Phase 17 FastEmbed/ONNX cosine retrieval method. It uses **hand-authored fictional notes only** and makes **zero hosted Qwen API calls**. It does **not** change the Streamlit app or its production demonstration fixtures.

## What is included

| File | Destination | Action |
|---|---|---|
| `cloud_demo/retrieval_benchmark.py` | `cloud_demo/` | Add |
| `cloud_demo/benchmark_fixtures.json` | `cloud_demo/` | Add (separate dataset) |
| `cloud_demo/benchmark_queries.json` | `cloud_demo/` | Add |
| `tests/test_retrieval_benchmark.py` | `tests/` | Add |
| `docs/phase17_1_retrieval_benchmark.md` | `docs/` | Add |
| `README_PHASE17_1.md` | Repository root | Add |

There are **4 fictitious patients, 32 notes, and 28 benchmark questions**, with one manually specified relevant note per question. Most benchmark notes and questions are synthetic administrative or laboratory workflow examples; none establish clinical truth.

**Do not overwrite** `cloud_demo/sample_records.json` or `cloud_demo/semantic_index.json`. The public Cloud Demo continues using its existing four notes while this separate benchmark is evaluated.

## Step 1 — Automated tests (no model download)

From the project root, in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_retrieval_benchmark.py" -v
```

Expected: **19 tests — OK**. The semantic-path unit tests use a small injected fake embedder only to test plumbing; they are **not** evidence of FastEmbed retrieval quality.

## Step 2 — Lexical reference run (offline, no download)

```powershell
.\.venv\Scripts\python.exe -m cloud_demo.retrieval_benchmark run --mode lexical --output "reports/rag_benchmark/phase17_1_lexical"
```

In our controlled reference run, using the included 28 questions, lexical retrieval produced Recall@1 = **0.7500**, Recall@3 = **0.8571**, and MRR@3 = **0.7857**. Machine-dependent latency values should not be compared to other hosts.

## Step 3 — Full comparison (real local ONNX embeddings)

Ensure the Phase 17 dependencies are installed:

```powershell
.\.venv\Scripts\python.exe -m pip install -r cloud_demo/requirements.txt
```

Then execute the real comparison:

```powershell
.\.venv\Scripts\python.exe -m cloud_demo.retrieval_benchmark run --mode both --output "reports/rag_benchmark/phase17_1"
```

The first run may need to fetch the FastEmbed model; it uses no hosted LLM API key. If the model cannot be downloaded or initialized, the command will fail explicitly — **no semantic score is fabricated**. The lexical-only run remains usable.

## Reports

Output files:

- `benchmark_summary.json` — aggregate metrics per method
- `benchmark_results.jsonl` — ranked document IDs and per-question metrics
- `benchmark_results.csv` — results for inspection in spreadsheets
- `benchmark_report.md` — short English interpretation

Metric definitions:

- **Recall@1**: fraction of gold relevant IDs recovered in rank 1
- **Recall@3**: fraction of gold relevant IDs recovered in the top 3
- **MRR@3**: mean reciprocal rank of the first relevant document in the top 3
- **Latency**: per-query retrieval time only; excludes embedding model download, index build, and Qwen generation

Because there is exactly **one gold document per question**, Recall@k also equals Hit@k on this dataset. The dataset and labels were **constructed by the project authors**; these metrics do not establish real-world generalization, factual truth, or clinical validity. The semantic model's actual performance is unknown until you run it.

## Next steps

Review failures and relevance labels, run repeated measurements for timing stability, and discuss whether more realistic paraphrases and several relevant documents per question would improve the benchmark. Do not publish comparative performance claims based on the fake-embedder unit tests.
