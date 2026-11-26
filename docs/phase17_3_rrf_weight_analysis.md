# Phase 17.3 — Patient-Held-Out RRF Weight Analysis

## Objective

Examine why equal-weight Reciprocal Rank Fusion (RRF) lost relevance relative to the semantic retriever in Phase 17.2. Compare a small **predeclared** set of semantic weights while reducing, though not eliminating, leakage from tuning and evaluation on the same questions.

This is an **offline, hand-authored fictional retrieval benchmark**, not an evaluation of clinical correctness, treatment recommendations, or hosted Qwen responses.

## Design

The retrieval input is the Phase 17.1 collection: **4 fictional patients, 32 fictional notes, 28 questions**. Each query has hand-authored relevance labels.

Both lexical and semantic retrievers rank **all notes for the queried patient**. Their document rankings are fused with the same RRF implementation used in Phase 17.2:

\[
\operatorname{RRF}(d)=\frac{1}{60+r_L(d)}+\frac{w_S}{60+r_S(d)}
\]

- Lexical weight: **1.0**, fixed.
- Candidate semantic weights: **1.0, 1.5, 2.0, 3.0, 4.0** (declared in advance).
- `rrf_k`: **60**, fixed.
- Rank-based fusion, not blending cosine distances with lexical overlap scores.
- Candidate rankings are computed from full **patient-scoped** document lists.

## Patient-held-out evaluation

For each of the four patients:

1. Hold out **all 7 questions for that patient**.
2. Select the semantic weight using **only the other 21 questions**.
3. Selection uses training `MRR@3`, then training `Recall@1`, then training `Recall@3`. Exact ties favor the **smaller weight**.
4. Evaluate the selected weight on the held-out patient's 7 questions.
5. Aggregate the 28 held-out outcomes and compare against pure lexical, pure semantic, and equal-weight RRF.

The embedding model and document index are prepared once. The same complete, patient-isolated rankings are reused across candidates; this avoids downloading the model or running inference separately for every weight.

## Output files

Generated in `reports/rag_benchmark/phase17_3/`:

- `weight_analysis_summary.json`: aggregate metrics and selected weight per held-out patient.
- `weight_analysis_results.csv`: each question's relevance ID, top-1 IDs, and correctness by method.
- `weight_analysis_results.jsonl`: detailed document rankings and metrics.
- `weight_analysis_report.md`: comparison tables, query-level error analysis, and limitations.

## Interpretation rules

Do **not** claim a better model from an apparent advantage on this small dataset. The four patients share constructed topics; holding out patients does not provide external or clinical validation. The handcrafted labels also limit generalizability.

Keep **semantic retrieval** as the deployed default for now. Only consider hybrid deployment after a separate, preregistered dataset establishes a meaningful gain that does not reduce `Recall@3` or compromise patient isolation.

No changes are made to `cloud_demo/streamlit_app.py`, `sample_records.json`, `semantic_index.json`, API credentials, or the hosted service.

## Reproducibility

Run in the project root, in the existing Python 3.12 virtual environment:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_rrf_weight_analysis.py" -v
.\.venv\Scripts\python.exe -m cloud_demo.rrf_weight_analysis run --output "reports/rag_benchmark/phase17_3"
```

The real experiment uses locally installed FastEmbed / BGE. Unit tests use a deterministic **fake embedder** to verify behavior; their numerical retrieval scores must not be presented as real model performance. No Qwen API key or network inference is used.

## Handoff to Phase 18

Proceed to **Phase 18 — Machine Learning Integration regardless of the outcome**. Initial recommended ML experiment: forecasting **monthly synthetic encounter volume** from the Gold Layer using chronological train/validation/test splits and simple baselines before more complex models. Evaluate MAE, RMSE, and WAPE (when defined); include leakage checks and no clinical predictive claims.
