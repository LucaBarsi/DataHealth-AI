# Phase 16.1 — Evidence Scope & Cross-Query Consistency

## Problem

During the public Cloud LLM evaluation, the fictional patient `DEMO-P001` had a condition entry, `DEMO-C001`, returned by the **Recorded Conditions** question. A different question, **Compare Vitals & Notes**, retrieved observations and the latest note but did **not** query conditions. The generated answer then asserted that no conditions were recorded. The citation ID validator passed because its citations existed, even though the absence claim was out of scope.

**Retrieval did not happen** is not equivalent to **the records do not exist**.

## Fix

1. `retrieval_scope()` exposes, for each of observations, conditions, medications and notes, whether the category was queried and how many records were returned.
2. The hosted Qwen prompt now includes a structured scope disclosure. It explicitly forbids interpreting unqueried or limited categories as proof of absence.
3. `negative_claim_check()` adds a conservative post-generation heuristic for unsupported absence claims; it runs **in addition to** exact citation validation. Failed checks produce the existing deterministic evidence-only answer and `EVIDENCE_SCOPE_VIOLATION`.
4. The **Inspect retrieved sources** panel distinguishes **Not queried for this question** from **Queried, but no matching records were retrieved**.
5. Both the Streamlit interface and offline/live evaluation module enforce the same negative-claim check.
6. Cross-query regression tests verify that `DEMO-C001` exists in the fictional condition query while `Compare Vitals & Notes` may not infer its absence.

## Correct interpretation examples

| Scenario | Acceptable wording | Unacceptable wording |
|---|---|---|
| Conditions not queried | "The condition category was not searched for this question." | "The patient has no conditions." |
| Medication query returned no rows | "No medication requests were retrieved in the selected scope." | "The patient has never taken medication." |
| Notes queried | "The retrieved note reports no new complaints [DOC:...]." | "No conditions are recorded anywhere." |
| Limited rows | "These are the most recent retrieved observations." | "No other observations exist." |

## Run the regression suite

From the project root:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_cloud_scope_consistency.py" -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_cloud*.py" -v
.\.venv\Scripts\python.exe -m cloud_demo.evaluate_cloud --output "reports/cloud_evaluation/phase16_1_offline"
```

All these commands use the handcrafted fictional data and **do not call the hosted model**. The final command produces offline evidence/retrieval reports only, not a factual-accuracy score for Qwen.

## Deployment

The new file `cloud_demo/scope_validation.py` must accompany the updated `cloud_demo/remote_inference.py`, `cloud_demo/streamlit_app.py`, and `cloud_demo/evaluate_cloud.py`.

Secrets remain in Streamlit app settings. **Do not commit credentials, local `.env`, SQLite, ChromaDB or local patient exports.**

## Limits

- The detector is a **heuristic**: it can miss rephrased absence claims or conservatively reject some legitimate prose.
- This check is **not** clinical validation, natural-language entailment, cross-record adjudication, diagnosis verification or a hallucination-rate measurement.
- A known marker only confirms that the identifier belongs to retrieved evidence. It does **not** prove a claim is supported by that source.
- The `complete_history_verified` field is intentionally `false`; retrieval uses selected subsets and result limits.
- Patient-scoped source isolation, bounded public use and provider-side quotas remain separate safeguards.
- The cloud demo uses lexical note retrieval, not a production-ready vector RAG system.

A later evaluation should compare six questions on `DEMO-P001` before and after this patch, then include all four fictional patients. Any hosted test consumes part of the provider's allowance.
