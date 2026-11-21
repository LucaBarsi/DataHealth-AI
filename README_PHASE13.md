# DataHealth AI — Phase 13: Local Mode + Cloud Demo Mode

## Purpose

Keep the production-like local educational prototype unchanged, while creating a **separate, lightweight public proof of concept** that can be deployed to Streamlit Community Cloud. This release is a *deployment preparation package*, not a deployed public service.

## Mode comparison

| Capability | Local Mode (unchanged) | Cloud Demo Mode (new) |
|---|---|---|
| Entrypoint | `Clinical_Assistant.py` | `cloud_demo/streamlit_app.py` |
| Data | 112 Synthea patients in local Gold SQLite | 4 hand-authored illustrative synthetic patients |
| SQL | Persistent local Gold SQLite | Read-only queries against ephemeral in-memory SQLite |
| Documents | ChromaDB vector RAG with local embeddings | Lexical lookup over small example notes; **not vector RAG** |
| LLM | Ollama `qwen3.5:4b` on the developer's PC | Evidence-only by default; optionally compatible hosted Qwen inference |
| Secrets | Local configuration | Streamlit managed secrets (never in source control) |
| Use case | Research/portfolio demo on localhost | Public lightweight UI preview with **fictional** fixtures |

The cloud demo does **not** access `data/gold/datahealth.db`, `data/vectorstore/chroma`, or the local Ollama server. It does not replace the local prototype. No patient data from the local Synthea export is copied into the cloud demo package.

## Installation — copy from this ZIP

Copy `cloud_demo/` into the **root of** your `datahealth_ai_starter/` project, alongside `Clinical_Assistant.py`. Copy `tests/test_cloud_demo_backend.py`, `docs/cloud_deployment_plan.md`, and `README_PHASE13.md` to their corresponding folders. Do not replace existing scripts or root `.streamlit/config.toml`.

### Run the cloud demo locally

From the project root in VS Code PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pip install -r cloud_demo/requirements.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_cloud_demo_backend.py" -v
.\.venv\Scripts\python.exe -m streamlit run cloud_demo/streamlit_app.py --server.address 127.0.0.1
```

Open the URL printed in the terminal. This lightweight version will display **4 illustrative demo patients**, not the 112-patient local database. Without secrets, it operates as `Evidence only`: deterministic answers with verifiable fictional row IDs and charts.

### Deploy to Streamlit Community Cloud

1. Review the new files for secrets and run the tests locally.
2. Stage only the new files, check them, then commit and push to `main`:

```powershell
git add cloud_demo/ tests/test_cloud_demo_backend.py docs/cloud_deployment_plan.md README_PHASE13.md
git diff --cached --check
git diff --cached --name-only
git commit -m "Add isolated Streamlit public cloud demo"
git push
```

3. Go to https://share.streamlit.io and connect GitHub if requested.
4. Choose GitHub repo `LucaBarsi/DataHealth-AI`, branch `main`, and **main file path**: `cloud_demo/streamlit_app.py`.
5. Streamlit Community Cloud finds `cloud_demo/requirements.txt` next to the entrypoint. You do not need to put the full local `requirements_local.txt` in the cloud app.
6. Deploy without secrets first and test that both tabs and the sample queries work.
7. Keep the app private/unlisted if your available visibility settings allow until you complete review; do not assume repository/app visibility is identical.

### Optional hosted Qwen — separate phase

When you choose a hosted inference provider that **actually offers the required Qwen model and API format**, configure three Streamlit Community Cloud app secrets (via app settings, NOT in Git):

```toml
QWEN_API_BASE_URL = "https://your-verified-provider.example/v1"
QWEN_MODEL_ID = "verified-qwen-model-id"
QWEN_API_KEY = "YOUR_REAL_SECRET_FROM_PROVIDER"
```

The demo expects an OpenAI-compatible **HTTPS** `/chat/completions` endpoint, a bearer key, and a model ID containing `qwen`. Endpoints/model availability, service cost, privacy policies, and rate limits must be verified with the chosen provider before enabling remote inference.

The code checks exact citation IDs but cannot automatically prove factual entailment or medical accuracy. It falls back to the deterministic evidence-only answer if remote inference fails or returns unknown/missing source IDs. It is NOT appropriate for real patient information.

**Never commit** `.streamlit/secrets.toml`, real API keys, `.env`, Synthea data, local SQLite, vector databases, model weights, or personal chat histories. Note that this package contains **no real secrets**; `secrets.example.toml` is illustrative only.

## Public demo limitations

- The cloud demo dataset is intentionally tiny and independently invented; its counts must not be compared with the original 112 patients.
- Vector semantic RAG, Kafka, Spark, Power BI, and cloud SQL infrastructure are **not implemented** in the cloud demo.
- The lexical note search is a functional placeholder only; it is labeled as such in the UI.
- The community hosting environment is not persistent storage for chat history or real records.
- Local chart trends are created from demo SQL rows with unit/code separation and explicit structural flags.
- Remote LLM access may cost money and needs authentication; the first deployment works without an API key.

## What success looks like

- Local `Clinical_Assistant.py` still runs normally.
- Cloud demo can run locally from its own entrypoint, using only its lightweight requirements.
- The GitHub repository contains the public demo source but does **not** contain local databases or API keys.
- A new hosted demo can run in **Evidence-only** mode even without a hosted Qwen provider.
