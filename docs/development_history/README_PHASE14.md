# DataHealth AI — Phase 14: Six Suggested Questions + Optional Hosted Qwen

This incremental update extends **only the isolated public `cloud_demo/`**. It preserves `Clinical_Assistant.py`, the local Ollama model, Gold SQLite, ChromaDB, all local evaluation reports, and the existing public URL.

## What changed

- **Six clickable suggestions**: Latest Vital Signs, Laboratory Results, Recorded Conditions, Clinical History, Medication Comparison, and Compare Vitals & Notes.
- Suggested questions use **automatic retrieval**, even if the sidebar currently shows a manually selected mode. Typed questions continue to respect the sidebar selection.
- Fixed, parameterized, patient-scoped SQL separates laboratory and vital-sign measurements.
- Added a synthetic `conditions` table with **invented placeholder labels**. These are *not medical diagnoses* and are never drawn from real patient records.
- Source markers are attached to condition rows and included in exact-ID citation checks.
- Hosted Qwen (if enabled later) receives the new condition evidence and an explicit instruction not to infer clinical status.
- Without cloud credentials, the app continues to provide a useful, deterministic **Evidence-only** preview.
- Keeps the local demo stable, and no hosted model is promised as already configured.

## Install in VS Code

1. Stop the running Cloud Demo Streamlit process (`Ctrl+C` in its terminal). Do **not** delete the local `Clinical_Assistant.py` entrypoint.
2. Back up the `cloud_demo/` directory or commit your current state before replacing files.
3. Copy these files from the Phase 14 ZIP into `datahealth_ai_starter/`:

| File in ZIP | Destination | Action |
|---|---|---|
| `cloud_demo/streamlit_app.py` | `cloud_demo/streamlit_app.py` | Replace |
| `cloud_demo/demo_backend.py` | `cloud_demo/demo_backend.py` | Replace |
| `cloud_demo/remote_inference.py` | `cloud_demo/remote_inference.py` | Replace |
| `cloud_demo/sample_records.json` | `cloud_demo/sample_records.json` | Replace *illustrative fixtures only* |
| `cloud_demo/suggested_questions.py` | `cloud_demo/suggested_questions.py` | Add |
| `tests/test_cloud_demo_phase14.py` | `tests/test_cloud_demo_phase14.py` | Add |
| `docs/phase14_cloud_qwen_suggestions.md` | `docs/phase14_cloud_qwen_suggestions.md` | Add |
| `README_PHASE14.md` | project root | Add |

**Do not replace** `cloud_demo/requirements.txt`, `cloud_demo/secrets.example.toml`, your local SQL/vector data, or root `.streamlit/config.toml`.

## Verify the backend and run the demonstration

From project root (`datahealth_ai_starter`) in the VS Code PowerShell terminal:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_cloud_demo_backend.py" -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_cloud_demo_phase14.py" -v
.\.venv\Scripts\python.exe -m streamlit run cloud_demo/streamlit_app.py --server.address 127.0.0.1
```

**Expected:** 13 Phase 13 tests + 16 Phase 14 tests pass (29 total); the browser displays six suggestion buttons in a 3×2 layout. Open the page at the URL printed in the terminal. Click **Recorded Conditions** using demo patient `Alex100 Example01`; it should return the fictional entry with `[SQL:DEMO-C001]`. Try `Jordan400 Mock04` to confirm it explicitly reports the absence of condition entries instead of inventing one.

## Update the existing Streamlit Community Cloud deployment

After confirming the local demo and ensuring the new files contain **no real secrets**:

```powershell
git add cloud_demo/streamlit_app.py cloud_demo/demo_backend.py cloud_demo/remote_inference.py cloud_demo/sample_records.json cloud_demo/suggested_questions.py tests/test_cloud_demo_phase14.py docs/phase14_cloud_qwen_suggestions.md README_PHASE14.md
git diff --cached --check
git diff --cached --name-only
git commit -m "Add six cloud demo prompts and condition retrieval"
git push
```

The existing app (`https://datahealth-ai-demo.streamlit.app/`) should rebuild from branch `main` after this GitHub push. Confirm the six prompts in a private browser window. If it fails, check **Manage app → Logs** in Streamlit Community Cloud. Do not paste API keys into logs or screenshots.

## Hosted Qwen — **not activated** by this update

The optional model connector supports an HTTPS OpenAI-compatible `POST /chat/completions` endpoint. It is **disabled** until the repository owner independently selects a provider that actually hosts a compatible Qwen model, reviews provider pricing and usage limits, and supplies valid credentials in **Streamlit Community Cloud → App settings → Secrets**.

Expected secrets keys (replace placeholder *values* when ready; DO NOT commit actual values):

```toml
QWEN_API_BASE_URL = "https://your-verified-provider.example/v1"
QWEN_MODEL_ID = "your-provider-specific-qwen-model-id"
QWEN_API_KEY = "YOUR-PRIVATE-KEY"
```

The application checks that all three values exist and that the model ID contains `qwen`. Validating the string does **not** prove that the provider supports that model: confirm the exact API model identifier and whether the endpoint is available **before enabling**. Model access can incur charges.

The model receives **only the selected invented demo patient's** question and evidence, never actual clinical records. Responses with missing or unknown citation IDs are replaced with deterministic evidence-only content. Exact citation IDs **do not** establish factual correctness, and the app must never be used for medical decisions.

A simple per-browser-session limit is not a security boundary. Before enabling third-party inference on a public app, configure **provider-side quotas, maximum cost controls, and rate limits**; review terms, data retention and cost. Public users can create new browser sessions and bypass in-app counters.

## Important limitations

- The public dataset is four explicitly invented patients; it is **not** the local 112-patient Synthea sample.
- Note retrieval in the cloud is **lexical matching, not ChromaDB vector RAG**. SQL uses an in-memory database built from approved fixtures.
- The new condition labels are fictional placeholders. Lack of a condition or prescription in the fixtures is not a clinical negative finding.
- The local pipeline still contains Qwen 3.5 4B through Ollama, FHIR Bronze/Silver/Gold transformations, RAG/ChromaDB and a larger analytics dashboard. They are not automatically deployed to the cloud.
- No model-quality, security, cost or uptime guarantee is implied by unit tests.

## Technical reference

See `docs/phase14_cloud_qwen_suggestions.md` for routing, test coverage, and the next actions for hosted inference.
