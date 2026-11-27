"""DataHealth AI Phase 9: Streamlit-independent, patient-scoped UI adapter.

This adapter reuses Phase 7/8.1 retrieval and guarded generation; it does not
modify source data or let the language model choose SQL statements.
SYNTHETIC records only. Not for real clinical use.
"""
from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Any, Callable, MutableMapping

from . import hybrid_assistant, reliable_assistant

DEFAULT_DATABASE = Path("data/gold/datahealth.db")
DEFAULT_INDEX = Path("data/vectorstore/chroma")


def list_synthetic_patients(database: Path = DEFAULT_DATABASE, limit: int = 500) -> list[dict[str, Any]]:
    """List patients using a read-only, parameterized SQLite query."""
    if not 1 <= limit <= 1000:
        raise ValueError("Patient list limit must be within 1..1000")
    database = Path(database)
    if not database.is_file():
        raise FileNotFoundError(f"Gold SQLite database not found: {database}")
    connection = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only = ON")
        return [dict(row) for row in connection.execute(
            "SELECT patient_id, full_name, gender, birth_date "
            "FROM patients ORDER BY full_name, patient_id LIMIT ?", (limit,)
        ).fetchall()]
    finally:
        connection.close()


def sync_patient_session(state: MutableMapping[str, Any], patient_id: str) -> bool:
    """Clear previous patient conversation on a selection change."""
    if not patient_id:
        raise ValueError("A patient must be selected")
    if state.get("active_patient_id") != patient_id:
        state["active_patient_id"] = patient_id
        state["chat_messages"] = []
        return True
    state.setdefault("chat_messages", [])
    return False


def ask_synthetic_patient(
    *,
    database: Path,
    index_dir: Path,
    patient_id: str,
    question: str,
    mode: str = "auto",
    topic: str | None = None,
    sql_limit: int = 5,
    top_k: int = 2,
    max_retries: int = 1,
    answer_generator: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    allow_rag: bool = True,
) -> dict[str, Any]:
    """Retrieve scoped evidence and return citation-guarded generation."""
    if not question or not question.strip():
        raise ValueError("Question cannot be empty")
    if len(question) > 1500:
        raise ValueError("Question cannot exceed 1,500 characters")
    if mode not in hybrid_assistant.MODES:
        raise ValueError("Unsupported retrieval mode")
    if topic is not None and topic not in hybrid_assistant.SQL_TOPICS:
        raise ValueError("Unsupported SQL topic")
    if not Path(database).is_file():
        raise FileNotFoundError("Gold database is missing")
    if mode in ("rag", "hybrid") and not Path(index_dir).exists():
        raise FileNotFoundError("ChromaDB index is missing")
    # The hosted SQL pilot has no compatible remote nomic-embed-text endpoint.
    # Block routes requiring document embeddings BEFORE retrieval or generation.
    route = hybrid_assistant.route_question(question.strip(), mode=mode, topic=topic)
    if not allow_rag and route["use_rag"]:
        raise ValueError(
            "Hosted RAG is not available until an embeddings service is "
            "configured. Select SQL retrieval and ask a structured-data question."
        )
    # The local default still supports SQL, RAG and hybrid Ollama retrieval.
    evidence = hybrid_assistant.retrieve_hybrid(
        Path(database), Path(index_dir), patient_id, question.strip(),
        mode=mode, topic=topic, sql_limit=sql_limit, top_k=top_k,
    )
    if evidence.get("patient", {}).get("patient_id") != patient_id:
        raise RuntimeError("Patient scope mismatch: response was blocked")
    response = (
        answer_generator(evidence)
        if answer_generator is not None
        else reliable_assistant.generate_reliable_answer(
            evidence, max_retries=max_retries
        )
    )
    return {"evidence": evidence, "response": response}


def source_summary(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten source metadata for a compact, verifiable UI table."""
    items: list[dict[str, Any]] = []
    for item in evidence.get("sql_evidence", []):
        row = item.get("record", {})
        items.append({
            "source": item["source_marker"],
            "type": "SQL",
            "record": row.get("measurement_display") or row.get("medication_display")
                      or row.get("display") or item.get("topic") or "Record",
            "date": row.get("effective_datetime_utc") or row.get("authored_on_utc")
                    or row.get("onset_datetime_utc") or "",
            "quality": row.get("quality_status") or "Not specified",
        })
    for item in evidence.get("rag_evidence", []):
        items.append({
            "source": item["source_marker"],
            "type": "RAG",
            "record": item.get("document_type") or "Clinical document",
            "date": item.get("document_date") or "",
            "quality": "Document candidate (not clinically validated)",
        })
    return items
