"""Phase 18: exploratory forecasting of monthly SYNTHETIC encounter counts.

Reads Gold SQLite encounters in read-only mode. No identifiers beyond encounter_id
are loaded; no patient demographics or clinical outcomes are used.

The evaluation is rolling one-step-ahead with known observed lags, not an
unattended multi-step forecast or a hospital demand prediction service.
"""
from __future__ import annotations

import argparse
import csv
from datetime import date, datetime, timezone
import json
import math
from pathlib import Path
import sqlite3
import sys
from typing import Any

MIN_WINDOW = 48
DEFAULT_WINDOW = 60
MAX_WINDOW = 240
LAG = 12


def month_number(value: date) -> int:
    return value.year * 12 + value.month - 1


def month_label(n: int) -> str:
    return f"{n // 12:04d}-{(n % 12) + 1:02d}"


def read_gold_encounters(database: Path) -> list[tuple[str, str | None]]:
    """Fetch only the minimal two fields from a SQLite DB in read-only mode."""
    if not database.is_file():
        raise FileNotFoundError(f"Gold database does not exist: {database}")
    conn = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        found = {str(row[1]) for row in conn.execute('PRAGMA table_info("encounters")')}
        required = {"encounter_id", "start_time_utc"}
        if not required.issubset(found):
            raise ValueError("Gold encounters table must contain encounter_id and start_time_utc")
        return [(str(r[0]), r[1]) for r in conn.execute(
            'SELECT encounter_id, start_time_utc FROM encounters'
        )]
    finally:
        conn.close()


def parse_utc(raw: str | None) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        dt = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except (ValueError, OverflowError):
        return None
    if dt.tzinfo is None:
        return None  # Never assume timezone.
    return dt.astimezone(timezone.utc)


