"""Standard-library tests for the targeted quality review."""
import csv
import json
import tempfile
import unittest
from pathlib import Path

from src.review_quality_findings import review


class QualityReviewTests(unittest.TestCase):
    def test_review_identifies_units_and_document_status(self):
        with tempfile.TemporaryDirectory() as root:
            input_dir, output_dir = Path(root) / "input", Path(root) / "output"
            input_dir.mkdir()
            fields = ["observation_id", "patient_id", "value_type", "unit_code",
                      "observation_code_system", "observation_code", "component_code_system", "component_code"]
            with (input_dir / "observations.csv").open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fields)
                writer.writeheader()
                for idx, unit in enumerate(("mg/L", "g/L", ""), 1):
                    writer.writerow({"observation_id": f"o{idx}", "patient_id": "p1", "value_type": "quantity",
                                     "unit_code": unit, "observation_code_system": "http://loinc.org",
                                     "observation_code": "1234-5", "component_code_system": "", "component_code": ""})
            with (input_dir / "clinical_documents.csv").open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=["document_id", "patient_id", "status", "text_content"])
                writer.writeheader()
                writer.writerow({"document_id": "d1", "patient_id": "p1", "status": "current", "text_content": "Synthetic report"})
                writer.writerow({"document_id": "d2", "patient_id": "p1", "status": "superseded", "text_content": "Old report"})
            out = review(input_dir, output_dir)
            self.assertEqual(out["quantity_rows_missing_unit_code"], 1)
            self.assertEqual(out["mixed_unit_groups"], 1)
            self.assertEqual(out["mixed_unit_affected_rows"], 2)
            self.assertEqual(out["rag_document_candidates_by_status_and_text_only"], 1)
            self.assertEqual(out["document_status_counts"]["superseded"], 1)
            self.assertEqual(json.loads((output_dir / "quality_review_summary.json").read_text())["status"],
                             "REVIEW_REQUIRED_NO_DATA_MODIFIED")


if __name__ == "__main__":
    unittest.main()
