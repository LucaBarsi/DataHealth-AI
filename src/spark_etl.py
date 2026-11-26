"""DataHealth AI: optional, local Apache Spark FHIR Bundle -> Parquet ETL.

All records are synthetic. This module writes to a separate Spark demo directory,
without changing the existing Bronze/Silver/Gold Python/SQLite pipeline.

Run from repository root:
    python -m src.spark_etl run --input data/raw/synthea_sample_data_fhir_latest \
        --output data/spark_demo --report reports/spark/phase19_summary.json
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import sys

from pyspark.sql import SparkSession, DataFrame, functions as F, types as T


CODING_SCHEMA = T.StructType([
    T.StructField("code", T.StringType()),
    T.StructField("display", T.StringType()),
])

RESOURCE_SCHEMA = T.StructType([
    T.StructField("resourceType", T.StringType()),
    T.StructField("id", T.StringType()),
    T.StructField("status", T.StringType()),
    T.StructField("period", T.StructType([
        T.StructField("start", T.StringType()),
    ])),
    T.StructField("effectiveDateTime", T.StringType()),
    T.StructField("issued", T.StringType()),
    T.StructField("recordedDate", T.StringType()),
    T.StructField("authoredOn", T.StringType()),
    T.StructField("category", T.ArrayType(T.StructType([
        T.StructField("coding", T.ArrayType(CODING_SCHEMA)),
    ]))),
    T.StructField("code", T.StructType([
        T.StructField("coding", T.ArrayType(CODING_SCHEMA)),
        T.StructField("text", T.StringType()),
    ])),
    T.StructField("valueQuantity", T.StructType([
        T.StructField("value", T.DoubleType()),
        T.StructField("unit", T.StringType()),
    ])),
])

BUNDLE_SCHEMA = T.StructType([
    T.StructField("resourceType", T.StringType()),
    T.StructField("entry", T.ArrayType(T.StructType([
        T.StructField("resource", RESOURCE_SCHEMA),
    ]))),
])


def build_spark() -> SparkSession:
    # Especially important on Windows: worker Python should match this venv.
    os.environ.setdefault("PYSPARK_PYTHON", sys.executable)
    os.environ.setdefault("PYSPARK_DRIVER_PYTHON", sys.executable)
    spark = (SparkSession.builder
             .master("local[2]")
             .appName("DataHealthAI-FHIR-ETL")
             .config("spark.sql.session.timeZone", "UTC")
             .config("spark.sql.shuffle.partitions", "4")
             .getOrCreate())
    spark.sparkContext.setLogLevel("ERROR")
    return spark


def parse_bundles(spark: SparkSession, input_dir: Path) -> tuple[DataFrame, int, int]:
    json_files = sorted(input_dir.glob("*.json"))
    if not json_files:
        raise FileNotFoundError(f"No JSON files in {input_dir}")

    # Spark reads each entire FHIR Bundle as a row; no driver-side collect of raw data.
    raw = spark.read.text(input_dir.resolve().as_uri() + "/*.json", wholetext=True)
    parsed = raw.select(F.from_json("value", BUNDLE_SCHEMA).alias("bundle"))
    bundle_count = parsed.count()
    valid = parsed.filter(F.col("bundle.resourceType") == "Bundle")
    valid_count = valid.count()
    if valid_count != bundle_count:
        raise ValueError(f"Unexpected or unreadable FHIR Bundles: {bundle_count-valid_count}/{bundle_count}")

    entries = valid.select(F.explode("bundle.entry").alias("entry"))
    resources = entries.select(F.col("entry.resource").alias("r"))
    return resources, bundle_count, valid_count


def normalize_resources(resources: DataFrame) -> DataFrame:
    category_code = F.col("r.category").getItem(0).getField("coding").getItem(0).getField("code")
    measure_code = F.col("r.code").getField("coding").getItem(0).getField("code")
    measure_display = F.coalesce(
        F.col("r.code").getField("coding").getItem(0).getField("display"),
        F.col("r.code").getField("text"),
    )
    event_time = F.coalesce(
        F.col("r.period.start"), F.col("r.effectiveDateTime"),
        F.col("r.issued"), F.col("r.recordedDate"), F.col("r.authoredOn"),
    )
    df = resources.select(
        F.col("r.resourceType").alias("resource_type"),
        F.col("r.id").alias("resource_id"),
        F.col("r.status").alias("record_status"),
        F.to_date(F.substring(event_time, 1, 10)).alias("event_date"),
        category_code.alias("category"),
        measure_code.alias("measurement_code"),
        measure_display.alias("measurement_name"),
        F.col("r.valueQuantity.value").alias("numeric_value"),
        F.col("r.valueQuantity.unit").alias("unit"),
    )
    # Minimal structural review only; does NOT imply medical or clinical validity.
    return df.withColumn(
        "quality_status",
        F.when(F.col("resource_type").isNull(), F.lit("MISSING_RESOURCE_TYPE"))
         .when(F.col("resource_id").isNull() | (F.trim("resource_id") == ""),
               F.lit("MISSING_RESOURCE_ID"))
         .otherwise(F.lit("PASS_MINIMAL_STRUCTURAL_CHECK")),
    )


def make_gold(silver: DataFrame) -> dict[str, DataFrame]:
    counts = silver.groupBy("resource_type").agg(F.count(F.lit(1)).alias("resource_count"))
    months = (silver.filter((F.col("resource_type") == "Encounter") & F.col("event_date").isNotNull())
              .withColumn("month", F.date_format("event_date", "yyyy-MM"))
              .groupBy("month").agg(F.count(F.lit(1)).alias("encounter_count")))
    observations = silver.filter(F.col("resource_type") == "Observation")
    categories = (observations.fillna({"category": "unspecified"})
                  .groupBy("category").agg(F.count(F.lit(1)).alias("observation_count")))
    measurements = (observations.filter(F.col("measurement_code").isNotNull())
                    .groupBy("measurement_code", "measurement_name", "unit")
                    .agg(F.count(F.lit(1)).alias("observation_count")))
    quality = silver.groupBy("quality_status").agg(F.count(F.lit(1)).alias("resource_count"))
    return {"resource_counts": counts, "monthly_encounters": months,
            "observation_categories": categories,
            "measurement_frequency": measurements, "structural_quality": quality}


def validate_paths(input_dir: Path, output_dir: Path, report_file: Path) -> None:
    source = input_dir.resolve()
    destination = output_dir.resolve()
    if not source.is_dir():
        raise FileNotFoundError(f"Input directory does not exist: {source}")
    if source == destination or source.is_relative_to(destination) or destination.is_relative_to(source):
        raise ValueError("Input and output directories must be separate")
    if report_file.resolve().is_relative_to(source):
        raise ValueError("Report file must not be written into the source directory")
    if destination.name.lower() in {"raw", "silver", "gold"}:
        raise ValueError("Use a distinct output directory; do not overwrite existing pipeline layers")


def execute(spark: SparkSession, input_dir: Path, output_dir: Path, report_file: Path) -> dict:
    validate_paths(input_dir, output_dir, report_file)
    resources, bundle_count, valid_count = parse_bundles(spark, input_dir)
    silver = normalize_resources(resources).cache()
    total = silver.count()
    if total == 0:
        silver.unpersist()
        raise ValueError("No FHIR resources were found")

    gold = make_gold(silver)
    try:
        silver.write.mode("overwrite").parquet((output_dir / "silver" / "fhir_resources").resolve().as_uri())
        for name, df in gold.items():
            df.write.mode("overwrite").parquet((output_dir / "gold" / name).resolve().as_uri())
        resource_counts = {r["resource_type"]: r["resource_count"]
                           for r in gold["resource_counts"].collect() if r["resource_type"]}
        structural_counts = {r["quality_status"]: r["resource_count"]
                             for r in gold["structural_quality"].collect()}
    finally:
        silver.unpersist()

    report = {
        "project": "DataHealth AI",
        "phase": "19 - Local PySpark FHIR ETL Proof of Concept",
        "data_policy": "Synthetic FHIR only. Not clinical validation.",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_bundle_files": bundle_count,
        "validated_bundles": valid_count,
        "resource_rows": total,
        "resource_counts": resource_counts,
        "structural_quality": structural_counts,
        "silver_path": (output_dir / "silver" / "fhir_resources").as_posix(),
        "gold_tables": sorted(gold),
        "warning": "Counts from raw bundles are NOT expected to match normalized Gold SQLite totals exactly.",
    }
    report_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Local synthetic FHIR Spark ETL")
    parser.add_argument("command", choices=["run"])
    parser.add_argument("--input", default="data/raw/synthea_sample_data_fhir_latest")
    parser.add_argument("--output", default="data/spark_demo")
    parser.add_argument("--report", default="reports/spark/phase19_summary.json")
    args = parser.parse_args(argv)
    # Validate before starting Spark (avoid accidental overwrite).
    validate_paths(Path(args.input), Path(args.output), Path(args.report))
    spark = build_spark()
    try:
        summary = execute(spark, Path(args.input), Path(args.output), Path(args.report))
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
