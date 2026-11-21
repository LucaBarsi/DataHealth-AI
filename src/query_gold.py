"""Read-only, parameterized SQLite demo queries for synthetic DataHealth AI data."""
from __future__ import annotations

import argparse
from pathlib import Path
import sqlite3


def run_query(database: Path, command: str, patient_id: str | None = None, limit: int = 10):
    if not database.is_file():
        raise FileNotFoundError(f"Gold database not found: {database}")
    if not 1 <= limit <= 100:
        raise ValueError("Limit must be between 1 and 100")
    uri = database.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        if command == "list-patients":
            sql = "SELECT patient_id, first_name, last_name, full_name, gender, birth_date FROM patients ORDER BY patient_id LIMIT ?"
            params = (limit,)
        else:
            if not patient_id:
                raise ValueError("--patient-id is required for this command")
            if command == "patient-overview":
                sql = "SELECT * FROM v_patient_overview WHERE patient_id = ?"
                params = (patient_id,)
            elif command == "latest-observations":
                sql = """SELECT effective_datetime_utc, measurement_display, value_numeric,
                         value_text, unit_code, quality_status, quality_flags, observation_id
                         FROM v_observations WHERE patient_id = ?
                         ORDER BY effective_datetime_utc DESC, observation_id DESC LIMIT ?"""
                params = (patient_id, limit)
            elif command == "medications":
                sql = """SELECT authored_on_utc, medication_display, status, medication_request_id
                         FROM medication_requests WHERE patient_id = ?
                         ORDER BY authored_on_utc DESC LIMIT ?"""
                params = (patient_id, limit)
            elif command == "diagnostic-reports":
                sql = """SELECT effective_datetime_utc, display, status, report_id
                         FROM diagnostic_reports WHERE patient_id = ?
                         ORDER BY effective_datetime_utc DESC LIMIT ?"""
                params = (patient_id, limit)
            else:
                raise ValueError(f"Unsupported command: {command}")
        return [dict(row) for row in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Read-only DataHealth AI Gold Layer queries")
    parser.add_argument("--database", type=Path, default=Path("data/gold/datahealth.db"))
    parser.add_argument("command", choices=["list-patients", "patient-overview", "latest-observations", "medications", "diagnostic-reports"])
    parser.add_argument("--patient-id", help="Synthetic patient UUID from list-patients")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    rows = run_query(args.database, args.command, args.patient_id, args.limit)
    if not rows:
        print("No records found for the supplied query.")
    for row in rows:
        print(" | ".join(f"{key}={value}" for key, value in row.items()))


if __name__ == "__main__":
    main()
