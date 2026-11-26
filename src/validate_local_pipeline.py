"""Read-only reconciliation of DataHealth AI's local Spark and SQLite outputs.

The datasets must contain synthetic records only. No row-level identifiers or
clinical content are included in the audit report. This is NOT clinical validation.

Usage (Ubuntu WSL, from project root):
    python -m src.validate_local_pipeline
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from contextlib import closing
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

GOLD_TABLES = (
    "measurement_frequency",
    "monthly_encounters",
    "observation_categories",
    "resource_counts",
    "structural_quality",
)

SQLITE_TO_FHIR = {
    "patients": "Patient",
    "encounters": "Encounter",
    "observation_events": "Observation",
    "conditions": "Condition",
    "diagnostic_reports": "DiagnosticReport",
    "medication_requests": "MedicationRequest",
    "clinical_documents": "DocumentReference",
}

FORBIDDEN_SILVER_COLUMNS = frozenset({
    "name", "patient_name", "given_name", "family_name", "address", "phone",
    "email", "telecom", "document_body", "full_text", "raw_json",
})


def equal_counts(actual: dict[str, int], expected: dict[str, int]) -> bool:
    """Compare dictionaries of label -> integer count without row-level data."""
    return actual == expected


def records_to_counts(rows: list[Any], key: str, count: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for row in rows:
        label = row[key]
        value = int(row[count])
        label_key = str(label) if label is not None else "(null)"
        if label_key in result:
            raise ValueError(f"Duplicate aggregate label: {label_key}")
        result[label_key] = value
    return result


def compare_sqlite_counts(db_path: Path, raw_counts: dict[str, int]) -> dict[str, Any]:
    """Read an existing SQLite DB in read-only mode; differences are informational."""
    if not db_path.is_file():
        return {"status": "NOT_FOUND", "tables": {}, "note": "SQLite comparison skipped."}
    table_results: dict[str, dict[str, Any]] = {}
    with closing(sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
        existing = {str(row[0]) for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        for table, resource in SQLITE_TO_FHIR.items():
            if table not in existing:
                table_results[table] = {"status": "TABLE_NOT_FOUND", "fhir_resource": resource}
                continue
            # Every identifier comes from the fixed internal allowlist above.
            sqlite_count = int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
            raw_count = int(raw_counts.get(resource, 0))
            table_results[table] = {
                "fhir_resource": resource,
                "raw_fhir_count": raw_count,
                "sqlite_count": sqlite_count,
                "equal": raw_count == sqlite_count,
                "difference_sqlite_minus_raw": sqlite_count - raw_count,
            }
    return {
        "status": "COMPARED_INFORMATIONALLY",
        "tables": table_results,
        "note": "Raw FHIR and normalized SQLite may legitimately differ; not a test failure.",
    }


def _dict_counts(df: Any, label: str, count: str) -> dict[str, int]:
    return records_to_counts(df.select(label, count).collect(), label, count)


def audit(spark: Any, spark_dir: Path, summary_path: Path,
          sqlite_path: Path, raw_dir: Path) -> dict[str, Any]:
    """Reconcile Silver, all Gold tables, Phase 19 summary, and optional SQLite."""
    from pyspark.sql import functions as F

    silver_dir = spark_dir / "silver" / "fhir_resources"
    gold_dir = spark_dir / "gold"
    required = [silver_dir, *(gold_dir / x for x in GOLD_TABLES)]
    absent = [str(p) for p in required if not p.is_dir()]
    if absent:
        raise FileNotFoundError("Missing Spark Parquet directories: " + ", ".join(absent))
    if not summary_path.is_file():
        raise FileNotFoundError(f"Missing Phase 19 report: {summary_path}")
    if not raw_dir.is_dir():
        raise FileNotFoundError(f"Missing synthetic FHIR raw directory: {raw_dir}")

    previous = json.loads(summary_path.read_text(encoding="utf-8"))
    silver = spark.read.parquet(silver_dir.resolve().as_uri()).cache()
    try:
        gold = {
            table: spark.read.parquet((gold_dir / table).resolve().as_uri())
            for table in GOLD_TABLES
        }
        resource_counts = _dict_counts(
            silver.groupBy("resource_type").agg(F.count(F.lit(1)).alias("n")),
            "resource_type", "n",
        )
        structural_counts = _dict_counts(
            silver.groupBy("quality_status").agg(F.count(F.lit(1)).alias("n")),
            "quality_status", "n",
        )
        total = int(sum(resource_counts.values()))
        gold_resources = _dict_counts(gold["resource_counts"], "resource_type", "resource_count")
        gold_quality = _dict_counts(gold["structural_quality"], "quality_status", "resource_count")

        category_expected = _dict_counts(
            silver.filter(F.col("resource_type") == "Observation")
            .fillna({"category": "unspecified"})
            .groupBy("category").agg(F.count(F.lit(1)).alias("n")),
            "category", "n",
        )
        category_gold = _dict_counts(
            gold["observation_categories"], "category", "observation_count",
        )

        month_expected = _dict_counts(
            silver.filter((F.col("resource_type") == "Encounter") & F.col("event_date").isNotNull())
            .withColumn("month", F.date_format("event_date", "yyyy-MM"))
            .groupBy("month").agg(F.count(F.lit(1)).alias("n")),
            "month", "n",
        )
        month_gold = _dict_counts(gold["monthly_encounters"], "month", "encounter_count")

        # Measurement keys can contain NULL values; compare whole aggregate tuples.
        measurement_expected = {
            (r["measurement_code"], r["measurement_name"], r["unit"], int(r["observation_count"]))
            for r in (
                silver.filter((F.col("resource_type") == "Observation") &
                              F.col("measurement_code").isNotNull())
                .groupBy("measurement_code", "measurement_name", "unit")
                .agg(F.count(F.lit(1)).alias("observation_count"))
                .collect()
            )
        }
        measurement_gold = {
            (r["measurement_code"], r["measurement_name"], r["unit"], int(r["observation_count"]))
            for r in gold["measurement_frequency"].collect()
        }

        raw_files = len(list(raw_dir.glob("*.json")))
        tests = {
            "bronze_bundle_file_count_matches_phase19": raw_files == int(previous["input_bundle_files"]),
            "silver_count_matches_phase19": total == int(previous["resource_rows"]),
            "silver_resource_counts_match_phase19": equal_counts(resource_counts, previous["resource_counts"]),
            "silver_structural_counts_match_phase19": equal_counts(structural_counts, previous["structural_quality"]),
            "gold_resource_counts_match_silver": equal_counts(gold_resources, resource_counts),
            "gold_structural_quality_matches_silver": equal_counts(gold_quality, structural_counts),
            "gold_observation_categories_match_silver": equal_counts(category_gold, category_expected),
            "gold_monthly_encounters_match_silver": equal_counts(month_gold, month_expected),
            "gold_measurement_frequency_matches_silver": measurement_gold == measurement_expected,
            "silver_excludes_identifying_columns": not any(
                column.lower() in FORBIDDEN_SILVER_COLUMNS for column in silver.columns
            ),
            "silver_quality_counts_sum_to_total": sum(structural_counts.values()) == total,
            "gold_resource_counts_sum_to_total": sum(gold_resources.values()) == total,
        }
        return {
            "project": "DataHealth AI",
            "phase": "20 - Local Pipeline Integration Audit",
            "data_policy": "Synthetic FHIR only. Structural, not clinical, validation.",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "audit_status": "PASS" if all(tests.values()) else "FAIL",
            "checks_passed": sum(tests.values()),
            "checks_total": len(tests),
            "checks": tests,
            "counts": {
                "raw_bundle_files": raw_files,
                "silver_resource_rows": total,
                "gold_tables": len(GOLD_TABLES),
                "patient_resource_rows": resource_counts.get("Patient", 0),
                "observation_resource_rows": resource_counts.get("Observation", 0),
                "encounter_resource_rows": resource_counts.get("Encounter", 0),
            },
            "sqlite_reconciliation": compare_sqlite_counts(sqlite_path, resource_counts),
            "limitations": [
                "This audit verifies internal arithmetic consistency, not FHIR standards compliance.",
                "SQLite normalization may expand or filter raw FHIR data; count differences are informational.",
                "Passing checks does not establish diagnostic accuracy or clinical safety.",
            ],
        }
    finally:
        silver.unpersist()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only DataHealth AI integration audit")
    parser.add_argument("--spark-dir", default="data/spark_demo")
    parser.add_argument("--phase19-report", default="reports/spark/phase19_summary.json")
    parser.add_argument("--sqlite", default="data/gold/datahealth.db")
    parser.add_argument("--raw", default="data/raw/synthea_sample_data_fhir_latest")
    parser.add_argument("--report", default="reports/integration/phase20_validation.json")
    args = parser.parse_args(argv)
    spark_dir = Path(args.spark_dir)
    raw_dir = Path(args.raw)
    phase19_report = Path(args.phase19_report)
    report_file = Path(args.report)
    # Protect inputs and existing Phase 19 report.
    if report_file.resolve() == phase19_report.resolve():
        parser.error("Phase 20 report must differ from the existing Phase 19 report")
    if report_file.resolve().is_relative_to(spark_dir.resolve()) or report_file.resolve().is_relative_to(raw_dir.resolve()):
        parser.error("Report must not be saved inside any dataset directory")

    from src.spark_etl import build_spark
    spark = build_spark()
    try:
        result = audit(spark, spark_dir, phase19_report, Path(args.sqlite), raw_dir)
    finally:
        spark.stop()
    report_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["audit_status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
