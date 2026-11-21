"""Create a reproducible SQLite Gold Layer from conservative Synthea Silver CSVs.

This educational demo uses synthetic records only. It does not validate clinical
semantics, authorize document access, or permit free-form LLM SQL execution.
"""
from __future__ import annotations

import argparse
import csv
from collections import Counter
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import sqlite3

SOURCE_TABLES = (
    "patients", "encounters", "observations", "conditions",
    "diagnostic_reports", "diagnostic_report_results",
    "medication_requests", "clinical_documents",
)

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE patients (
    patient_id TEXT PRIMARY KEY,
    first_name TEXT, last_name TEXT, full_name TEXT,
    gender TEXT, birth_date TEXT, source_file TEXT
);
CREATE TABLE encounters (
    encounter_id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL REFERENCES patients(patient_id),
    status TEXT, class_code TEXT, type_code TEXT, type_display TEXT,
    start_time_utc TEXT, end_time_utc TEXT, source_file TEXT
);
CREATE TABLE observation_events (
    observation_id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL REFERENCES patients(patient_id),
    encounter_id TEXT REFERENCES encounters(encounter_id),
    status TEXT, category TEXT, code_system TEXT, code TEXT, display TEXT,
    effective_datetime_utc TEXT, effective_datetime_source TEXT,
    issued_datetime_utc TEXT, source_file TEXT
);
CREATE TABLE observation_values (
    observation_id TEXT NOT NULL REFERENCES observation_events(observation_id),
    component_index INTEGER NOT NULL,
    measurement_code_system TEXT, measurement_code TEXT, measurement_display TEXT,
    value_type TEXT, value_numeric REAL, value_numeric_source TEXT,
    value_text TEXT, unit_code TEXT, unit_display TEXT, unit_system TEXT,
    quality_status TEXT, quality_flags TEXT,
    PRIMARY KEY(observation_id, component_index)
);
CREATE TABLE conditions (
    condition_id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL REFERENCES patients(patient_id),
    encounter_id TEXT REFERENCES encounters(encounter_id),
    code_system TEXT, code TEXT, display TEXT, clinical_status TEXT,
    verification_status TEXT, onset_datetime_utc TEXT, source_file TEXT
);
CREATE TABLE diagnostic_reports (
    report_id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL REFERENCES patients(patient_id),
    encounter_id TEXT REFERENCES encounters(encounter_id),
    status TEXT, code_system TEXT, code TEXT, display TEXT,
    effective_datetime_utc TEXT, source_file TEXT
);
CREATE TABLE diagnostic_report_results (
    report_id TEXT NOT NULL REFERENCES diagnostic_reports(report_id),
    observation_id TEXT NOT NULL REFERENCES observation_events(observation_id),
    PRIMARY KEY(report_id, observation_id)
);
CREATE TABLE medication_requests (
    medication_request_id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL REFERENCES patients(patient_id),
    encounter_id TEXT REFERENCES encounters(encounter_id),
    status TEXT, intent TEXT, medication_code TEXT, medication_display TEXT,
    authored_on_utc TEXT, source_file TEXT
);
-- Clinical document text remains in the Silver Layer. Gold contains metadata only.
CREATE TABLE clinical_documents (
    document_id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL REFERENCES patients(patient_id),
    status TEXT, document_type TEXT, document_date_utc TEXT,
    rag_candidate_status TEXT, rag_review_flags TEXT, source_file TEXT
);
CREATE INDEX idx_encounters_patient_time ON encounters(patient_id, start_time_utc);
CREATE INDEX idx_observations_patient_time ON observation_events(patient_id, effective_datetime_utc);
CREATE INDEX idx_observations_code ON observation_events(code);
CREATE INDEX idx_measurements_code ON observation_values(measurement_code);
CREATE INDEX idx_reports_patient ON diagnostic_reports(patient_id);
CREATE INDEX idx_conditions_patient ON conditions(patient_id);
CREATE INDEX idx_medications_patient ON medication_requests(patient_id);
CREATE INDEX idx_documents_patient ON clinical_documents(patient_id);
CREATE VIEW v_observations AS
SELECT e.patient_id, e.observation_id, v.component_index, e.encounter_id,
       e.effective_datetime_utc, e.status, e.category,
       e.code AS panel_code, e.display AS panel_display,
       v.measurement_code, v.measurement_display,
       v.value_type, v.value_numeric, v.value_numeric_source,
       v.value_text, v.unit_code, v.unit_display,
       v.quality_status, v.quality_flags, e.source_file
