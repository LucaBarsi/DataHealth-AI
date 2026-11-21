"""Read-only analytics for the DataHealth AI synthetic SQLite Gold Layer.

All filters are bound SQL parameters. Measurement trends only compare identical
measurement codes AND unit codes. These are exploratory graphics, not clinical
interpretations, real-time monitoring or predictions.
"""
from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from datetime import date
from pathlib import Path
import sqlite3
from typing import Iterator

DEFAULT_DATABASE = Path("data/gold/datahealth.db")
OBSERVATION_CATEGORIES = ("All categories", "laboratory", "vital-signs", "survey", "other")


@contextmanager
def _db(database: Path) -> Iterator[sqlite3.Connection]:
    """Open one read-only SQLite connection, closed on every code path."""
    file_path = Path(database)
    if not file_path.is_file():
        raise FileNotFoundError(f"SQLite Gold Layer not found: {file_path}")
    connection = sqlite3.connect(file_path.resolve().as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only = ON")
        yield connection
    finally:
        connection.close()


def _dates(start_date: str | None, end_date: str | None) -> None:
    """Validate ISO date boundaries before passing them to SQL."""
    for value in (start_date, end_date):
        if value is not None:
            if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
                raise ValueError("Date boundaries must use YYYY-MM-DD")
    if start_date and end_date and start_date > end_date:
        raise ValueError("Start date cannot be after end date")


def _patient(connection: sqlite3.Connection, patient_id: str | None) -> None:
    if patient_id is not None:
        if not isinstance(patient_id, str) or not patient_id or len(patient_id) > 128:
            raise ValueError("Invalid patient ID")
        if not connection.execute("SELECT 1 FROM patients WHERE patient_id=?", (patient_id,)).fetchone():
            raise ValueError("Patient not found in the synthetic database")


def _observation_filter(
    patient_id: str | None, start_date: str | None, end_date: str | None,
    category: str = "All categories", event_alias: str = "e",
) -> tuple[str, tuple[str, ...]]:
    """Build SQL from fixed internal column identifiers, never from user SQL."""
    _dates(start_date, end_date)
    if category not in OBSERVATION_CATEGORIES:
        raise ValueError("Unknown observation category")
    clauses = ["1 = 1"]
    params: list[str] = []
    if patient_id is not None:
        clauses.append(f"{event_alias}.patient_id = ?")
        params.append(patient_id)
    if start_date is not None:
        clauses.append(f"substr({event_alias}.effective_datetime_utc, 1, 10) >= ?")
        params.append(start_date)
    if end_date is not None:
        clauses.append(f"substr({event_alias}.effective_datetime_utc, 1, 10) <= ?")
        params.append(end_date)
    if category != "All categories":
        if category == "other":
            clauses.append(f"coalesce({event_alias}.category,'') NOT IN ('laboratory','vital-signs','survey')")
        else:
            clauses.append(f"{event_alias}.category = ?")
            params.append(category)
    return " AND ".join(clauses), tuple(params)


def _dated_filter(
    table_alias: str, patient_id: str | None,
    date_column: str, start_date: str | None, end_date: str | None,
) -> tuple[str, tuple[str, ...]]:
    # Internal-only date_column values are defined at call sites below.
    _dates(start_date, end_date)
    clauses = ["1 = 1"]
    params: list[str] = []
    if patient_id is not None:
        clauses.append(f"{table_alias}.patient_id = ?")
        params.append(patient_id)
    if start_date is not None:
        clauses.append(f"substr({table_alias}.{date_column}, 1, 10) >= ?")
        params.append(start_date)
    if end_date is not None:
        clauses.append(f"substr({table_alias}.{date_column}, 1, 10) <= ?")
        params.append(end_date)
    return " AND ".join(clauses), tuple(params)


def list_patients(database: Path = DEFAULT_DATABASE) -> list[dict]:
    with _db(database) as conn:
        return [dict(r) for r in conn.execute(
            "SELECT patient_id, full_name, gender, birth_date "
            "FROM patients ORDER BY full_name COLLATE NOCASE, patient_id"
        )]


def observation_date_bounds(database: Path = DEFAULT_DATABASE) -> tuple[str | None, str | None]:
    with _db(database) as conn:
        row = conn.execute(
            "SELECT MIN(substr(effective_datetime_utc,1,10)) AS first_date, "
            "MAX(substr(effective_datetime_utc,1,10)) AS last_date "
            "FROM observation_events WHERE effective_datetime_utc IS NOT NULL"
        ).fetchone()
        return row["first_date"], row["last_date"]


def kpis(database: Path = DEFAULT_DATABASE, *, patient_id: str | None = None,
         start_date: str | None = None, end_date: str | None = None,
         category: str = "All categories") -> dict:
    with _db(database) as conn:
        _patient(conn, patient_id)
        where, params = _observation_filter(patient_id, start_date, end_date, category)
        row = conn.execute(f"""
            SELECT COUNT(DISTINCT e.observation_id) AS observation_events,
                   COUNT(*) AS observation_rows,
                   SUM(CASE WHEN v.quality_status='REVIEW_REQUIRED' THEN 1 ELSE 0 END) AS flagged_rows,
                   COUNT(DISTINCT e.patient_id) AS patients_with_observations
            FROM observation_events e
            JOIN observation_values v ON e.observation_id = v.observation_id
            WHERE {where}
        """, params).fetchone()
        encounter_filter, encounter_params = _dated_filter(
            "enc", patient_id, "start_time_utc", start_date, end_date)
        encounters = conn.execute(
            f"SELECT COUNT(*) FROM encounters enc WHERE {encounter_filter}", encounter_params
        ).fetchone()[0]
        population = conn.execute(
            "SELECT COUNT(*) FROM patients" if patient_id is None else
            "SELECT COUNT(*) FROM patients WHERE patient_id = ?",
            () if patient_id is None else (patient_id,)
        ).fetchone()[0]
        return {
            "population_patients": population,
            "patients_with_observations": row["patients_with_observations"],
            "observation_events": row["observation_events"],
            "observation_rows": row["observation_rows"],
            "flagged_rows": row["flagged_rows"] or 0,
            "encounters": encounters,
        }


def category_distribution(database: Path = DEFAULT_DATABASE, *, patient_id: str | None = None,
                          start_date: str | None = None, end_date: str | None = None,
                          category: str = "All categories") -> list[dict]:
    with _db(database) as conn:
        _patient(conn, patient_id)
        where, params = _observation_filter(patient_id, start_date, end_date, category)
        return [dict(r) for r in conn.execute(f"""
            SELECT COALESCE(e.category, 'uncategorized') AS category,
                   COUNT(*) AS observation_rows
            FROM observation_events e JOIN observation_values v USING(observation_id)
            WHERE {where}
            GROUP BY COALESCE(e.category, 'uncategorized')
            ORDER BY observation_rows DESC, category
        """, params)]


def observation_activity(database: Path = DEFAULT_DATABASE, *, patient_id: str | None = None,
                         start_date: str | None = None, end_date: str | None = None,
                         category: str = "All categories", granularity: str = "year") -> list[dict]:
    if granularity not in ("year", "month"):
        raise ValueError("granularity must be 'year' or 'month'")
    n = 4 if granularity == "year" else 7
    with _db(database) as conn:
        _patient(conn, patient_id)
        where, params = _observation_filter(patient_id, start_date, end_date, category)
        return [dict(r) for r in conn.execute(f"""
            SELECT substr(e.effective_datetime_utc,1,{n}) AS period,
                   COUNT(*) AS observation_rows
            FROM observation_events e JOIN observation_values v USING(observation_id)
            WHERE {where} AND e.effective_datetime_utc IS NOT NULL
            GROUP BY period ORDER BY period
        """, params)]


def latest_observations(database: Path = DEFAULT_DATABASE, *, patient_id: str | None = None,
                        start_date: str | None = None, end_date: str | None = None,
                        category: str = "All categories", limit: int = 100) -> list[dict]:
    if not 1 <= limit <= 500:
        raise ValueError("Row limit must be 1..500")
    with _db(database) as conn:
        _patient(conn, patient_id)
        where, params = _observation_filter(patient_id, start_date, end_date, category)
        return [dict(r) for r in conn.execute(f"""
            SELECT e.patient_id, e.observation_id, e.effective_datetime_utc,
                   e.category, v.measurement_code, v.measurement_display,
                   v.value_numeric, v.value_text, v.unit_code,
                   v.quality_status, v.quality_flags
            FROM observation_events e JOIN observation_values v USING(observation_id)
            WHERE {where}
            ORDER BY e.effective_datetime_utc DESC, e.observation_id DESC, v.component_index
            LIMIT ?
        """, (*params, limit))]


def measurement_options(database: Path, patient_id: str, *, start_date: str | None = None,
                        end_date: str | None = None,
                        category: str = "All categories") -> list[dict]:
    with _db(database) as conn:
        _patient(conn, patient_id)
        where, params = _observation_filter(patient_id, start_date, end_date, category)
        return [dict(r) for r in conn.execute(f"""
            SELECT v.measurement_code AS measurement_code,
                   COALESCE(v.measurement_display, v.measurement_code, 'Unnamed measurement') AS display,
                   COALESCE(v.unit_code, '') AS unit_code,
                   COUNT(*) AS count,
                   SUM(CASE WHEN v.quality_status='REVIEW_REQUIRED' THEN 1 ELSE 0 END) AS flagged_count
            FROM observation_events e JOIN observation_values v USING(observation_id)
            WHERE {where} AND v.value_numeric IS NOT NULL AND v.measurement_code IS NOT NULL
            GROUP BY v.measurement_code, v.measurement_display, COALESCE(v.unit_code,'')
            ORDER BY count DESC, display, v.measurement_code, unit_code
            LIMIT 150
        """, params)]


def measurement_series(database: Path, patient_id: str, measurement_code: str, unit_code: str,
                       *, start_date: str | None = None, end_date: str | None = None,
                       category: str = "All categories", include_flagged: bool = False,
                       limit: int = 750) -> dict:
    if not 1 <= limit <= 2000:
        raise ValueError("Series row limit must be 1..2000")
    if not measurement_code or len(measurement_code) > 128 or len(unit_code) > 128:
        raise ValueError("Invalid code or unit")
    with _db(database) as conn:
        _patient(conn, patient_id)
        where, params = _observation_filter(patient_id, start_date, end_date, category)
        approved = "" if include_flagged else " AND v.quality_status != 'REVIEW_REQUIRED'"
        records = [dict(r) for r in conn.execute(f"""
            SELECT e.patient_id, e.observation_id, e.effective_datetime_utc,
                   v.measurement_code, v.measurement_display,
                   v.unit_code, v.value_numeric, v.quality_status, v.quality_flags
            FROM observation_events e JOIN observation_values v USING(observation_id)
            WHERE {where} AND v.measurement_code = ?
              AND COALESCE(v.unit_code,'') = ? AND v.value_numeric IS NOT NULL
              AND e.effective_datetime_utc IS NOT NULL {approved}
            ORDER BY e.effective_datetime_utc DESC, e.observation_id DESC
            LIMIT ?
        """, (*params, measurement_code, unit_code, limit + 1))]
        truncated = len(records) > limit
        return {"rows": list(reversed(records[:limit])), "truncated": truncated}


def quality_summary(database: Path = DEFAULT_DATABASE, *, patient_id: str | None = None,
                    start_date: str | None = None, end_date: str | None = None,
                    category: str = "All categories") -> dict:
    with _db(database) as conn:
        _patient(conn, patient_id)
        where, params = _observation_filter(patient_id, start_date, end_date, category)
        rows = [dict(r) for r in conn.execute(f"""
            SELECT v.quality_status AS status, COALESCE(v.quality_flags,'') AS flags,
                   COUNT(*) AS count
            FROM observation_events e JOIN observation_values v USING(observation_id)
            WHERE {where}
            GROUP BY v.quality_status, v.quality_flags
        """, params)]
    status = Counter()
    flags = Counter()
    for row in rows:
        status[row["status"] or "UNSPECIFIED"] += row["count"]
        if row["status"] == "REVIEW_REQUIRED":
            for flag in (str(row["flags"]).split("|")):
                flags[flag or "UNSPECIFIED"] += row["count"]
    return {"status": dict(status), "flags": dict(flags), "total_rows": sum(status.values())}


def encounter_activity(database: Path = DEFAULT_DATABASE, *, patient_id: str | None = None,
                       start_date: str | None = None, end_date: str | None = None,
                       granularity: str = "year") -> list[dict]:
    if granularity not in ("year", "month"):
        raise ValueError("granularity must be 'year' or 'month'")
    n = 4 if granularity == "year" else 7
    with _db(database) as conn:
        _patient(conn, patient_id)
        where, params = _dated_filter("enc", patient_id, "start_time_utc", start_date, end_date)
        return [dict(r) for r in conn.execute(f"""
            SELECT substr(enc.start_time_utc,1,{n}) AS period, COUNT(*) AS encounters
            FROM encounters enc WHERE {where} AND enc.start_time_utc IS NOT NULL
            GROUP BY period ORDER BY period
        """, params)]


def clinical_document_status(database: Path = DEFAULT_DATABASE, *, patient_id: str | None = None,
                             start_date: str | None = None, end_date: str | None = None) -> list[dict]:
    with _db(database) as conn:
        _patient(conn, patient_id)
        where, params = _dated_filter("d", patient_id, "document_date_utc", start_date, end_date)
        return [dict(r) for r in conn.execute(f"""
            SELECT COALESCE(d.status,'not specified') AS status, COUNT(*) AS count
            FROM clinical_documents d WHERE {where}
            GROUP BY COALESCE(d.status,'not specified') ORDER BY count DESC, status
        """, params)]


def top_measurements(database: Path = DEFAULT_DATABASE, *, patient_id: str | None = None,
                     start_date: str | None = None, end_date: str | None = None,
                     category: str = "All categories", limit: int = 12) -> list[dict]:
    if not 1 <= limit <= 100:
        raise ValueError("Top measurement limit must be 1..100")
    with _db(database) as conn:
        _patient(conn, patient_id)
        where, params = _observation_filter(patient_id, start_date, end_date, category)
        return [dict(r) for r in conn.execute(f"""
            SELECT COALESCE(v.measurement_display,v.measurement_code,'Unnamed') AS display,
                   COALESCE(v.measurement_code,'') AS measurement_code,
                   COALESCE(v.unit_code,'') AS unit_code,
                   COUNT(*) AS count
            FROM observation_events e JOIN observation_values v USING(observation_id)
            WHERE {where}
            GROUP BY v.measurement_code, v.measurement_display, COALESCE(v.unit_code,'')
            ORDER BY count DESC, display LIMIT ?
        """, (*params, limit))]


def flagged_observations(database: Path = DEFAULT_DATABASE, *, patient_id: str | None = None,
                         start_date: str | None = None, end_date: str | None = None,
                         category: str = "All categories", limit: int = 100) -> list[dict]:
    """Fetch newest flagged rows without sampling ordinary rows first."""
    if not 1 <= limit <= 500:
        raise ValueError("Flagged row limit must be 1..500")
    with _db(database) as conn:
        _patient(conn, patient_id)
        where, params = _observation_filter(patient_id, start_date, end_date, category)
        return [dict(r) for r in conn.execute(f"""
            SELECT e.patient_id, e.observation_id, e.effective_datetime_utc,
                   e.category, v.measurement_code, v.measurement_display,
                   v.value_numeric, v.value_text, v.unit_code,
                   v.quality_status, v.quality_flags
            FROM observation_events e JOIN observation_values v USING(observation_id)
            WHERE {where} AND v.quality_status = 'REVIEW_REQUIRED'
            ORDER BY e.effective_datetime_utc DESC, e.observation_id DESC, v.component_index
            LIMIT ?
        """, (*params, limit))]
