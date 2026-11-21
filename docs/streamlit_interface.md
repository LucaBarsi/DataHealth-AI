# Phase 9 — Local Streamlit Interface

## Objective
Expose the existing local, patient-scoped SQL + ChromaDB + Qwen 3.5 4B workflow through an interactive browser interface without replacing earlier pipelines.

## Architecture

- **UI:** `app.py` using Streamlit chat, patient selector, retrieval controls, source inspection.
- **Backend adapter:** `src/ui_backend.py` handles read-only patient selection, session changes and the existing Phase 7/8.1 calls.
- **SQL retrieval:** `src.hybrid_assistant` uses allowlisted parameterized queries against the Gold SQLite database.
- **RAG retrieval:** ChromaDB indexed from eligible synthetic documents and filtered by selected patient ID.
- **Generation:** `src.reliable_assistant.generate_reliable_answer` calls local Qwen 3.5 4B and validates exact citation IDs. If the model cannot produce valid IDs, it fails closed with an evidence-only display.

## Controls and limitations

1. **Synthetic only.** The sample Synthea names and records are fictitious; do not upload actual health records.
2. **Localhost only.** Launch with `--server.address 127.0.0.1`. Do not expose the app to public networks or deploy it to shared hosting.
3. **Patient selection is not authentication.** Switching patients is allowed for testing because all records are synthetic; a real deployment would require access control, auditing, encryption and legal compliance.
4. **No arbitrary SQL.** The LLM cannot issue SQL queries; the application selects existing allowlisted read-only retrieval functions.
5. **Citation validity is not factual correctness.** A matching source ID does not prove a claim is supported. We retain the Phase 8.1 manual-review findings and do not call this system clinically validated.
6. **Patient isolation in chat.** Switching the selected synthetic patient clears local conversation state.
7. **No automatic data writes.** The UI does not modify Bronze, Silver, Gold or ChromaDB files.
8. **No live device stream.** Kafka, Spark, cloud infrastructure and Power BI remain planned architecture extensions, not capabilities of this Streamlit prototype.

## Local smoke-test checklist

- The application opens only on `http://127.0.0.1:8501`.
- The 112 synthetic patient names appear in the selector.
- Changing the selected patient clears the visible conversation.
- `SQL`, `RAG`, `Hybrid` and `Auto` routing can be selected.
- An answer displays source markers and the `CITATION_IDS_VALID` / `EVIDENCE_ONLY_FALLBACK` / `NO_ELIGIBLE_EVIDENCE` status.
- Empty or unavailable evidence does not cause the app to invent a patient conclusion.
- No real-world clinical claims or deployment readiness is asserted.

## Next work

Evaluate the interactive workflow with multiple synthetic patients and adversarial prompts; improve claim-to-citation grounding; prepare operational monitoring and Power BI metrics; subsequently extend the local architecture with Kafka and Spark demonstrations.
