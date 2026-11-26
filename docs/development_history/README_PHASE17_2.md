# DataHealth AI — Phase 17.2: Hybrid Retrieval Benchmarking

## Objective

Evaluate whether **Reciprocal Rank Fusion (RRF)**, combining the existing lexical and semantic document rankings, improves retrieval performance on the **same 28 hand-authored questions and 32 fictional notes** used in Phase 17.1. The goal is to select a retrieval strategy using measured evidence, **not** to claim that hybrid search is inherently superior.

This update is **benchmark-only**. It does **not** replace the public Streamlit Cloud application, change the hosted Qwen API, or require a new API key.

## Files to add

| Package file | Destination in `datahealth_ai_starter` |
|---|---|
| `cloud_demo/hybrid_benchmark.py` | `cloud_demo/hybrid_benchmark.py` |
| `tests/test_hybrid_benchmark.py` | `tests/test_hybrid_benchmark.py` |
| `docs/phase17_2_hybrid_retrieval.md` | `docs/phase17_2_hybrid_retrieval.md` |
| `README_PHASE17_2.md` | Root of project |

The Phase 17.1 files `cloud_demo/retrieval_benchmark.py`, `cloud_demo/benchmark_fixtures.json`, and `cloud_demo/benchmark_queries.json`, and Phase 17's `cloud_demo/semantic_retrieval.py`, must already exist. **Do not overwrite** the production `sample_records.json`, `semantic_index.json`, or `streamlit_app.py`.

## 1. Run offline unit tests

In the PowerShell terminal at the project root:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_hybrid_benchmark.py" -v
```

Expected: `Ran 19 tests ... OK`. These use fake embeddings solely for testing program logic and never report model-quality benchmark metrics.

Optional regression tests:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_retrieval_benchmark.py" -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_cloud_semantic_rag.py" -v
```

## 2. Run real local benchmark (FastEmbed CPU)

```powershell
.\.venv\Scripts\python.exe -m cloud_demo.hybrid_benchmark run --output "reports/rag_benchmark/phase17_2"
```

The program uses the **real local FastEmbed `BAAI/bge-small-en-v1.5` model**, comparing lexical, semantic, and equal-weight RRF on exactly the same 28 questions. The model may need to download its ONNX files on first use. There are **no hosted Qwen API calls**.

Default fusion uses `rrf_k=60`, `lexical_weight=1.0`, and `semantic_weight=1.0`. These choices are fixed in advance and are **not tuned to the results**.

## 3. Inspect results

Open `reports/rag_benchmark/phase17_2/`:

- `hybrid_summary.json` — Recall@1, Recall@3, MRR@3, timings, wins/ties/losses.
- `hybrid_results.csv` — per-query data for the three retrieval methods.
- `hybrid_results.jsonl` — structured raw benchmark results.
- `hybrid_report.md` — comparison table and question-level failures.

### How to interpret

A hybrid approach is beneficial only if it improves ranking for the desired workload without unacceptable latency or extra complexity. **If semantic-only search remains as good or better, prefer the simpler semantic approach.** Performance is measured on a small illustrative corpus and must not be presented as clinical accuracy.

## 4. Optional GitHub update

After reviewing the new code and excluding any credentials:

```powershell
git add cloud_demo/hybrid_benchmark.py tests/test_hybrid_benchmark.py docs/phase17_2_hybrid_retrieval.md README_PHASE17_2.md
git diff --cached --check
git diff --cached --name-only
git commit -m "Benchmark hybrid RRF retrieval on fictional notes"
git push
```

This commits only benchmark code and documentation. It does **not** deploy hybrid retrieval to Streamlit Cloud. Do not upload the test fixtures to the production demo database or claim improved performance before the real local run.

## Safety and limitations

- All input records are invented, with manually assigned relevance labels; no human clinical records are used.
- Retrieval rankings are **patient-scoped before fusion**; the fusion rejects mismatched candidate sets.
- No clinical reasoning or answer correctness is measured; this benchmark tests document retrieval only.
- FastEmbed downloads are not API usage, but CPU latency varies by hardware.
- For a rigorous generalization claim, build a larger independent evaluation set and tune parameters only on a separate development set.
