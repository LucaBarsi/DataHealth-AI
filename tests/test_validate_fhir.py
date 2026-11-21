"""Basic unit tests for the quality audit; run with: python -m unittest discover -s tests."""
from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from src.validate_fhir import TABLES, audit


class FhirAuditTests(unittest.TestCase):
    def _create_tables(self, folder: Path) -> None:
        cols = {
            "patients": ["patient_id", "gender", "birth_date"],
            "encounters": ["encounter_id", "patient_id", "start_time", "end_time"],
            "observations": [
                "observation_id", "component_index", "patient_id", "encounter_id",
                "observation_code", "observation_code_system", "component_code", "component_code_system",
                "status", "value_type", "value_numeric", "unit_code",
            ],
            "conditions": ["condition_id", "patient_id", "encounter_id"],
            "diagnostic_reports": ["report_id", "patient_id", "encounter_id"],
            "diagnostic_report_results": ["report_id", "observation_id"],
            "medication_requests": ["medication_request_id", "patient_id", "encounter_id"],
            "clinical_documents": ["document_id", "patient_id", "status", "text_content"],
        }
        data = {
            "patients": [{"patient_id": "p1", "gender": "male", "birth_date": "2026-07-01"}],
            "encounters": [{"encounter_id": "e1", "patient_id": "p1", "start_time": "2026-07-01T00:00:00Z", "end_time": "2026-07-01T00:15:00Z"}],
            "observations": [
                {"observation_id": "o1", "component_index": "1", "patient_id": "p1", "encounter_id": "e1", "observation_code": "85354-9", "observation_code_system": "http://loinc.org", "component_code": "8480-6", "component_code_system": "http://loinc.org", "status": "final", "value_type": "quantity", "value_numeric": "120", "unit_code": "mm[Hg]"},
                {"observation_id": "o1", "component_index": "2", "patient_id": "p1", "encounter_id": "e1", "observation_code": "85354-9", "observation_code_system": "http://loinc.org", "component_code": "8462-4", "component_code_system": "http://loinc.org", "status": "final", "value_type": "quantity", "value_numeric": "80", "unit_code": "mm[Hg]"},
            ],
            "conditions": [], "diagnostic_reports": [{"report_id": "r1", "patient_id": "p1", "encounter_id": "e1"}],
            "diagnostic_report_results": [{"report_id": "r1", "observation_id": "o1"}],
            "medication_requests": [],
            "clinical_documents": [{"document_id": "d1", "patient_id": "p1", "status": "superseded", "text_content": "Old note"}],
        }
        for table in TABLES:
            with (folder / f"{table}.csv").open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=cols[table]); writer.writeheader(); writer.writerows(data[table])

    def test_valid_component_references_are_not_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); raw = root / "processed"; raw.mkdir()
            self._create_tables(raw)
            result = audit(raw, root / "reports", make_charts=False)
            self.assertEqual(result["unique_observation_ids"], 1)
            self.assertEqual(result["observation_rows"], 2)
            self.assertEqual(result["overall_status"], "NO_CRITICAL_ISSUES_FOUND")
            issues = (root / "reports" / "quality_issues.csv").read_text(encoding="utf-8")
            self.assertIn("document_not_current", issues)
            self.assertNotIn("duplicate_business_key", issues)

    def test_unknown_patient_is_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); raw = root / "processed"; raw.mkdir()
            self._create_tables(raw)
            path = raw / "conditions.csv"
            with path.open("a", encoding="utf-8", newline="") as handle:
                csv.writer(handle).writerow(["c1", "missing", ""])
            result = audit(raw, root / "reports", make_charts=False)
            self.assertEqual(result["overall_status"], "REVIEW_REQUIRED")
            issues = (root / "reports" / "quality_issues.csv").read_text(encoding="utf-8")
            self.assertIn("unresolved_patient_reference", issues)


if __name__ == "__main__":
    unittest.main()
