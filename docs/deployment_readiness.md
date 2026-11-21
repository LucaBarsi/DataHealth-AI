# Deployment Readiness — DataHealth AI

## 1. Current verified scope

DataHealth AI is a **local, educational synthetic-data prototype**. Its stack includes:

- **FHIR/Synthea** for synthetic clinical source records.
- **Python** processing and Bronze/Silver/Gold-inspired data layers.
- **SQLite** for pre-defined, patient-scoped, read-only analytical queries.
- **ChromaDB** and `nomic-embed-text` for semantic retrieval of selected current synthetic documents.
- **Qwen 3.5 4B via local Ollama** for responses generated from SQL and/or RAG evidence.
- **Streamlit + Plotly** for the Clinical Assistant and Analytics Dashboard.
- A citation-ID validator and a limited, manually reviewed evaluation suite.

The architecture does **not** implement full FHIR clinical conformity, real-patient authorization, production security, or medical decision support. Seven stages of quality controls and model evaluations do not establish medical validity.

## 2. System boundaries and data ownership

| Component | Current dependency | Can it simply be pushed to GitHub? |
|---|---|---|
| Application Python source and tests | Source tree | Yes, after audit |
| Documentation, SQL templates, CSS | Source tree | Yes, after audit |
| `data/raw` and `data/silver` | Large generated/local data | No; regenerate from Synthea |
| `data/gold/datahealth.db` | Local binary SQLite | No, exclude from initial code repository |
| `data/vectorstore/chroma` | Local ChromaDB index | No, rebuild in deployment environment |
| Ollama (`localhost:11434`) | Local background service and model files | No, cannot be reached from Community Cloud |
| `.venv`, logs, experiment outputs | Local artifacts | No, exclude |
| `.env`, `.streamlit/secrets.toml` | Potential credentials | Never publish |

Consider uploading a deliberately small, verified synthetic sample to a **separate demo data artifact** later, with explicit provenance and permission review. Synthetic status does not remove security or license considerations.

## 3. Suggested deployment tracks

**Track A — Public code portfolio (Phase 12):** Publish reviewed source code, tests, architecture notes, screenshots and reproducible setup instructions. Local demo remains functional on the developer workstation. GitHub itself does not expose a running chat app.

**Track B — Hosted lightweight showcase:** Host a dashboard that loads a small, explicitly packaged synthetic **read-only** summary dataset. The LLM features must either be disabled with a clear label or backed by a hosted model and data service. Do not silently replace unavailable real retrieval with fabricated data.

**Track C — Full hosted hybrid assistant:** Keep a Streamlit frontend, add a protected backend/service for patient-scoped SQL retrieval, a supported persistent vector store, a remote model endpoint, secrets, rate limiting, resource monitoring, and a privacy/security review. AWS/Azure can support this architecture, but cost and operational scope are higher.

**Recommended:** finish Track A before deciding between Track B and Track C.

## 4. Hosted API keys and secrets

An API key is a **credential**, not the mechanism that publishes a website. If the future hosted model provider uses one, store it in deployment secrets/secure environment variables. Do not put tokens in `.py` files, README examples, Git commits, or browser-facing code.

For Streamlit Community Cloud, configure deployment secrets in the app's advanced settings; local secrets files are not committed. Environment variables configured in `.env.example` are documentation only until the application actually reads them.

Never expose local Ollama via an unauthenticated public port. Users must not be allowed to supply arbitrary SQL or arbitrary patient identifiers in a multi-tenant deployment without authorization.

## 5. Reproducibility checklist

1. Use Python 3.12 and a fresh virtual environment.
2. Install local requirements and verify version compatibility.
3. Obtain the permitted synthetic Synthea FHIR R4 sample independently.
4. Re-run the existing source audit, FHIR transform, Silver and Gold scripts.
5. Rebuild ChromaDB from selected current synthetic documents with the embedding model.
6. Run automated tests and document known non-blocking clinical metadata issues.
7. Start local Ollama separately and verify `qwen3.5:4b` and `nomic-embed-text` availability.
8. Start Streamlit with `Clinical_Assistant.py`.

Avoid claiming the complete application works publicly until an independent deployment run passes end-to-end checks.

## 6. Objective gates before public launch

- [ ] Git repository contains source code only; no secrets/data binaries.
- [ ] All dependency and license constraints reviewed.
- [ ] Synthetic data provenance recorded.
- [ ] Public mode gracefully handles unavailable model/data services.
- [ ] Test questions include no-evidence, cross-patient isolation, citation validity and safety cases.
- [ ] Remote backend and storage are accessible only through authenticated/authorized interfaces when appropriate.
- [ ] Request limits and operating cost caps established.
- [ ] Privacy notice explains that the content is synthetic and not medical advice.
- [ ] Source citation IDs are not claimed to be clinical evidence validation.
- [ ] Hosting logs, failures and cost monitoring are in place.

## 7. Reference documentation

- Streamlit Community Cloud deployments: https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy
- Streamlit dependencies: https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/app-dependencies
- Streamlit secrets: https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management
- GitHub sensitive data guidance: https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository
