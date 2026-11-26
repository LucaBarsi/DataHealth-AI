"""Read and validate Phase 18 synthetic forecasting artifacts (read-only).

No SQLite queries, model fitting, network access, or patient-level information.
"""
from __future__ import annotations

import csv
from datetime import datetime
import json
import math
from pathlib import Path
from typing import Any

REQUIRED_FILES = (
    "data_audit.json", "evaluation_summary.json", "monthly_encounters.csv", "test_predictions.csv"
)
_ALLOWED_STATUS = "EXPLORATORY_ONLY_NOT_FOR_OPERATIONAL_USE"


def _json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return data


def _csv(path: Path, required: set[str]) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
            raise ValueError(f"{path.name} is missing required columns")
        rows = list(reader)
    if not rows:
        raise ValueError(f"{path.name} contains no records")
    return rows


def _month(value: str) -> str:
    if len(value) != 7 or value[4] != "-":
        raise ValueError("Expected month in YYYY-MM format")
    datetime.strptime(value, "%Y-%m")
    return value


def _number(value: Any) -> float:
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError("Encounter counts and errors must be finite, nonnegative")
    return result


def read_report(report_dir: Path) -> dict[str, Any]:
    """Return strictly scoped, validated aggregate reports from the existing ML run."""
    report_dir = Path(report_dir)
    missing = [name for name in REQUIRED_FILES if not (report_dir / name).is_file()]
    if missing:
        raise FileNotFoundError("Missing Phase 18 report files: " + ", ".join(missing))

    audit = _json(report_dir / "data_audit.json")
    summary = _json(report_dir / "evaluation_summary.json")
    if audit.get("status") != "SUFFICIENT_FOR_EXPLORATORY_TEST":
        raise ValueError("The Phase 18 source audit was not approved for the exploratory test")
    if summary.get("status") != _ALLOWED_STATUS:
        raise ValueError("Unexpected Phase 18 evaluation status")

    months = []
    for raw in _csv(report_dir / "monthly_encounters.csv", {"period", "count"}):
        m = _month(raw["period"])
        count = _number(raw["count"])
        if not count.is_integer():
            raise ValueError("Monthly encounter counts must be integers")
        months.append({"month": m, "encounters": int(count)})
    if len({m["month"] for m in months}) != len(months) or [m["month"] for m in months] != sorted(m["month"] for m in months):
        raise ValueError("Historical months must be distinct and chronologically sorted")
    if len(months) != int(audit["window_months"]) or sum(m["encounters"] for m in months) != int(audit["encounters_in_window"]):
        raise ValueError("Historical CSV does not match the data audit")
    if months[0]["month"] != audit.get("first_complete_month") or months[-1]["month"] != audit.get("last_complete_month"):
        raise ValueError("Historical periods do not match the data audit")

    winner = summary.get("selected_model_by_validation_mae")
    models = summary.get("candidate_models")
    val = summary.get("validation_metrics")
    test = summary.get("test_metrics_including_diagnostics_only")
    if not isinstance(models, list) or not models or not isinstance(val, dict) or not isinstance(test, dict) or winner not in models:
        raise ValueError("Invalid model selection fields")
    model_rows = []
    for name in models:
        if name not in val or name not in test:
            raise ValueError("Missing model metrics")
        vm, tm = val[name], test[name]
        row = {
            "model": name,
            "validation_mae": _number(vm["mae"]),
            "test_mae": _number(tm["mae"]),
            "test_rmse": _number(tm["rmse"]),
            "test_wape_pct": _number(tm["wape_pct"]) if tm.get("wape_pct") is not None else None,
            "selected": name == winner,
        }
        model_rows.append(row)
    selected = next(r for r in model_rows if r["selected"])

    pred_rows = []
    for raw in _csv(report_dir / "test_predictions.csv", {
        "month", "actual_encounters", "selected_model", "predicted_encounters", "last_month_baseline", "seasonal_12_baseline"
    }):
        if raw["selected_model"] != winner:
            raise ValueError("Test predictions were made for a different model")
        pred_rows.append({
            "month": _month(raw["month"]),
            "observed": _number(raw["actual_encounters"]),
            "predicted": _number(raw["predicted_encounters"]),
            "last_month": _number(raw["last_month_baseline"]),
            "seasonal_12": _number(raw["seasonal_12_baseline"]),
        })
    pred_months = [row["month"] for row in pred_rows]
    if len(set(pred_months)) != len(pred_months) or pred_months != sorted(pred_months):
        raise ValueError("Test months must be unique and sorted")
    if len(pred_rows) != int(summary["test_months"]) or pred_months[0] != summary["test_first_month"] or pred_months[-1] != summary["test_last_month"]:
        raise ValueError("Test predictions do not match evaluation summary")
    counts_by_month = {m["month"]: m["encounters"] for m in months}
    if any(row["month"] not in counts_by_month or counts_by_month[row["month"]] != row["observed"] for row in pred_rows):
        raise ValueError("Held-out actual counts disagree with history")

    # Any model-to-test comparison displayed here is descriptive; selection took place on validation only.
    return {
        "audit": audit,
        "summary": summary,
        "monthly": months,
        "predictions": pred_rows,
        "models": model_rows,
        "selected": selected,
        "selected_model": winner,
    }
