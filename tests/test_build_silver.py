"""Basic unit test for conservative Silver Layer rules."""
from pathlib import Path
import csv
import tempfile
import unittest

from src.build_silver import SOURCE_TABLES, build_silver
from src.transform_fhir import SCHEMAS


class SilverLayerTest(unittest.TestCase):
    def test_preserves_all_rows_flags_unit_mismatch_and_filters_documents(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            source = folder / "transformed"
            source.mkdir()
            tables = {name: [] for name in SOURCE_TABLES}
            tables["patients"] = [{"patient_id": "P001"}]
            tables["encounters"] = [{"encounter_id": "E001", "patient_id": "P001"}]
            base = {"observation_id": "O1", "patient_id": "P001", "encounter_id": "E001",
                    "observation_code_system": "http://loinc.org", "observation_code": "788-0",
                    "value_type": "quantity", "value_numeric": "12", "effective_datetime": "2026-01-01"}
            tables["observations"] = [
                {**base, "unit_code": "%"},
                {**base, "observation_id": "O2", "unit_code": "fL"},
                {**base, "observation_id": "O3", "unit_code": ""},
            ]
            tables["clinical_documents"] = [
                {"document_id": "D1", "patient_id": "P001", "status": "current", "text_content": "Synthetic test note."},
                {"document_id": "D2", "patient_id": "P001", "status": "superseded", "text_content": "Old note."},
            ]
            for table_name in SOURCE_TABLES:
                with (source / f"{table_name}.csv").open("w", newline="", encoding="utf-8") as stream:
                    writer = csv.DictWriter(stream, fieldnames=SCHEMAS[table_name])
                    writer.writeheader()
                    for row in tables[table_name]:
                        writer.writerow(row)
            silver = folder / "silver"
            reports = folder / "reports"
            summary = build_silver(source, silver, reports)
            self.assertEqual(summary["silver_observation_rows"], 3)
            self.assertEqual(summary["observations_flagged_for_review"], 3)
            self.assertEqual(summary["observation_flag_counts"]["MIXED_UNIT_CODING"], 3)
            self.assertEqual(summary["observation_flag_counts"]["MISSING_UNIT_CODE"], 1)
            self.assertEqual(summary["rag_preliminary_candidates"], 1)
            self.assertTrue((reports / "silver_validation_report.md").is_file())
            with (silver / "observations.csv").open(newline="", encoding="utf-8") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual([r["unit_code"] for r in rows], ["%", "fL", ""])


if __name__ == "__main__":
    unittest.main()