def monthly_audit(rows: list[tuple[str, str | None]], as_of: date,
                  window: int = DEFAULT_WINDOW) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Include only FULL UTC calendar months strictly before as_of's month."""
    if not MIN_WINDOW <= window <= MAX_WINDOW:
        raise ValueError(f"--window must be between {MIN_WINDOW} and {MAX_WINDOW}")
    cutoff = month_number(as_of)
    last = cutoff - 1
    first = last - window + 1
    counts: dict[int, int] = {}
    seen: set[str] = set()
    invalid = duplicate = incomplete = older = included = 0
    for eid, raw in rows:
        if not eid or eid in seen:
            duplicate += 1
            continue
        seen.add(eid)
        dt = parse_utc(raw)
        if dt is None:
            invalid += 1
            continue
        month = month_number(dt.date())
        if month >= cutoff:
            incomplete += 1
        elif month < first:
            older += 1
        else:
            included += 1
            counts[month] = counts.get(month, 0) + 1
    series = [{"period": month_label(m), "count": counts.get(m, 0)}
              for m in range(first, last + 1)]
    positives = sum(s["count"] > 0 for s in series)
    max_count = max((s["count"] for s in series), default=0)
    zero_fraction = 1.0 - positives / window
    max_zero_streak = streak = 0
    for s in series:
        streak = streak + 1 if s["count"] == 0 else 0
        max_zero_streak = max(max_zero_streak, streak)
    warnings: list[str] = []
    if invalid:
        warnings.append("Invalid/missing/unzoned timestamps were excluded")
    if duplicate:
        warnings.append("Duplicate encounter IDs were excluded")
    if positives < max(12, window // 4):
        warnings.append("Very few months contain encounters: training is not meaningful")
    if zero_fraction > 0.5:
        warnings.append("More than half the selected months have no encounters: zeros may indicate incomplete data")
    if max_count > included * 0.4 and included > 0:
        warnings.append("One month contains more than 40% of selected encounters")
    if sum(s["count"] for s in series[-6:]) == 0:
        warnings.append("No encounters in the six most recent complete months")
    if included < 100:
        warnings.append("Fewer than 100 encounters in the selected window")
    status = "SUFFICIENT_FOR_EXPLORATORY_TEST" if (
        included >= 100 and positives >= max(12, window // 4)
    ) else "INSUFFICIENT_FOR_MEANINGFUL_MODELING"
    audit = {
        "project": "DataHealth AI",
        "phase": "18 — Synthetic Workload Forecasting",
        "data_source": "Gold SQLite encounters table — synthetic only",
        "interpretation": "Exploratory time-series experiment; not validated healthcare demand forecasting",
        "as_of_utc_date": as_of.isoformat(),
        "completeness_rule": "Exclude the entire month containing as_of, and all later months",
        "window_months": window,
        "first_complete_month": month_label(first),
        "last_complete_month": month_label(last),
        "encounters_read": len(rows),
        "unique_encounter_ids": len(seen),
        "invalid_or_missing_start_time": invalid,
        "duplicate_encounter_ids": duplicate,
        "excluded_current_or_future_month": incomplete,
        "excluded_before_window": older,
        "encounters_in_window": included,
        "months_with_encounters": positives,
        "months_without_encounters": window - positives,
        "zero_month_fraction": round(zero_fraction, 4),
        "longest_zero_month_streak": max_zero_streak,
        "maximum_monthly_count": max_count,
        "status": status,
        "warnings": warnings,
    }
    return series, audit


def features(series: list[dict[str, Any]]) -> tuple[list[list[float]], list[float], list[str], list[int]]:
    """Only features available before each target month. No target leakage."""
    counts = [int(s["count"]) for s in series]
    x: list[list[float]] = []
    y: list[float] = []
    labels: list[str] = []
    offsets: list[int] = []
    for t in range(LAG, len(counts)):
        month = int(series[t]["period"].split("-")[1])
        x.append([
            float(counts[t - 1]), float(counts[t - 2]),
            float(counts[t - 3]), float(counts[t - 6]),
            float(counts[t - 12]),
            sum(counts[t - 3:t]) / 3.0,
            sum(counts[t - 6:t]) / 6.0,
            math.sin(2.0 * math.pi * month / 12.0),
            math.cos(2.0 * math.pi * month / 12.0),
            float(t),
        ])
        y.append(float(counts[t]))
        labels.append(series[t]["period"])
        offsets.append(t)
    return x, y, labels, offsets


def chronological_split(n: int) -> tuple[range, range, range]:
    if n < 24:
        raise ValueError("Need at least 24 labeled months after lag-12 warmup")
    n_train = int(n * 0.60)
    n_val = int(n * 0.20)
    if min(n_train, n_val, n - n_train - n_val) < 6:
        raise ValueError("Chronological split must have >=6 months per partition")
    return range(n_train), range(n_train, n_train + n_val), range(n_train + n_val, n)


def metrics(truth: list[float], pred: list[float]) -> dict[str, float | None]:
    if len(truth) != len(pred) or not truth:
        raise ValueError("Non-empty, equal-length truth and predictions required")
    if any(not math.isfinite(v) for v in truth + pred):
        raise ValueError("Non-finite inputs not allowed")
    errors = [abs(a - b) for a, b in zip(truth, pred)]
    total = sum(abs(v) for v in truth)
    return {
        "mae": round(sum(errors) / len(errors), 4),
        "rmse": round(math.sqrt(sum((a-b)**2 for a,b in zip(truth,pred)) / len(truth)), 4),
        "wape_pct": round(100.0 * sum(errors) / total, 4) if total > 0 else None,
    }


def _predict_model(name: str, train_x: list[list[float]], train_y: list[float],
                   query_x: list[list[float]]) -> list[float]:
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.linear_model import Ridge
    from sklearn.ensemble import RandomForestRegressor
    if name == "ridge":
        model = make_pipeline(StandardScaler(), Ridge(alpha=10.0))
    elif name == "random_forest":
        model = RandomForestRegressor(n_estimators=120, max_depth=5,
                                      min_samples_leaf=3, n_jobs=1, random_state=42)
    else:
        raise ValueError(f"Unexpected model: {name}")
    model.fit(train_x, train_y)
    return [max(0.0, float(p)) for p in model.predict(query_x)]


def run_models(series: list[dict[str, Any]], audit: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if audit["status"] != "SUFFICIENT_FOR_EXPLORATORY_TEST":
        raise ValueError("Audit indicates insufficient history/volume. Inspect audit.json; no model was trained")
    x, y, labels, _ = features(series)
    tr, va, te = chronological_split(len(y))
    def take(v, idx): return [v[i] for i in idx]
    def predict(name: str, fit_indices: range, predict_indices: range) -> list[float]:
        if name == "last_month":
            return [x[i][0] for i in predict_indices]
        if name == "seasonal_12":
            return [x[i][4] for i in predict_indices]
        return _predict_model(name, take(x, fit_indices), take(y, fit_indices), take(x, predict_indices))
    names = ("last_month", "seasonal_12", "ridge", "random_forest")
    validation: dict[str, dict[str, Any]] = {}
    for name in names:
        validation[name] = metrics(take(y, va), predict(name, tr, va))
    # Model selection uses ONLY validation data. Favor simple baselines on exact ties.
    winner = min(names, key=lambda name: (
        validation[name]["mae"], validation[name]["rmse"], names.index(name)))
    train_val = range(va.stop)
    test_predictions: dict[str, list[float]] = {
        name: predict(name, train_val, te) for name in names
    }
    test_metrics = {name: metrics(take(y, te), pred)
                    for name, pred in test_predictions.items()}
    selected_pred = test_predictions[winner]
    prediction_rows = [{
        "month": labels[i],
        "actual_encounters": int(y[i]),
        "selected_model": winner,
        "predicted_encounters": round(selected_pred[j], 3),
        "last_month_baseline": round(test_predictions["last_month"][j], 3),
        "seasonal_12_baseline": round(test_predictions["seasonal_12"][j], 3),
    } for j,i in enumerate(te)]
    summary = {
        "project": "DataHealth AI",
        "phase": "18 — Synthetic Workload Forecasting",
        "status": "EXPLORATORY_ONLY_NOT_FOR_OPERATIONAL_USE",
        "evaluation_protocol": "Chronological 60/20/20; train on first block, select on validation, refit selected on train+validation, evaluate test once",
        "forecast_type": "Rolling one-step-ahead evaluation with actual prior-month counts available; not recursive multi-month forecasting",
        "feature_policy": "Only historical lags, historical rolling means, calendar seasonality and a time index; no contemporaneous records",
        "lag_warmup_months": LAG,
        "labeled_months": len(y),
        "train_months": len(tr), "validation_months": len(va), "test_months": len(te),
        "train_first_month": labels[tr.start], "train_last_month": labels[tr.stop-1],
        "validation_first_month": labels[va.start], "validation_last_month": labels[va.stop-1],
        "test_first_month": labels[te.start], "test_last_month": labels[te.stop-1],
        "candidate_models": list(names),
        "validation_metrics": validation,
        "selected_model_by_validation_mae": winner,
        "test_metrics_including_diagnostics_only": test_metrics,
        "selected_test_metrics": test_metrics[winner],
        "audit_warnings": audit["warnings"],
        "limitations": [
            "Synthetic encounters do not represent hospital demand or real-world operating patterns.",
            "Only the selected historical calendar window is analyzed, not a prospective forecast.",
            "Zero months may reflect sparse or incomplete synthetic data, not real zero demand.",
            "Lag features use the known observed preceding month at each evaluation step.",
            "Test metrics for all models are diagnostic; do not reselect the model using test results.",
            "No patient-level predictions or clinical inference.",
        ],
    }
    return summary, prediction_rows


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError("Cannot export empty CSV")
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def plot_report(out: Path, series: list[dict[str, Any]], predictions: list[dict[str, Any]]) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(11, 4))
    ax.plot([s["period"] for s in series], [s["count"] for s in series], marker=".", linewidth=1)
    ax.set_title("Synthetic monthly encounter counts (exploratory)")
    ax.set_ylabel("Encounter count")
    ax.set_xlabel("UTC complete calendar months")
    ax.set_xticks(range(0, len(series), max(1, len(series)//12)))
    ax.tick_params(axis="x", labelrotation=45)
    fig.tight_layout()
    fig.savefig(out / "monthly_encounters.png", dpi=140)
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(10,4))
    ax.plot([p["month"] for p in predictions], [p["actual_encounters"] for p in predictions], marker="o", label="Observed")
    ax.plot([p["month"] for p in predictions], [p["predicted_encounters"] for p in predictions], marker="o", label="Selected model")
    ax.set_title("Held-out test: one-step-ahead (synthetic only)")
    ax.set_ylabel("Encounters")
    ax.set_xlabel("Test months")
    ax.tick_params(axis="x", labelrotation=45)
    ax.legend()
    fig.tight_layout()
    fig.savefig(out / "test_predictions.png", dpi=140)
    plt.close(fig)


def markdown_report(audit: dict[str, Any], result: dict[str, Any]) -> str:
    names = result["candidate_models"]
    t = ["# Phase 18 — Synthetic Encounter Workload Forecasting", "",
         "Experimental one-step-ahead benchmark on **synthetic Gold Layer encounters**. Not a clinical or operational forecasting tool.", "",
         "## Data coverage", "",
         f"- UTC analysis period: {audit['first_complete_month']} to {audit['last_complete_month']}",
         f"- Total encounters in window: {audit['encounters_in_window']}",
         f"- Empty months: {audit['months_without_encounters']} / {audit['window_months']}",
         f"- Data quality warnings: {', '.join(audit['warnings']) if audit['warnings'] else 'None flagged by the limited audit'}", "",
         "## Evaluation", "",
         f"- Split: {result['train_months']} train, {result['validation_months']} validation, {result['test_months']} test months (chronological)",
         f"- Selected by validation MAE: **{result['selected_model_by_validation_mae']}**", "",
         "| Candidate | Validation MAE | Test MAE | Test RMSE | Test WAPE |", "|---|---:|---:|---:|---:|"]
    for name in names:
        v = result["validation_metrics"][name]; m = result["test_metrics_including_diagnostics_only"][name]
        w = f"{m['wape_pct']:.2f}%" if m["wape_pct"] is not None else "N/A (zero denominator)"
        t.append(f"| {name} | {v['mae']:.3f} | {m['mae']:.3f} | {m['rmse']:.3f} | {w} |")
    t += ["", "The model choice used only validation data. Test metrics for unselected models are diagnostics, not a basis for re-selection.", "",
          "## Limitations", ""]
    t.extend(f"- {x}" for x in result["limitations"])
    return "\n".join(t) + "\n"


def run_cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for cmd in ("audit", "run"):
        p = sub.add_parser(cmd)
        p.add_argument("--database", default="data/gold/datahealth.db")
        p.add_argument("--output", default="reports/ml/phase18")
        p.add_argument("--window", type=int, default=DEFAULT_WINDOW,
                       help="Trailing COMPLETE UTC months to analyze (default: 60)")
        p.add_argument("--as-of", type=date.fromisoformat, default=None,
                       metavar="YYYY-MM-DD", help="Reproducible UTC as-of date; excludes this month")
    args = parser.parse_args(argv)
    out = Path(args.output)
    try:
        rows = read_gold_encounters(Path(args.database))
        series, audit = monthly_audit(rows, args.as_of or datetime.now(timezone.utc).date(), args.window)
        out.mkdir(parents=True, exist_ok=True)
        write_json(out / "data_audit.json", audit)
        write_csv(out / "monthly_encounters.csv", series)
        if args.command == "audit":
            print(json.dumps(audit, indent=2))
            return 0 if audit["status"] == "SUFFICIENT_FOR_EXPLORATORY_TEST" else 2
        summary, preds = run_models(series, audit)
        write_json(out / "evaluation_summary.json", summary)
        write_csv(out / "test_predictions.csv", preds)
        (out / "evaluation_report.md").write_text(markdown_report(audit, summary), encoding="utf-8")
        plot_report(out, series, preds)
        print(json.dumps({"status": summary["status"],
                          "selected_model": summary["selected_model_by_validation_mae"],
                          "test_metrics": summary["selected_test_metrics"],
                          "output": str(out)}, indent=2))
        return 0
    except (ValueError, OSError, sqlite3.DatabaseError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(run_cli())
