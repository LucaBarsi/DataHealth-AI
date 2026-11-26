# Phase 17.2 — Hybrid Retrieval (Reciprocal Rank Fusion)

## Motivation

Phase 17.1 compared lexical keyword overlap with ONNX semantic cosine retrieval using 28 handcrafted fictional queries, 32 documents, and four fictional patient identities. In that small experimental run, semantic search achieved a higher Recall@1, Recall@3, and MRR@3, with longer query processing time. The next question is whether **rank fusion** offers an additional improvement over either method alone.

The benchmark is a controlled, local **retrieval-only** experiment. The deployed Streamlit UI and its fictional dataset remain unchanged.

## Fixed approach

1. Load only the explicitly fictional Phase 17.1 fixtures and hand-authored gold relevance IDs.
2. Validate the query labels and ownership of every relevant document.
3. Build one FastEmbed index using `BAAI/bge-small-en-v1.5` and normalize the vectors.
4. For each question, restrict the candidate set **to the selected patient** and rank all eight of that patient's notes:
   - Lexical: word overlap followed by document date (existing Phase 17.1 behavior).
   - Semantic: cosine similarity from the Phase 17 vector index.
5. Fuse complete patient-scoped rankings with **Reciprocal Rank Fusion (RRF)** using equal weights and `k=60`.
6. Evaluate all three ranked lists at **top 1** and **top 3** against the same gold labels.
7. Record mean, median, maximum query latency and per-query improvements/regressions.

### Fusion formula

For document `d`:

```text
RRF(d) = (lexical_weight / (rrf_k + lexical_rank(d)))
       + (semantic_weight / (rrf_k + semantic_rank(d)))

Defaults: rrf_k = 60; lexical_weight = semantic_weight = 1.0.
```

Positions are one-indexed. Ties are broken deterministically using the best original rank and then document ID. RRF scores are **not probabilities** and do not represent truthfulness, clinical relevance, or diagnostic confidence.

## Metrics

| Metric | Operational interpretation |
|---|---|
| Recall@1 | Fraction of labeled relevant documents retrieved in the first position; with one gold label per question it is top-1 hit rate. |
| Recall@3 | Fraction of labeled relevant documents within the first three results. |
| MRR@3 | Mean reciprocal rank of the first gold document among the top three positions. |
| Mean query latency (ms) | Local CPU wall-clock retrieval time after embedding warmup; no model download or generation. |
| Hybrid wins/ties/losses | Number of queries whose top-1 accuracy improved, tied, or worsened relative to each baseline. |

### Fairness checks

- The **same questions and labels** are evaluated for all methods.
- Semantic and lexical rankings contain the **same patient-owned document IDs** before fusion.
- Model loading, index construction and warmup are excluded from per-question latency, but index build time is reported separately.
- Hybrid latency covers both retrieval stages plus fusion, rather than just the fusion calculation.
- Parameter tuning is deliberately not performed on the 28 evaluation queries.

## Reproducibility

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_hybrid_benchmark.py" -v
.\.venv\Scripts\python.exe -m cloud_demo.hybrid_benchmark run --output "reports/rag_benchmark/phase17_2"
```

Expected files:

```text
reports/rag_benchmark/phase17_2/
  hybrid_summary.json
  hybrid_results.csv
  hybrid_results.jsonl
  hybrid_report.md
```

The 19 automated tests run without installing FastEmbed or calling hosted Qwen; they inject a tiny fake embedder to test isolation, deterministic fusion, input validation, and report creation. **Only the CLI benchmark using real FastEmbed** yields meaningful retrieval scores.

## Research limitations

- The small dataset was deliberately handcrafted; gold labels were not independently annotated.
- Each question has one designated relevant note. There are no graded relevance assessments or clinically established outcomes.
- No external held-out cohort is available; improvements on this dataset do not establish generalization.
- These experiments measure retrieval only: citation correctness and answer-level factual support require separate evaluation.
- Actual model download, memory use, API calls, Streamlit load, and clinical reasoning are out of scope.
- This project uses no real patient data and must never be used to guide clinical decisions.

## Deployment gate

Do **not** replace the public semantic retriever yet. First review `hybrid_report.md` and its per-query regressions. If RRF performs worse than semantic-only on the benchmark, investigate failure cases, and compare on an independent test set before deciding on deployment. Cloud deployment should be planned separately, preserving the Phase 16.1 evidence-scope and citation guards.
