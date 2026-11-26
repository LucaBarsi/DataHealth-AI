"""Self-contained Spark ETL integration tests using invented FHIR fixtures."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.spark_etl import build_spark, execute, validate_paths


def example_bundle(patient_id: str, obs_id: str) -> dict:
    return {
        "resourceType": "Bundle",
        "type": "collection",
        "entry": [
            {"resource": {"resourceType": "Patient", "id": patient_id,
                          "name": [{"text": "INVENTED PRIVATE NAME"}]}},
            {"resource": {"resourceType": "Encounter", "id": "enc-"+patient_id,
                          "period": {"start": "2026-01-12T08:00:00+00:00"}, "status": "finished"}},
            {"resource": {"resourceType": "Observation", "id": obs_id,
                          "effectiveDateTime": "2026-01-12T08:00:00+00:00",
                          "category": [{"coding": [{"code": "vital-signs"}]}],
                          "code": {"coding": [{"code": "8867-4", "display": "Heart rate"}]},
                          "valueQuantity": {"value": 75, "unit": "/min"}}},
        ],
    }


class SparkEtLTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # On Windows, Hadoop may retain handles until SparkContext stops.
        # Therefore clean up the temporary directory AFTER stopping Spark.
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp_dir.name)
        cls.spark = build_spark()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.spark.stop()
        finally:
            cls.temp_dir.cleanup()

    def test_full_pipeline_and_no_names_in_outputs(self):
        root = self.root / "full"
        source = root / "source"
        source.mkdir(parents=True)
        for idx in (1, 2):
            (source / f"bundle_{idx}.json").write_text(
                json.dumps(example_bundle(f"p{idx}", f"o{idx}")), encoding="utf-8")
        output = root / "spark_demo"
        report = root / "reports" / "summary.json"
        result = execute(self.spark, source, output, report)
        self.assertEqual(result["input_bundle_files"], 2)
        self.assertEqual(result["resource_rows"], 6)
        self.assertEqual(result["resource_counts"]["Observation"], 2)
        self.assertEqual(result["resource_counts"]["Encounter"], 2)
        self.assertTrue(report.is_file())
        silver = self.spark.read.parquet((output / "silver" / "fhir_resources").resolve().as_uri())
        self.assertEqual(silver.count(), 6)
        self.assertNotIn("name", silver.columns)
        self.assertNotIn("patient_name", silver.columns)
        months = self.spark.read.parquet((output / "gold" / "monthly_encounters").resolve().as_uri())
        self.assertEqual(months.collect()[0]["encounter_count"], 2)
        self.assertEqual(months.collect()[0]["month"], "2026-01")
        quality = self.spark.read.parquet((output / "gold" / "structural_quality").resolve().as_uri())
        self.assertEqual(sum(row["resource_count"] for row in quality.collect()), 6)

    def test_input_directory_cannot_be_output(self):
        source = self.root / "other_raw"
        source.mkdir()
        with self.assertRaises(ValueError):
            validate_paths(source, source, self.root / "report.json")

    def test_invalid_json_bundle_rejected(self):
        root = self.root / "invalid"
        source = root / "source"
        source.mkdir(parents=True)
        (source / "bad.json").write_text('{"resourceType":"Patient"}', encoding="utf-8")
        with self.assertRaises(ValueError):
            execute(self.spark, source, root / "out", root / "report.json")


if __name__ == "__main__":
    unittest.main()
