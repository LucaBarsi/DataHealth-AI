# Phase 17.1 — Retrieval Benchmark Methodology

## Goal and hypothesis

Quantitatively compare two evidence-selection strategies on the **same fictional note corpus** and the **same fixed gold query labels**. A plausible hypothesis is that semantic retrieval may match paraphrases with low exact word overlap; **the outcome is not presumed in advance**.

## Scope and provenance

- All entities and notes are explicitly fictional demonstration fixtures.
- Four patient identifiers remain `DEMO-P001` through `DEMO-P004`.
- There are 32 notes (the initial four, plus 28 hand-authored notes) and 28 queries, seven per patient.
- Each query labels one document as relevant. Some query wording intentionally differs from the language in the target note.
- The benchmark corpus is **separate** from `cloud_demo/sample_records.json` and is not loaded into the live Streamlit app.
- There is no human patient information, diagnoses, clinical validation, or medical decision support.

## Methods

### Lexical baseline

The lexical implementation reuses `cloud_demo.demo_backend._tokens`, ranks by the size of the set intersection with each note's tokens and resolves ties by more recent note date (mirroring the Phase 17 lexical fallback). All candidates are filtered to the requested patient **before ranking**. Benchmark questions do not request a latest-note override.

### Semantic candidate

The semantic implementation reuses `cloud_demo.semantic_retrieval` from Phase 17, including `BAAI/bge-small-en-v1.5`, index normalization, patient-scoped cosine retrieval, and exact document-ID matching. All embeddings are produced locally using FastEmbed/ONNX; no cloud embedding provider or Qwen inference is used. The benchmark index is built **in memory** from the independent test corpus, never overwriting the production `semantic_index.json`.

### Fairness controls

- Both methods rank the same note texts, for the same patient IDs and questions.
- Both return at most three IDs per query.
- All gold IDs are checked against the patient's own corpus before evaluation.
- The semantic model is warmed up once before timing query retrieval.
- Index construction time is tracked separately from the measured query latency.
- No semantic score is reported unless the actual embedding path is executed (except tests, which use a fake embedder for code correctness and are explicitly nonperformance tests).

## Metrics

Given a gold set \(G\) and the first \(k\) retrieved IDs \(R_k\):

- **Recall@k** = \(|G \cap R_k|/|G|\)
- **Reciprocal Rank@3** = \(1/r\) where \(r\) is the rank of the first gold ID among the top three, else 0
- **MRR@3** = mean reciprocal rank across all 28 questions
- **Median query latency (ms)** = median elapsed wall-clock time per query; machine-specific, excluding model initialization and index construction

The included gold labels have exactly one relevant document per question, which means Recall@k coincides with Hit@k for this experiment.

## Interpretation and limitations

1. This small benchmark is curated and may favor either method due to lexical vocabulary choices or paraphrasing style. It cannot establish broad superiority.
2. Relevance labels were authored alongside the notes instead of independently adjudicated.
3. One relevant document per question limits realism; real retrieval may involve multiple relevant chunks or partially relevant evidence.
4. Latency comparisons on 32 notes are not predictive of production-scale performance. FastEmbed downloads and startup are excluded from query timings.
5. Correct retrieval does **not** prove that a downstream LLM will produce factually supported claims; source-ID validation remains separate from entailment.
6. The public Streamlit demo, API budget, existing citations, and live documents are not modified by this benchmark.

## Reference lexical-only results

The supplied lexical implementation produced **Recall@1 0.7500**, **Recall@3 0.8571**, and **MRR@3 0.7857** in the development check. These figures describe only the hand-authored reference corpus. **No real semantic retrieval scores are claimed until the user runs the ONNX model.**

## Reproducible commands

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_retrieval_benchmark.py" -v
.\.venv\Scripts\python.exe -m cloud_demo.retrieval_benchmark run --mode lexical --output "reports/rag_benchmark/phase17_1_lexical"
.\.venv\Scripts\python.exe -m cloud_demo.retrieval_benchmark run --mode both --output "reports/rag_benchmark/phase17_1"
```

Output: summary JSON, per-question JSONL/CSV and Markdown report under the requested reports directory. Generated reports should remain outside the committed source tree unless intentionally reviewed and selected for publication.
