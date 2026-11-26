# DataHealth AI — Phase 15: Hosted Qwen Diagnostics

This targeted update improves reliability and observability for the public cloud demo. It does not modify the local Ollama/ChromaDB/SQLite implementation or the invented sample records.

## What changed

- Uses `reasoning_effort="none"` in Mixlayer-compatible Chat Completions requests, so the free Qwen model produces direct answers rather than spending the output budget on hidden reasoning.
- Raises the output budget to 900 tokens, with a 30-second HTTP timeout.
- Maintains source-marker validation and evidence-only fallback.
- Displays a **coarse, non-sensitive** fallback diagnostic code without exposing API keys, base URLs or provider response bodies.

## Mixlayer connection configuration

In Streamlit Community Cloud → App settings → Secrets:

```toml
QWEN_API_BASE_URL = "https://mixlayer.ai/v1"
QWEN_MODEL_ID = "qwen/qwen3.5-4b-free"
QWEN_API_KEY = "SET_PRIVATELY_IN_STREAMLIT_SECRETS"
```

`https://mixlayer.ai/v1` is the API base documented in Mixlayer's Quickstart. Do not paste the real key into local files, source control, screenshots or chat.

## Installation

Back up `cloud_demo/remote_inference.py` and `cloud_demo/streamlit_app.py`. Copy only these two files from the ZIP into your project's `cloud_demo/`, replacing the previous versions. Add `tests/test_cloud_qwen_diagnostics.py` and `docs/cloud_qwen_diagnostics.md`.

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_cloud_qwen_diagnostics.py" -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_cloud_demo_phase14.py" -v
```

When tests pass, check the staged files and push:

```powershell
git add cloud_demo/remote_inference.py cloud_demo/streamlit_app.py tests/test_cloud_qwen_diagnostics.py docs/cloud_qwen_diagnostics.md README_PHASE15.md
git diff --cached --check
git diff --cached --name-only
git commit -m "Improve hosted Qwen diagnostics and non-thinking inference"
git push
```

Streamlit Community Cloud should redeploy on changes to `main`. If necessary, reboot from the Streamlit app settings, then reload the application.

## Validation

Select a fictional patient and choose **Latest Vital Signs**. If the model returns valid cited content, the status should be `CITATION_IDS_VALID`. Otherwise, the application shows the deterministic evidence-only fallback **and a safe diagnostic**. Use that code to troubleshoot without sharing credentials.

| Diagnostic | Meaning |
| --- | --- |
| `AUTHENTICATION_FAILED` | The service rejected the API credential; review the key in Streamlit Secrets |
| `ACCESS_DENIED` | The account/model is not authorized |
| `ENDPOINT_OR_MODEL_NOT_FOUND` | The API base or model ID is wrong or unavailable |
| `RATE_LIMITED` | Provider quota or request limit reached |
| `NETWORK_OR_TIMEOUT` | Network problem or timeout |
| `EMPTY_MODEL_CONTENT` | Provider replied but returned no answer text |
| `UNSUPPORTED_RESPONSE_FORMAT` | Provider response differs from expected Chat Completions shape |
| `CITATION_CHECK_FAILED` | Model responded without an exact approved citation marker or invented a marker |

Even `CITATION_IDS_VALID` confirms only exact IDs; it does not guarantee factual correctness. This deployment uses fictional illustrative records and is not for clinical use.

## Security note

The session-level call cap is not a global rate limit. Before promoting a public demo with an API key, verify the provider's free-tier limits, disable any unexpected auto billing, monitor usage and consider server-side rate limiting/authentication.
