# DataHealth AI — Phase 16.1

**Evidence Scope & Cross-Query Consistency**

This incremental patch fixes a specific failure found in the Phase 16 public Qwen evaluation: the LLM asserted that no condition was recorded even though the condition category had not been queried (and `DEMO-C001` exists in the demonstration dataset).

## Install

Copy files from this archive into your existing `datahealth_ai_starter` project, preserving their paths:

- Replace `cloud_demo/remote_inference.py`
- Replace `cloud_demo/streamlit_app.py`
- Replace `cloud_demo/evaluate_cloud.py`
- Add `cloud_demo/scope_validation.py`
- Add `tests/test_cloud_scope_consistency.py`
- Add `docs/evidence_scope_consistency.md`
- Add `README_PHASE16_1.md` in the project root

**Do not replace** `cloud_demo/demo_backend.py`, `cloud_demo/sample_records.json`, `cloud_demo/usage_controls.py`, `Clinical_Assistant.py`, or the local data layer. Keep the six suggested questions and all Streamlit secrets unchanged.

## Test without API usage

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_cloud_scope_consistency.py" -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_cloud*.py" -v
.\.venv\Scripts\python.exe -m cloud_demo.evaluate_cloud --output "reports/cloud_evaluation/phase16_1_offline"
```

Expected for the new suite: **15 tests, OK**. The local packaging verification passed **70 cloud tests** across the previous releases plus this patch. Your complete project may have additional tests.

## Publish after reviewing changes

```powershell
git add cloud_demo/remote_inference.py cloud_demo/streamlit_app.py cloud_demo/evaluate_cloud.py cloud_demo/scope_validation.py tests/test_cloud_scope_consistency.py docs/evidence_scope_consistency.md README_PHASE16_1.md
git diff --cached --check
git diff --cached --name-only
git commit -m "Guard cloud answers against out-of-scope absence claims"
git push
```

Confirm the result on `https://datahealth-ai-demo.streamlit.app/`. Test **Recorded Conditions** and **Compare Vitals & Notes** with `DEMO-P001`. A valid answer must not claim there are no conditions based on a question that did not query them. If the model does, the displayed result falls back to the deterministic evidence-only view with code `EVIDENCE_SCOPE_VIOLATION`.

See `docs/evidence_scope_consistency.md` for the exact scope rules and known limitations.
