# DataHealth AI — Phase 17

**Advanced RAG foundation: optional, patient-scoped semantic note retrieval**

This package **does not replace** the local Ollama + ChromaDB implementation. It extends the small, public Streamlit Cloud demonstration, using four wholly fictional sample patients and their existing synthetic notes.

## What is new

- Optional **FastEmbed ONNX** text embeddings (`BAAI/bge-small-en-v1.5`) for note/document selection, running locally on the Streamlit server CPU without an embedding API key.
- Cosine similarity with **strict patient isolation**. SQL, conditions, medication requests, source-marker validation, negative-claim checks, and hosted Qwen remain unchanged.
- A **small JSON vector index** that can be built locally and committed to GitHub. The index contains only fictional IDs, vectors, and a SHA-256 fingerprint. It is revalidated against fixture contents and the selected embedding model.
- A **keyword-search fallback** when the embedding model or index is unavailable.
- Explicit retrieval-mode labels in the evidence panel (`semantic_vector_cosine`, `lexical_keywords`, `not_queried`).
- Fifteen offline tests, including a two-note fake corpus used to demonstrate ranking and document/patient isolation.

## Honest limitations

- The **current public fixture has only one note per patient**. Real semantic retrieval gains cannot be measured on this tiny corpus; this phase sets up the functionality, not a validated improvement in search accuracy.
- The ONNX model downloads on first use unless already cached; Streamlit Community Cloud memory/network constraints may cause fallback. **Do not claim the model is running until the evidence panel reports `semantic_vector_cosine`.**
- This uses vector similarity over existing note documents, **not ChromaDB** in the public Cloud Demo. The full local RAG remains separate.
- The vector index can persist across Cloud restarts **only if you generate `cloud_demo/semantic_index.json` locally and commit it**. The model files themselves are downloaded/cached at runtime and are not in Git.
- Citation validity is not clinical or claim-level factual validation. All content is made-up; never use real patient data.

## Installation (PowerShell from `datahealth_ai_starter/`)

1. Back up `cloud_demo/demo_backend.py`, `cloud_demo/streamlit_app.py`, and `cloud_demo/requirements.txt`.
2. Copy the files from this ZIP to their relative paths. Do not replace `Clinical_Assistant.py` or any local Gold/ChromaDB data.
3. Install dependencies:

   ```powershell
   .\.venv\Scripts\python.exe -m pip install -r cloud_demo/requirements.txt
   ```

4. Run new tests, then regressions:

   ```powershell
   .\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_cloud_semantic_rag.py" -v
   .\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_cloud*.py" -v
   ```

5. Build the small index **once locally**. The first FastEmbed run may download an ONNX model. This does not call hosted Qwen or spend Mixlayer credits:

   ```powershell
   .\.venv\Scripts\python.exe -m cloud_demo.semantic_retrieval build --fixture cloud_demo/sample_records.json --output cloud_demo/semantic_index.json
   ```

6. Test semantic retrieval locally, opting in explicitly:

   ```powershell
   $env:SEMANTIC_RAG_ENABLED = "true"
   .\.venv\Scripts\python.exe -m streamlit run cloud_demo/streamlit_app.py --server.address 127.0.0.1 --server.port 8505
   ```

   Select fictional patient `DEMO-P001` and choose **Clinical History**. Open evidence and check for `semantic_vector_cosine`. If it says `lexical_keywords`, semantic retrieval was not active and the safe fallback was used.

7. After checking the staged content, push:

   ```powershell
   git add cloud_demo/semantic_retrieval.py cloud_demo/demo_backend.py cloud_demo/streamlit_app.py cloud_demo/requirements.txt cloud_demo/semantic_index.json tests/test_cloud_semantic_rag.py docs/phase17_semantic_rag.md README_PHASE17.md
   git diff --cached --check
   git diff --cached --name-only
   git commit -m "Add patient-scoped semantic note retrieval to cloud demo"
   git push
   ```

   If Git ignores `semantic_index.json`, check `.gitignore` and confirm the index contains only fictional IDs/vectors before deciding whether to add it explicitly. Do not use `git add -f` blindly.

8. In **Streamlit Community Cloud → App → Settings → Secrets**, append (without removing Qwen credentials):

   ```toml
   SEMANTIC_RAG_ENABLED = "true"
   ```

   Reboot the app if needed. Test **Clinical History** and **Compare Vitals & Notes**, then inspect the retrieval method. If the app becomes slow or hits resource limits, set the flag to `"false"` to restore lexical retrieval.

## What not to publish

Never commit `.env`, actual API keys, local patient data, a large local ChromaDB directory, downloaded ONNX model caches, or `.venv/`.

## Files in this ZIP

| File | Destination | Action |
|---|---|---|
| `semantic_retrieval.py` | `cloud_demo/` | Add |
| `demo_backend.py` | `cloud_demo/` | Replace |
| `streamlit_app.py` | `cloud_demo/` | Replace |
| `requirements.txt` | `cloud_demo/` | Replace |
| `test_cloud_semantic_rag.py` | `tests/` | Add |
| `phase17_semantic_rag.md` | `docs/` | Add |
| `README_PHASE17.md` | Project root | Add |

## Next: Phase 17.1

Enrich the fictional note corpus (multiple documents per patient), benchmark retrieval with labeled relevant documents (`Recall@k`, MRR), compare lexical vs semantic rankings, and extend synthetic FHIR-style document metadata without changing existing clinical claims.
