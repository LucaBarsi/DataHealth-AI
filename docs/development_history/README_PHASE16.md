# DataHealth AI — Phase 16

Cloud LLM Evaluation & Security | Fictional Data Only

This patch is **additive** to Phases 14/15 and preserves the public Streamlit demo UI, all six suggested questions, the dashboard, and the optional hosted Qwen API.

## Files to install

Copy the files in this archive into your existing `datahealth_ai_starter` project, retaining folder structure:

| File | Action |
|---|---|
| `cloud_demo/streamlit_app.py` | Replace the Phase 15 version **after backing it up** |
| `cloud_demo/usage_controls.py` | Add |
| `cloud_demo/evaluate_cloud.py` | Add |
| `cloud_demo/__init__.py` | Add if absent |
| `tests/test_cloud_phase16.py` | Add |
| `docs/cloud_llm_evaluation_security.md` | Add |
| `README_PHASE16.md` | Add to project root |

**Do not replace** `cloud_demo/remote_inference.py`, `cloud_demo/demo_backend.py`, `cloud_demo/sample_records.json`, `cloud_demo/suggested_questions.py`, or your local SQLite/ChromaDB/Ollama stack. These remain from Phases 14/15.

## Verify

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_cloud_phase16.py" -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_cloud_demo_phase14.py" -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_cloud_qwen_diagnostics.py" -v
.\.venv\Scripts\python.exe -m cloud_demo.evaluate_cloud --output "reports/cloud_evaluation/phase16_offline"
```

The **offline** evaluator checks 6 prompts × 4 fictional patients = 24 cases, with **zero hosted API calls**. It is not a factual accuracy benchmark.

## Local smoke test

```powershell
.\.venv\Scripts\python.exe -m streamlit run cloud_demo/streamlit_app.py --server.address 127.0.0.1
```

Try `Latest Vital Signs`, then try a second suggested question immediately. A minimum **15-second cooldown** between hosted model requests in one session should trigger evidence-only fallback with `SESSION_COOLDOWN` when called too soon. The request is not sent to the API. Browser sessions are limited to **6 requests**; a shared **process-local** budget allows at most **24 requests per rolling hour**.

The latter is **not an enforceable global spend ceiling across cloud replicas and restarts**. Confirm provider-side limits before broadly sharing the public demo.

## Publish to GitHub / Streamlit Cloud

After the tests and review:

```powershell
git add cloud_demo/streamlit_app.py cloud_demo/usage_controls.py cloud_demo/evaluate_cloud.py cloud_demo/__init__.py tests/test_cloud_phase16.py docs/cloud_llm_evaluation_security.md README_PHASE16.md
git diff --cached --check
git diff --cached --name-only
git commit -m "Add cloud evaluation and inference usage safeguards"
git push
```

The existing Streamlit entrypoint remains `cloud_demo/streamlit_app.py`. No new API key is needed, and the hosted model secrets should remain only in Streamlit Cloud settings.

## Honest limitations

`CITATION_IDS_VALID` is an exact identifier check, not factual validation. The new evaluation records retrieval correctness and leaves claim-level review to humans. Session and process rate limiting mitigate casual repeated calls but do not replace provider billing caps, authentication, or distributed rate limiting.
