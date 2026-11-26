# DataHealth AI — Phase 9: Local Streamlit Interface

This phase adds a graphical interface to the existing **SQL + RAG + Qwen 3.5 4B** prototype. All project files and messages are in English. The application uses **SYNTHETIC Synthea data only** and is **not clinically validated**.

## Add the files (do not replace existing modules)

| New file | Destination in `datahealth_ai_starter` |
| --- | --- |
| `app.py` | Project root |
| `src/ui_backend.py` | `src/` |
| `tests/test_ui_backend.py` | `tests/` |
| `docs/streamlit_interface.md` | `docs/` |
| `requirements_phase9.txt` | Project root |
| `README_PHASE9.md` | Project root |

Earlier phases must remain in place, notably `src/hybrid_assistant.py`, `src/reliable_assistant.py`, `data/gold/datahealth.db`, and `data/vectorstore/chroma`.

## 1 — Install Streamlit in the Python 3.12 environment

From the root folder in VS Code PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements_phase9.txt
```

Verify:

```powershell
.\.venv\Scripts\python.exe -c "import streamlit; print('Streamlit installed:', streamlit.__version__)"
```

## 2 — Run the backend unit tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_ui_backend.py" -v
```

Expected: **7 tests** passing. They use an isolated temporary SQLite database and mock the LLM.

## 3 — Start the interface (local only)

Make sure Ollama is running and `ollama list` shows `qwen3.5:4b` and `nomic-embed-text`.

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1
```

Open `http://127.0.0.1:8501` in a browser if it does not open automatically. To stop the app, press **Ctrl+C** in that terminal.

## 4 — First functional test

1. Select **Abraham100 Hackett68** (the original Synthea sample patient).
2. Choose **Hybrid** mode and **Vitals** topic.
3. Ask: `Summarize the latest vital signs and the most recent clinical note, citing each source.`
4. Expand **Source details and quality flags** to verify SQL/RAG evidence and the citation-guard status.
5. Select a different synthetic patient and confirm the conversation resets.

## Notes

- Only local synthetic data. Never enter or upload real patient records.
- This is an interactive **demo**, not a production, authenticated clinical product.
- Do not commit `data/gold/*.db`, `data/vectorstore/`, raw synthetic bundles, or `.venv/` unless you have deliberately reviewed repository size and data-publication choices.
- Phase 8/8.1 evaluation baselines remain unchanged.
- If a previous Streamlit server is running, stop it before launching again.
- If Port 8501 is occupied, stop the existing server rather than exposing the app on another interface.