FROM observation_events e JOIN observation_values v USING(observation_id);
CREATE VIEW v_patient_overview AS
SELECT p.patient_id, p.first_name, p.last_name, p.full_name, p.gender, p.birth_date,
    (SELECT COUNT(*) FROM encounters e WHERE e.patient_id=p.patient_id) AS encounter_count,
    (SELECT COUNT(*) FROM observation_events o WHERE o.patient_id=p.patient_id) AS observation_event_count,
    (SELECT COUNT(*) FROM conditions c WHERE c.patient_id=p.patient_id) AS condition_count,
    (SELECT COUNT(*) FROM diagnostic_reports d WHERE d.patient_id=p.patient_id) AS diagnostic_report_count,
    (SELECT COUNT(*) FROM medication_requests m WHERE m.patient_id=p.patient_id) AS medication_request_count
FROM patients p;
CREATE VIEW v_rag_preliminary_document_metadata AS
SELECT document_id, patient_id, document_type, document_date_utc, source_file
FROM clinical_documents
WHERE status='current' AND rag_candidate_status='PRELIMINARY_ONLY_NOT_AUTHORIZED'
  AND (rag_review_flags IS NULL OR rag_review_flags='');
"""


def read_rows(folder: Path, table: str) -> list[dict[str, str]]:
    path = folder / f"{table}.csv"
    if not path.is_file():
        raise FileNotFoundError(f"Missing required Silver input: {path}")
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames:
            raise ValueError(f"Missing CSV header: {path}")
        return list(reader)


def nullable(value: str | None) -> str | None:
    return value if value not in (None, "") else None


def required(row: dict[str, str], field: str, table: str) -> str:
    value = nullable(row.get(field))
    if value is None:
        raise ValueError(f"Missing required field '{field}' in Silver table '{table}'")
    return value


def utc_time(text: str | None, counters: Counter) -> str | None:
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            counters["timezone_missing_datetime_rows"] += 1
            return None  # Never infer a time zone.
        return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds")
    except ValueError:
        counters["invalid_datetime_rows"] += 1
        return None


def numeric(text: str | None, counters: Counter) -> float | None:
    if text in (None, ""):
        return None
    try:
        result = float(text)
        if not math.isfinite(result):
            counters["invalid_numeric_rows"] += 1
            return None
        return result
    except ValueError:
        counters["invalid_numeric_rows"] += 1
        return None


def insert(conn: sqlite3.Connection, table: str, columns: tuple[str, ...], rows: list[tuple]) -> None:
    marks = ", ".join("?" for _ in columns)
    fields = ", ".join(columns)
    conn.executemany(f"INSERT INTO {table} ({fields}) VALUES ({marks})", rows)


def create_gold(input_dir: Path, database: Path, reports: Path) -> dict:
    if not input_dir.is_dir():
        raise NotADirectoryError(f"Silver input not found: {input_dir}")
    all_rows = {name: read_rows(input_dir, name) for name in SOURCE_TABLES}
    database.parent.mkdir(parents=True, exist_ok=True)
    if database.suffix.lower() not in (".db", ".sqlite", ".sqlite3"):
        raise ValueError("Use a .db, .sqlite, or .sqlite3 output file")
    temp_db = database.with_name(database.name + ".building")
    if temp_db.exists():
        temp_db.unlink()
    counts: Counter = Counter()
    conn = sqlite3.connect(temp_db)
    try:
        conn.executescript(SCHEMA)
        insert(conn, "patients", ("patient_id", "first_name", "last_name", "full_name", "gender", "birth_date", "source_file"), [
            (required(r, "patient_id", "patients"), nullable(r.get("first_name")), nullable(r.get("last_name")),
             nullable(r.get("full_name")), nullable(r.get("gender")), nullable(r.get("birth_date")), nullable(r.get("source_file")))
            for r in all_rows["patients"]
        ])
        insert(conn, "encounters", ("encounter_id", "patient_id", "status", "class_code", "type_code", "type_display", "start_time_utc", "end_time_utc", "source_file"), [
            (required(r,"encounter_id","encounters"), required(r,"patient_id","encounters"), nullable(r.get("status")), nullable(r.get("class_code")), nullable(r.get("type_code")), nullable(r.get("type_display")), utc_time(r.get("start_time"),counts), utc_time(r.get("end_time"),counts), nullable(r.get("source_file")))
            for r in all_rows["encounters"]
        ])
        events = {}
        values = []
        for r in all_rows["observations"]:
            oid = required(r, "observation_id", "observations")
            event = (oid, required(r,"patient_id","observations"), nullable(r.get("encounter_id")), nullable(r.get("status")), nullable(r.get("category")), nullable(r.get("observation_code_system")), nullable(r.get("observation_code")), nullable(r.get("observation_display")), utc_time(r.get("effective_datetime"), counts), nullable(r.get("effective_datetime")), utc_time(r.get("issued_datetime"), counts), nullable(r.get("source_file")))
            if oid in events:
                if events[oid] != event:
                    raise ValueError(f"Conflicting event-level metadata across observation components: {oid}")
            else:
                events[oid] = event
            component_index = int(r.get("component_index") or 0)
            is_component = component_index != 0
            qstatus = nullable(r.get("quality_status"))
            if qstatus is None:
                raise ValueError("Silver observations must contain 'quality_status'; rebuild the Silver Layer first")
            if qstatus == "REVIEW_REQUIRED":
                counts["flagged_observation_rows"] += 1
            vals = (oid, component_index,
                    nullable(r.get("component_code_system") if is_component else r.get("observation_code_system")),
                    nullable(r.get("component_code") if is_component else r.get("observation_code")),
                    nullable(r.get("component_display") if is_component else r.get("observation_display")),
                    nullable(r.get("value_type")), numeric(r.get("value_numeric"),counts), nullable(r.get("value_numeric")),
                    nullable(r.get("value_text")), nullable(r.get("unit_code")), nullable(r.get("value_unit")),
                    nullable(r.get("unit_system")), qstatus, nullable(r.get("quality_flags")))
            values.append(vals)
        insert(conn, "observation_events", ("observation_id", "patient_id", "encounter_id", "status", "category", "code_system", "code", "display", "effective_datetime_utc", "effective_datetime_source", "issued_datetime_utc", "source_file"), list(events.values()))
        insert(conn, "observation_values", ("observation_id", "component_index", "measurement_code_system", "measurement_code", "measurement_display", "value_type", "value_numeric", "value_numeric_source", "value_text", "unit_code", "unit_display", "unit_system", "quality_status", "quality_flags"), values)
        insert(conn, "conditions", ("condition_id", "patient_id", "encounter_id", "code_system", "code", "display", "clinical_status", "verification_status", "onset_datetime_utc", "source_file"), [
            (required(r,"condition_id","conditions"), required(r,"patient_id","conditions"), nullable(r.get("encounter_id")), nullable(r.get("code_system")), nullable(r.get("code")), nullable(r.get("display")), nullable(r.get("clinical_status")), nullable(r.get("verification_status")), utc_time(r.get("onset_datetime"), counts), nullable(r.get("source_file")))
            for r in all_rows["conditions"]
        ])
        insert(conn, "diagnostic_reports", ("report_id", "patient_id", "encounter_id", "status", "code_system", "code", "display", "effective_datetime_utc", "source_file"), [
            (required(r,"report_id","diagnostic_reports"), required(r,"patient_id","diagnostic_reports"), nullable(r.get("encounter_id")), nullable(r.get("status")), nullable(r.get("code_system")), nullable(r.get("code")), nullable(r.get("display")), utc_time(r.get("effective_datetime"), counts), nullable(r.get("source_file")))
            for r in all_rows["diagnostic_reports"]
        ])
        insert(conn, "diagnostic_report_results", ("report_id", "observation_id"), [
            (required(r,"report_id","diagnostic_report_results"), required(r,"observation_id","diagnostic_report_results"))
            for r in all_rows["diagnostic_report_results"]
        ])
        insert(conn, "medication_requests", ("medication_request_id", "patient_id", "encounter_id", "status", "intent", "medication_code", "medication_display", "authored_on_utc", "source_file"), [
            (required(r,"medication_request_id","medication_requests"), required(r,"patient_id","medication_requests"), nullable(r.get("encounter_id")), nullable(r.get("status")), nullable(r.get("intent")), nullable(r.get("medication_code")), nullable(r.get("medication_display")), utc_time(r.get("authored_on"), counts), nullable(r.get("source_file")))
            for r in all_rows["medication_requests"]
        ])
        insert(conn, "clinical_documents", ("document_id", "patient_id", "status", "document_type", "document_date_utc", "rag_candidate_status", "rag_review_flags", "source_file"), [
            (required(r,"document_id","clinical_documents"), required(r,"patient_id","clinical_documents"), nullable(r.get("status")), nullable(r.get("document_type")), utc_time(r.get("document_date"), counts), nullable(r.get("rag_candidate_status")), nullable(r.get("rag_review_flags")), nullable(r.get("source_file")))
            for r in all_rows["clinical_documents"]
        ])
        fk_issues = conn.execute("PRAGMA foreign_key_check").fetchall()
        if fk_issues:
            raise ValueError(f"Foreign key validation failed: {fk_issues[:5]}")
        table_counts = {name: conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0] for name in ("patients", "encounters", "observation_events", "observation_values", "conditions", "diagnostic_reports", "diagnostic_report_results", "medication_requests", "clinical_documents")}
        if table_counts["observation_values"] != len(all_rows["observations"]):
            raise AssertionError("Observation value rows not preserved")
        expected_counts = {t: len(rows) for t, rows in all_rows.items()}
        for table_name, n in expected_counts.items():
            target = "observation_values" if table_name == "observations" else table_name
            if table_counts[target] != n:
                raise AssertionError(f"Record count mismatch for {table_name}")
        candidate_count = conn.execute("SELECT COUNT(*) FROM v_rag_preliminary_document_metadata").fetchone()[0]
        named_patient_count = conn.execute("SELECT COUNT(*) FROM patients WHERE full_name IS NOT NULL AND TRIM(full_name) != ''").fetchone()[0]
        conn.commit()
        summary = {
            "project": "DataHealth AI",
            "phase": "Phase 4 — Gold Layer & SQLite",
            "source": str(input_dir), "database": str(database),
            "source_row_counts": expected_counts, "gold_table_counts": table_counts,
            "patients_with_full_name": named_patient_count,
            "flagged_observation_rows": counts["flagged_observation_rows"],
            "preliminary_rag_document_metadata_rows": candidate_count,
            "invalid_numeric_rows": counts["invalid_numeric_rows"],
            "invalid_datetime_rows": counts["invalid_datetime_rows"],
            "timezone_missing_datetime_rows": counts["timezone_missing_datetime_rows"],
            "foreign_key_violations": len(fk_issues),
            "note": "Synthetic data demo only; no clinical validity or access authorization is implied. Original Silver CSVs were not modified."
        }
    except Exception:
        conn.close()
        if temp_db.exists():
            temp_db.unlink()
        raise
    else:
        conn.close()
    os.replace(temp_db, database)
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "gold_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    report = [
        "# Gold Layer — SQLite Build Validation", "",
        "## Purpose", "",
        "Relational query layer for the Synthea-based DataHealth AI prototype. No clinical predictions or diagnoses are performed.", "",
        "## Gold row counts", "", "| Table | Rows |", "|---|---:|",
        *[f"| {key} | {value} |" for key, value in table_counts.items()],
        "", "## Data safeguards", "",
        f"- Foreign key violations: **{len(fk_issues)}**.",
        f"- Patients with a populated synthetic full name: **{named_patient_count}**.",
        f"- Observation value rows flagged for review: **{counts['flagged_observation_rows']}**.",
        f"- Preliminary document metadata candidates: **{candidate_count}**.",
        "- No automatic unit conversion or clinical recoding was performed.",
        "- Original timestamps and numeric values are retained in the Silver CSV files; Gold retains source numeric strings and original observation timestamps.",
        "- Gold clinical_documents contains metadata only, not document bodies.",
        "- Preliminary RAG candidate status does not imply access authorization or clinical validity.",
        "- The SQLite database is a local educational prototype, not a production multi-user EHR.",
    ]
    (reports / "gold_validation_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a SQLite Gold Layer from Synthea Silver CSV tables")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reports", type=Path, required=True)
    args = parser.parse_args()
    result = create_gold(args.input, args.output, args.reports)
    print("Gold Layer build completed.")
    for name, count in result["gold_table_counts"].items():
        print(f"{name}: {count}")
    print(f"Flagged observation rows preserved: {result['flagged_observation_rows']}")
    print(f"Foreign key violations: {result['foreign_key_violations']}")
    print(f"Report: {args.reports / 'gold_summary.json'}")


if __name__ == "__main__":
    main()
