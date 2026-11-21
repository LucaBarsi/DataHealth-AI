"""DataHealth AI — patient-scoped, evidence-linked measurement trends.

Only SQL evidence from the selected synthetic patient may suggest a measurement.
Chart values are re-read from the local Gold SQLite database (not from LLM text).
All queries are read-only; measurements are grouped by *code AND unit*.
The module has no Streamlit dependency so that its invariants can be unit-tested.

This module is for education and synthetic data exploration, not clinical use.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import Any

from . import analytics_backend

ALLOWED_TOPICS = frozenset({"vitals", "laboratory"})


@dataclass(frozen=True)
class ChartTarget:
    code: str
    unit: str
    display: str
    topic: str
    source_marker: str

    @property
    def label(self) -> str:
        return f"{self.display} · {self.code} · {self.unit or 'unit not recorded'}"


def chart_targets(evidence: dict[str, Any], patient_id: str, max_targets: int = 10) -> list[ChartTarget]:
    """Return distinct eligible (measurement code, unit) pairs in SQL evidence.

    No target is ever inferred from the LLM's free-form answer, from RAG text,
    or from a different patient's response.
    """
    if not isinstance(patient_id, str) or not patient_id:
        raise ValueError("A selected patient ID is required")
    if not isinstance(max_targets, int) or not 1 <= max_targets <= 30:
        raise ValueError("max_targets must be between 1 and 30")
    stored_patient = evidence.get("patient", {}).get("patient_id")
    if stored_patient != patient_id:
        raise ValueError("Patient scope mismatch: contextual chart blocked")

    choices: list[ChartTarget] = []
    seen: set[tuple[str, str]] = set()
    for item in evidence.get("sql_evidence", []):
        topic = item.get("topic")
        record = item.get("record")
        if topic not in ALLOWED_TOPICS or not isinstance(record, dict):
            continue
        # Upstream clinical-assistant queries may omit patient_id in each row;
        # nevertheless, reject any row that explicitly claims another patient.
        if record.get("patient_id") not in (None, patient_id):
            continue
        code = record.get("measurement_code")
        unit = record.get("unit_code") or ""
        raw = record.get("value_numeric")
        if not isinstance(code, str) or not code.strip() or len(code) > 128:
            continue
        if not isinstance(unit, str) or len(unit) > 128:
            continue
        if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not isfinite(float(raw)):
            continue
        marker = item.get("source_marker")
        if not isinstance(marker, str) or not marker.startswith(f"[SQL:{topic}:"):
            continue
        pair = (code, unit)
        if pair in seen:
            continue
        seen.add(pair)
        display = record.get("measurement_display") or code
        choices.append(ChartTarget(
            code=code, unit=unit, display=str(display), topic=topic, source_marker=marker,
        ))
        if len(choices) >= max_targets:
            break
    return choices


def chart_series(
    database: Path,
    evidence: dict[str, Any],
    patient_id: str,
    target: ChartTarget,
    *,
    include_flagged: bool = False,
    limit: int = 500,
) -> dict[str, Any]:
    """Read the complete available series for one evidence-linked target.

    The LLM's source snippets may contain just 5 recent rows; this function
    reads up to 500 matching historical rows from the Gold Layer, filtered by
    selected patient and exact code and unit. No clinical interpretation.
    """
    if not isinstance(target, ChartTarget) or target not in chart_targets(evidence, patient_id):
        raise ValueError("Chart target is not present in selected patient's retrieved SQL evidence")
    if not isinstance(limit, int) or not 1 <= limit <= 2000:
        raise ValueError("limit must be in 1..2000")
    series = analytics_backend.measurement_series(
        Path(database), patient_id, target.code, target.unit,
        include_flagged=include_flagged, limit=limit,
    )
    for row in series["rows"]:
        if row["patient_id"] != patient_id:
            raise RuntimeError("Database returned measurements for another patient")
        if row["measurement_code"] != target.code or (row.get("unit_code") or "") != target.unit:
            raise RuntimeError("Database returned an unrelated measurement")
    return series
