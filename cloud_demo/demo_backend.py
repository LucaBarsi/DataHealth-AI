"""DataHealth AI: public, read-only demo backend.

Uses fictional fixtures and an ephemeral in-memory SQLite database. No local
Synthea, ChromaDB, or Ollama dependency. Document retrieval is lexical, NOT
semantic vector RAG. This module does not support actual patient data.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path
import json
import re
import sqlite3

STOPWORDS = frozenset({"the", "and", "for", "with", "most", "recent", "latest", "show", "what", "does", "about", "into", "from", "this", "that", "patient", "please", "summarize", "summary", "their", "clinical", "records"})
CITATION_PATTERN = re.compile(r"\[(SQL|DOC):([^\]\s]+)\]")
REFERENCE_LIKE_PATTERN = re.compile(r"\[(?:SQL|DOC):[^\]]*\]")


def load_fixtures(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("synthetic_only") is not True or not isinstance(data.get("patients"), list):
        raise ValueError("Only explicitly synthetic demo fixtures are accepted")
    patients = data["patients"]
    ids = [p["patient_id"] for p in patients]
    if len(ids) != len(set(ids)) or not ids or any(not str(i).startswith("DEMO-P") for i in ids):
        raise ValueError("Duplicate or non-demo patient identifiers")
    return data


def open_demo_database(data: dict) -> sqlite3.Connection:
    """Build private ephemeral tables from approved fixtures; use fixed SQL only."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript("""
        CREATE TABLE patients (patient_id TEXT PRIMARY KEY, full_name TEXT NOT NULL, gender TEXT, birth_date TEXT);
        CREATE TABLE observations (
            observation_id TEXT PRIMARY KEY, patient_id TEXT NOT NULL REFERENCES patients(patient_id),
            code TEXT NOT NULL, display TEXT NOT NULL, value REAL NOT NULL, unit TEXT NOT NULL,
            timestamp TEXT NOT NULL, quality_status TEXT NOT NULL);
        CREATE TABLE medications (
            request_id TEXT PRIMARY KEY, patient_id TEXT NOT NULL REFERENCES patients(patient_id),
            medication TEXT NOT NULL, status TEXT NOT NULL, authored_on TEXT NOT NULL);
        CREATE TABLE notes (
            document_id TEXT PRIMARY KEY, patient_id TEXT NOT NULL REFERENCES patients(patient_id),
            date TEXT NOT NULL, type TEXT NOT NULL, text TEXT NOT NULL);
    """)
    for p in data["patients"]:
        pid = p["patient_id"]
        conn.execute("INSERT INTO patients VALUES (?,?,?,?)", (pid, p["full_name"], p.get("gender"), p.get("birth_date")))
        conn.executemany("INSERT INTO observations VALUES (?,?,?,?,?,?,?,?)", [
            (o["observation_id"], pid, o["code"], o["display"], o["value"], o["unit"], o["timestamp"], o["quality_status"])
            for o in p.get("observations", [])
        ])
        conn.executemany("INSERT INTO medications VALUES (?,?,?,?,?)", [
            (m["request_id"], pid, m["medication"], m["status"], m["authored_on"])
            for m in p.get("medications", [])
        ])
        conn.executemany("INSERT INTO notes VALUES (?,?,?,?,?)", [
            (n["document_id"], pid, n["date"], n["type"], n["text"])
            for n in p.get("notes", [])
        ])
    conn.commit()
    conn.execute("PRAGMA query_only=ON")
    return conn


def _rows(conn: sqlite3.Connection, query: str, params: tuple = ()) -> list[dict]:
    return [dict(row) for row in conn.execute(query, params).fetchall()]


def list_patients(conn: sqlite3.Connection) -> list[dict]:
    return _rows(conn, "SELECT patient_id, full_name, gender, birth_date FROM patients ORDER BY patient_id")


def counts(conn: sqlite3.Connection) -> dict:
    return {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("patients", "observations", "medications", "notes")}


def series_for_patient(conn: sqlite3.Connection, patient_id: str, code: str, unit: str, include_flagged=False) -> list[dict]:
    """Never mix patients, code, units, or unreviewed flags by default."""
    return _rows(conn, """
        SELECT observation_id, code, display, timestamp, value, unit, quality_status
        FROM observations WHERE patient_id=? AND code=? AND unit=?
          AND (?=1 OR quality_status='PASS_STRUCTURAL_CHECKS')
        ORDER BY timestamp ASC, observation_id ASC
    """, (patient_id, code, unit, int(include_flagged)))


def measurement_options(conn: sqlite3.Connection, patient_id: str) -> list[dict]:
    return _rows(conn, """
        SELECT DISTINCT code, unit, display FROM observations WHERE patient_id=?
        ORDER BY display, unit, code
    """, (patient_id,))


def _tokens(text: str) -> set[str]:
    return {x for x in re.findall(r"[a-z]{3,}", text.lower()) if x not in STOPWORDS}


def route_question(question: str, mode: str = "auto") -> tuple[bool, bool, bool]:
    """Return (observations, notes, medications) for deterministic fixed retrieval."""
    if mode not in {"auto", "measurements", "notes", "combined"}:
        raise ValueError("Unsupported retrieval mode")
    if mode == "measurements":
        return True, False, False
    if mode == "notes":
        return False, True, False
    if mode == "combined":
        return True, True, True
    q = question.lower()
    has_note = any(word in q for word in ("note", "history", "document", "narrative"))
    has_med = any(word in q for word in ("medication", "prescription", "drug"))
    has_numeric = any(word in q for word in ("vital", "heart", "pulse", "respirat", "pressure", "glucose", "weight", "cholesterol", "laboratory", "measurement", "trend", "lab"))
    if not (has_note or has_med or has_numeric):
        return True, True, True
    return has_numeric, has_note, has_med


def retrieve_evidence(conn: sqlite3.Connection, patient_id: str, question: str, mode: str="auto", limit: int=6) -> dict:
    if not 1 <= limit <= 15:
        raise ValueError("Invalid evidence limit")
    patient = _rows(conn, "SELECT patient_id, full_name, gender, birth_date FROM patients WHERE patient_id=?", (patient_id,))
    if not patient:
        raise ValueError("Unknown synthetic demo patient")
    want_measurements, want_notes, want_medications = route_question(question, mode)
    obs = (_rows(conn, """SELECT observation_id, code, display, value, unit, timestamp, quality_status
                          FROM observations WHERE patient_id=? ORDER BY timestamp DESC, observation_id DESC LIMIT ?""",
                 (patient_id, limit)) if want_measurements else [])
    meds = (_rows(conn, """SELECT request_id, medication, status, authored_on
                           FROM medications WHERE patient_id=? ORDER BY authored_on DESC LIMIT ?""",
                  (patient_id, limit)) if want_medications else [])
    notes = []
    if want_notes:
        candidates = _rows(conn, "SELECT document_id, date, type, text FROM notes WHERE patient_id=? ORDER BY date DESC", (patient_id,))
        qterms = _tokens(question)
        scored = [(len(qterms & _tokens(n["text"])), n["date"], n) for n in candidates]
        notes = [n for _, _, n in sorted(scored, key=lambda x: (x[0], x[1]), reverse=True)[:2]]
    for r in obs:
        r["source_marker"] = f"[SQL:{r['observation_id']}]"
    for m in meds:
        m["source_marker"] = f"[SQL:{m['request_id']}]"
    for n in notes:
        n["source_marker"] = f"[DOC:{n['document_id']}#chunk:0]"
    return {"patient": patient[0], "question": question, "routing": {"mode": mode,
            "measurements": want_measurements, "notes": want_notes, "medications": want_medications},
            "observations": obs, "medications": meds, "notes": notes,
            "limitations": "Hand-authored fictional fixtures. Structural labels do not establish clinical validity. Lexical document matching is not vector RAG."}


def allowed_markers(evidence: dict) -> set[str]:
    return {row["source_marker"] for section in ("observations", "medications", "notes") for row in evidence.get(section, [])}


def citation_check(answer: str, evidence: dict) -> dict:
    """Exact marker check only, NEVER a factual-entailment evaluation."""
    used = set(REFERENCE_LIKE_PATTERN.findall(answer))
    allowed = allowed_markers(evidence)
    unknown = sorted(used - allowed)
    return {"valid": bool(used) and not unknown, "unknown": unknown, "used": sorted(used), "allowed": sorted(allowed)}


def evidence_only_answer(evidence: dict) -> str:
    """Deterministic response from scoped records; no generative model claim."""
    p = evidence["patient"]
    lines = [f"**Recorded evidence for {p['full_name']}** (illustrative fixtures):"]
    obs = evidence["observations"]
    meds = evidence["medications"]
    notes = evidence["notes"]
    if obs:
        lines += ["", "**Structured measurements (latest retrieved rows)**"]
        for r in obs:
            tag = " — flagged for review" if r["quality_status"] != "PASS_STRUCTURAL_CHECKS" else ""
            lines.append(f"- {r['display']}: {r['value']:g} {r['unit']} on {r['timestamp']}{tag} {r['source_marker']}")
    if evidence["routing"]["medications"]:
        lines += ["", "**Structured medication requests**"]
        lines += ([f"- {m['medication']} — status: {m['status']} ({m['authored_on']}) {m['source_marker']}" for m in meds]
                  if meds else ["- No medication requests were retrieved from this demo dataset; this is not proof of no medication use."])
    if notes:
        lines += ["", "**Document excerpts**"]
        lines += [f"- **{n['type']}** ({n['date']}): {n['text']} {n['source_marker']}" for n in notes]
    if not obs and not meds and not notes:
        lines += ["", "No eligible evidence was found for this question in the selected demo scope."]
    lines += ["", "*Evidence-only preview — not generated by Qwen. Source IDs have not been clinically validated.*"]
    return "\n".join(lines)
