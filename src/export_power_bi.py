"""Export aggregate-only Gold SQLite indicators for Power BI Desktop.

DataHealth AI educational prototype. Only verified synthetic data may be used.
No patient identifiers, names, dates of birth or clinical document bodies are exported.
"""
from __future__ import annotations

import argparse
import csv
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3


REQUIRED_COLUMNS = {
    "patients": {"patient_id"},
    "encounters": {"encounter_id", "patient_id", "start_time_utc"},
    "observation_events": {"observation_id", "category"},
    "observation_values": {"observation_id", "component_index", "measurement_code", "measurement_display", "unit_code", "quality_status", "quality_flags"},
    "conditions": {"condition_id"},
    "diagnostic_reports": {"report_id"},
    "medication_requests": {"medication_request_id"},
    "clinical_documents": {"document_id"},
}


def safe_cell(value):
    """Prevent formula execution if exported text is opened in a spreadsheet."""
    if value is None:
        return ""
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def write_csv(path: Path, headers: tuple[str, ...], rows: list[tuple]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        for row in rows:
            writer.writerow([safe_cell(v) for v in row])


def assert_schema(conn: sqlite3.Connection):
    for name, columns in REQUIRED_COLUMNS.items():
        got = {r[1] for r in conn.execute(f"PRAGMA table_info({name})")}
        if missing := columns - got:
            raise ValueError(f"Gold Layer schema mismatch in '{name}': missing {sorted(missing)}")


def monthly_series(raw_rows):
    """Fill missing calendar months with zero counts for honest time-series plots."""
    if not raw_rows:
        return []
    by_month = {str(month): (int(events), int(patients)) for month, events, patients in raw_rows}
    start = min(by_month)
    end = max(by_month)
    y, m = map(int, start.split("-"))
    ey, em = map(int, end.split("-"))
    output = []
    while (y, m) <= (ey, em):
        key = f"{y:04d}-{m:02d}"
        encounters, patients = by_month.get(key, (0, 0))
        output.append((f"{key}-01", y, m, encounters, patients))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return output


def export_aggregates(database: Path, output: Path) -> dict:
    database = Path(database)
    output = Path(output)
    if not database.is_file():
        raise FileNotFoundError(f"Gold Layer database not found: {database}")
    # Read-only URI prevents sqlite3.connect() from silently creating an empty DB.
    uri = database.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as conn:
        assert_schema(conn)
        monthly_raw = conn.execute("""
            SELECT substr(start_time_utc, 1, 7) AS month,
                   COUNT(*) AS encounter_count,
                   COUNT(DISTINCT patient_id) AS monthly_unique_patients
            FROM encounters
            WHERE start_time_utc IS NOT NULL AND start_time_utc != ''
              AND substr(start_time_utc, 6, 2) BETWEEN '01' AND '12'
            GROUP BY substr(start_time_utc, 1, 7)
            ORDER BY month
        """).fetchall()
        monthly_rows = monthly_series(monthly_raw)
        obs_categories = conn.execute("""
            SELECT COALESCE(NULLIF(trim(e.category),''), '(unspecified)') AS category,
                   COUNT(DISTINCT e.observation_id) AS observation_events,
                   COUNT(v.observation_id) AS observation_value_rows
            FROM observation_events AS e
            LEFT JOIN observation_values AS v ON v.observation_id = e.observation_id
            GROUP BY 1 ORDER BY observation_value_rows DESC, category
        """).fetchall()
        measurement_freq = conn.execute("""
            SELECT COALESCE(NULLIF(trim(measurement_code),''), '(unspecified)') AS measurement_code,
                   COALESCE(NULLIF(trim(measurement_display),''), '(unspecified)') AS measurement,
                   COALESCE(NULLIF(trim(unit_code),''), '(unspecified)') AS unit_code,
                   COUNT(*) AS value_rows,
                   SUM(CASE WHEN COALESCE(quality_status,'') != 'PASS_STRUCTURAL_CHECKS'
                                OR COALESCE(trim(quality_flags),'') != ''
                            THEN 1 ELSE 0 END) AS flagged_rows
            FROM observation_values GROUP BY 1,2,3
            ORDER BY value_rows DESC, measurement_code, unit_code
        """).fetchall()
        quality_status = conn.execute("""
            SELECT COALESCE(NULLIF(trim(quality_status),''), '(unspecified)') AS quality_status,
                   COUNT(*) AS value_rows,
                   SUM(CASE WHEN COALESCE(quality_status,'') != 'PASS_STRUCTURAL_CHECKS'
                                OR COALESCE(trim(quality_flags),'') != ''
                            THEN 1 ELSE 0 END) AS flagged_rows
            FROM observation_values GROUP BY 1 ORDER BY value_rows DESC
        """).fetchall()
        table_counts = {
            "patients_total": "patients",
            "encounters_total": "encounters",
            "observation_events_total": "observation_events",
            "observation_values_total": "observation_values",
            "conditions_total": "conditions",
            "diagnostic_reports_total": "diagnostic_reports",
            "medication_requests_total": "medication_requests",
            "clinical_documents_total": "clinical_documents",
        }
        overview = {k: int(conn.execute(f"SELECT COUNT(*) FROM {v}").fetchone()[0]) for k,v in table_counts.items()}
        overview["flagged_observation_values"] = int(conn.execute("""
            SELECT COUNT(*) FROM observation_values
            WHERE COALESCE(quality_status,'') != 'PASS_STRUCTURAL_CHECKS'
               OR COALESCE(trim(quality_flags),'') != ''
        """).fetchone()[0])
        overview["undated_encounters"] = int(conn.execute("""
            SELECT COUNT(*) FROM encounters
            WHERE start_time_utc IS NULL OR start_time_utc = ''
        """).fetchone()[0])
    output.mkdir(parents=True, exist_ok=True)
    files = {
        "monthly_encounters.csv": (("month_start", "year", "month_number", "encounter_count", "monthly_unique_patients"), monthly_rows),
        "observation_categories.csv": (("category", "observation_events", "observation_value_rows"), obs_categories),
        "measurement_frequency.csv": (("measurement_code", "measurement", "unit_code", "value_rows", "flagged_rows"), measurement_freq),
        "observation_quality.csv": (("quality_status", "value_rows", "flagged_rows"), quality_status),
        "overview.csv": (tuple(overview), [tuple(overview.values())]),
    }
    for file_name, (headers, rows) in files.items():
        write_csv(output/file_name, headers, rows)
    summary = {
        "project": "DataHealth AI",
        "phase": "Power BI — Aggregate Gold Layer Export",
        "synthetic_data_only": True,
        "identifiers_or_document_bodies_exported": False,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "files": {name: len(rows) for name, (_, rows) in files.items()},
        "counts": overview,
        "notes": [
            "Monthly distinct patient counts are NOT additive across months.",
            "Observation values are rows, not necessarily unique observation events.",
            "Quality flags indicate structural review needs, not clinical validation.",
            "The output must only be used with confirmed synthetic source data.",
        ],
    }
    (output/"export_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Export synthetic Gold Layer aggregates to CSVs for Power BI Desktop")
    parser.add_argument("--database", type=Path, default=Path("data/gold/datahealth.db"))
    parser.add_argument("--output", type=Path, default=Path("reports/power_bi/source_csv"))
    args = parser.parse_args()
    print(json.dumps(export_aggregates(args.database, args.output), indent=2))


if __name__ == "__main__":
    main()
