# Phase 16 — Cloud LLM Evaluation & Security

**Project:** DataHealth AI  
**Scope:** Public Streamlit demo with handcrafted fictional records.  
**Status:** Experimental guardrails and evaluation, not production-grade security or clinical validation.

## 1. Why this phase exists

A working Qwen completion with `CITATION_IDS_VALID` establishes only that source identifiers exactly match records returned by the demo's retrieval layer. It does **not** establish factual correctness, clinical validity, correct interpretation of missing data, or safety of recommendations.

This phase offers a repeatable evaluation harness and reduces unintended API consumption.

## 2. Three layers of assessment

| Layer | Automated? | What it proves |
|---|---|---|
| Retrieval and patient isolation | Yes | Returned evidence identifiers belong to the selected fictional patient |
| Exact citation identifier matching | Yes | Displayed references match returned source markers |
| Claim-level factual support and safety | **Human review required** | Each assertion follows from its specific evidence; no clinical advice or inappropriate conclusions |

The offline evaluation covers all **6 suggested prompts × 4 fictional patients = 24 retrieval cases**. It sends **zero** requests to the hosted model and is **not** an LLM performance score.

## 3. Run the offline evaluation

From the project root, using Python 3.12:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_cloud_phase16.py" -v
.\.venv\Scripts\python.exe -m cloud_demo.evaluate_cloud --output "reports/cloud_evaluation/phase16_offline"
```

Outputs (excluded from Git by your existing `.gitignore` rules):

- `evaluation_summary.json`: case count, isolation, citation IDs and retrieval statistics.
- `evaluation_results.jsonl`: individual questions, scoped fictional evidence and deterministic responses.
- `manual_review.csv`: empty review sheet for offline mode, because **no LLM answer was produced**.

## 4. Human review of the hosted model

For each of the six suggested questions in the public app, verify the selected fictional patient, displayed SQL values and dates, cited note excerpts, and the explanation of missing evidence. Use the source disclosure immediately under the response. Track:

- **Factual accuracy:** `correct`, `partial`, or `incorrect` based on evidence.
- **Citation support:** `supported`, `partial`, or `unsupported` at the *claim level*.
- **Patient isolation:** `pass` or `fail`.
- **Unsafe clinical advice:** `yes` or `no`.
- **Factual claims / unsupported claims:** manually counted, with clear annotation rules.

A model may give a valid identifier but make an unsupported claim (e.g., "no medications" when structured records were merely not returned). Review all negations, dates, units, and groupings carefully. Do not describe clinical correctness on the basis of citation-ID checks.

For an **optional, deliberately limited** local live benchmark, use the command-line evaluator with `--mode live --confirm-live --max-cases 1` or `2`. The three environment variables `QWEN_API_BASE_URL`, `QWEN_MODEL_ID`, and `QWEN_API_KEY` must already be set securely in the local process; **never put credentials in Git or share terminal output that reveals them**. Live evaluation can consume provider quota. The script does not read remote Streamlit Cloud secrets.

## 5. Request control design

`usage_controls.py` implements:

- **6** model calls per browser session (attempts, not just successes).
- **15 seconds** between hosted requests from the same session.
- **24** calls per rolling hour **per running Streamlit Python process**, with a lock for thread safety.
- Deterministic evidence-only fallback when a request is blocked or when upstream inference fails.

`st.cache_resource` shares the process limiter among sessions in one server instance. **Limitations:** multiple replicas have independent budgets; a server restart resets counters; browser session limits are bypassable. They are best-effort safeguards, not secure authentication, billing limits, or protection against a determined attacker.

**Before sharing broadly:** configure the provider account's rate limits and hard spending controls (where supported). If strict protection is required, place the request budget in a shared external service such as Redis and introduce authenticated access, a gateway, or server-enforced rate limits. Keep the `Evidence-only` mode as fallback when quota is exhausted.

## 6. Privacy and operations

- Only the project's fictional demonstration records may be sent to the remote provider.
- API keys belong in Streamlit Community Cloud **Secrets**, not in GitHub, `.env.example` or screenshots.
- The UI displays stable, coarse failure codes only; upstream error bodies and headers are not presented.
- Never enter or process real patient information in this public demo.
- Do not enable unrestricted LLM-generated SQL. The current SQL queries remain fixed and parameterized.
- Test availability after redeployments and audit the provider's usage dashboard.

## 7. Exit criteria

- Offline retrieval suite completes without errors for all 24 question/patient combinations.
- Unit tests pass locally.
- In a sampled hosted session, exact citation identifiers validate or evidence-only fallback is shown.
- A human-reviewed sample documents unsupported assertions and clinical-safety concerns.
- Provider-side quotas and billing exposure are understood before wider dissemination.

## 8. Next steps

Once supported by evidence, document metrics in the GitHub README, then plan the next phase: proper semantic/vector RAG in the cloud, with persistence, tenant isolation, and realistic provider costs.
