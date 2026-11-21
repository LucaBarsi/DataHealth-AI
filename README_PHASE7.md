# DataHealth AI — Phase 7: Hybrid SQL + RAG

This package **adds** a single new Python module, tests and documentation to the existing `datahealth_ai_starter` repository. Do **not** replace the Phase 5 or Phase 6 modules.

## Requirements

- Python 3.12 virtual environment with Phase 6 requirements installed.
- Completed Gold SQLite database: `data/gold/datahealth.db`.
- Completed Phase 6 ChromaDB vector index: `data/vectorstore/chroma`.
- Local Ollama models `qwen3.5:4b` and `nomic-embed-text` already downloaded.
- `src/clinical_assistant.py` and `src/rag_assistant.py` from Phases 5 and 6, respectively.

## Copy files to the existing project

- `src/hybrid_assistant.py` -> `src/`
- `tests/test_hybrid_assistant.py` -> `tests/`
- `docs/hybrid_assistant_architecture.md` -> `docs/`
- `README_PHASE7.md` -> project root

## Test first

In VS Code PowerShell, from the project root:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_hybrid_assistant.py" -v
```

## First inspection (does not call the Qwen chat model)

```powershell
.\.venv\Scripts\python.exe -m src.hybrid_assistant inspect --patient-id "e34fa1e8-0cbc-0d22-89d4-6996de874bd8" --question "Compare medication prescriptions with the latest clinical note." --mode hybrid --topic medications --sql-limit 5 --top-k 2
```

This inspection **does** call the local embeddings model through Ollama for RAG retrieval. It outputs separate `sql_evidence` and `rag_evidence` arrays. Do not worry if a patient has no medication requests: an empty SQL section is a valid result.

## First hybrid answer

```powershell
.\.venv\Scripts\python.exe -m src.hybrid_assistant ask --patient-id "e34fa1e8-0cbc-0d22-89d4-6996de874bd8" --question "Compare medication prescriptions with the latest clinical note. Distinguish structured records from statements in the note." --mode hybrid --topic medications --sql-limit 5 --top-k 2
```

For a demonstration that is likely to retrieve both SQL observations and a clinical note:

```powershell
.\.venv\Scripts\python.exe -m src.hybrid_assistant ask --patient-id "e34fa1e8-0cbc-0d22-89d4-6996de874bd8" --question "Summarize the latest vital signs and the most recent clinical note, citing each source." --mode hybrid --topic vitals --sql-limit 5 --top-k 2
```

## Other examples

```powershell
# Structured observations only: no embedding request
.\.venv\Scripts\python.exe -m src.hybrid_assistant ask --patient-id "e34fa1e8-0cbc-0d22-89d4-6996de874bd8" --question "List the latest vital signs with units." --mode sql --topic vitals

# RAG notes only: no clinical SQL topics retrieved
.\.venv\Scripts\python.exe -m src.hybrid_assistant ask --patient-id "e34fa1e8-0cbc-0d22-89d4-6996de874bd8" --question "Summarize the most recent clinical note." --mode rag

# Automatic keyword-based routing (experimental)
.\.venv\Scripts\python.exe -m src.hybrid_assistant inspect --patient-id "e34fa1e8-0cbc-0d22-89d4-6996de874bd8" --question "Compare latest laboratory results and clinical notes."
```

## Troubleshooting

- `No module named src.hybrid_assistant`: ensure the file is in the project's existing `src` folder, not a second nested `src` directory.
- `No module named chromadb`: use `.venv\Scripts\python.exe` (Python 3.12) rather than a global Python 3.15 installation.
- `Vector index not found`: verify `data/vectorstore/chroma` was created by Phase 6.
- `Embedding model differs from stored index`: use `nomic-embed-text` or rebuild Phase 6 intentionally using a consistent model.
- `Cannot reach local Ollama`: start the Ollama Windows app, then run `ollama list`.
- `Unknown patient_id`: use an ID from the Gold `patients` table.

### Security note

Use **synthetic** data only. The prototype is not authorized for clinical use. Never commit database files containing real patient information, credentials, vector indexes with protected data or local virtual environments to GitHub.
