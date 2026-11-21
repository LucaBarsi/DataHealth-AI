# DataHealth AI — Phase 11: Evidence-Linked Charts in Clinical Assistant

This update adds interactive, read-only clinical measurement charts under SQL/hybrid answers while preserving the existing questions, Qwen, SQLite Gold Layer, ChromaDB, and the standalone Analytics Dashboard.

## Installation

1. Stop the active Streamlit process with **Ctrl+C** in its VS Code terminal.
2. Back up your current `Clinical_Assistant.py` as `Clinical_Assistant_before_phase11.py` (or outside the project, if you want to keep only one launchable script).
3. Copy the **new** `Clinical_Assistant.py` from this ZIP into the **project root**, replacing the current version.
4. Copy `src/contextual_charts.py` to `src/`.
5. Copy `tests/test_contextual_charts.py` to `tests/`.
6. Copy `docs/contextual_charts.md` to `docs/`.

The existing `src/analytics_backend.py` from Phase 10 and `plotly` from the Analytics Dashboard must already be installed. **Do not rebuild the SQLite database or vector index.** Do not replace `app.py`, `pages/1_Analytics_Dashboard.py`, or existing clinical assistant backend modules.

## Test

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_contextual_charts.py" -v
```

Expected: `Ran 11 tests` and `OK`.

## Run

```powershell
.\.venv\Scripts\python.exe -m streamlit run Clinical_Assistant.py --server.address 127.0.0.1
```

Open the local URL shown in the terminal, then choose a synthetic patient, retrieval mode `auto`, and **Latest vital signs** from Suggested Questions.

After the model answer, open **Explore measurements from this answer** (it expands automatically) and choose a measurement from the selector. Optionally show review-required records, and inspect the exact observation IDs. Switching patients clears the prior chat as before.

### What to expect

- `vitals`/`laboratory` SQL evidence: a selectable code-and-unit-specific historical graph, read from SQLite.
- RAG-only notes or medications without numeric evidence: no graph.
- A single historical point: a marker with an explicit one-record notice, not an inferred time trend.
- The full Analytics Dashboard remains a separate page accessible through the Streamlit navigation.

## Safety and provenance

This is an educational synthetic-data prototype; no patient authentication, clinical validity, diagnosis, treatment, real-time monitoring, forecasts, or access to real health records. The chart reads SQL directly; it is not an explanation automatically verified by the LLM. Never treat `PASS_STRUCTURAL_CHECKS` as clinical validation.
