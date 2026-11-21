"""Self-contained tests for the DataHealth AI educational SQLite Gold Layer."""
from __future__ import annotations

import csv
from pathlib import Path
import sqlite3
import tempfile
import unittest

from src.build_gold import create_gold
from src.query_gold import run_query


def write_csv(path: Path, rows: list[dict], headers: list[str]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


class TestGoldLayer(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.silver = self.root / "silver"
        self.db = self.root / "gold" / "health.db"
        self.reports = self.root / "reports"
        files = {
            "patients": (["patient_id", "gender", "birth_date", "source_file"], [
                {"patient_id": "synthetic-1", "gender": "female", "birth_date": "2000-01-01", "source_file": "demo.json"}]),
            "encounters": (["encounter_id", "patient_id", "status", "start_time"], [
                {"encounter_id": "visit-1", "patient_id": "synthetic-1", "status": "finished", "start_time": "2026-11-01T09:30:00+00:00"}]),
            "observations": (["observation_id", "patient_id", "encounter_id", "status", "category", "observation_code_system", "observation_code", "observation_display", "component_index", "component_code_system", "component_code", "component_display", "value_type", "value_numeric", "value_unit", "unit_code", "unit_system", "value_text", "effective_datetime", "issued_datetime", "quality_status", "quality_flags", "source_file"], [
                {"observation_id": "pressure-1", "patient_id": "synthetic-1", "encounter_id": "visit-1", "category": "vital-signs", "observation_code": "85354-9", "observation_display": "Blood pressure", "component_index": "1", "component_code": "8480-6", "component_display": "Systolic blood pressure", "value_type": "quantity", "value_numeric": "122", "unit_code": "mm[Hg]", "effective_datetime": "2026-11-01T09:30:00+00:00", "quality_status": "PASS_STRUCTURAL_CHECKS"},
                {"observation_id": "pressure-1", "patient_id": "synthetic-1", "encounter_id": "visit-1", "category": "vital-signs", "observation_code": "85354-9", "observation_display": "Blood pressure", "component_index": "2", "component_code": "8462-4", "component_display": "Diastolic blood pressure", "value_type": "quantity", "value_numeric": "82", "unit_code": "mm[Hg]", "effective_datetime": "2026-11-01T09:30:00+00:00", "quality_status": "REVIEW_REQUIRED", "quality_flags": "MIXED_UNIT_CODING"}]),
            "conditions": (["condition_id", "patient_id", "encounter_id"], []),
            "diagnostic_reports": (["report_id", "patient_id", "encounter_id", "status", "code"], [
                {"report_id": "report-1", "patient_id": "synthetic-1", "encounter_id": "visit-1", "status": "final", "code": "test-panel"}]),
            "diagnostic_report_results": (["report_id", "observation_id"], [
                {"report_id": "report-1", "observation_id": "pressure-1"}]),
            "medication_requests": (["medication_request_id", "patient_id", "encounter_id"], []),
            "clinical_documents": (["document_id", "patient_id", "status", "document_date", "document_type", "rag_candidate_status", "rag_review_flags"], [
                {"document_id": "doc-current", "patient_id": "synthetic-1", "status": "current", "document_date": "2026-11-01T09:30:00+00:00", "rag_candidate_status": "PRELIMINARY_ONLY_NOT_AUTHORIZED"},
                {"document_id": "doc-old", "patient_id": "synthetic-1", "status": "superseded", "document_date": "2026-10-01T09:30:00+00:00", "rag_candidate_status": "EXCLUDED_PENDING_REVIEW", "rag_review_flags": "NON_CURRENT_DOCUMENT"}]),
        }
        for name, (headers, rows) in files.items():
            write_csv(self.silver / f"{name}.csv", rows, headers)

    def test_gold_retains_components_and_flags(self):
        summary = create_gold(self.silver, self.db, self.reports)
        self.assertEqual(summary["gold_table_counts"]["observation_events"], 1)
        self.assertEqual(summary["gold_table_counts"]["observation_values"], 2)
        self.assertEqual(summary["flagged_observation_rows"], 1)
        self.assertEqual(summary["preliminary_rag_document_metadata_rows"], 1)
        self.assertEqual(summary["foreign_key_violations"], 0)
        self.assertEqual(len(run_query(self.db, "list-patients")), 1)
        results = run_query(self.db, "latest-observations", "synthetic-1")
        self.assertEqual(sorted(r["value_numeric"] for r in results), [82.0, 122.0])
        with sqlite3.connect(self.db) as conn:
            n = conn.execute("SELECT COUNT(*) FROM v_rag_preliminary_document_metadata").fetchone()[0]
            self.assertEqual(n, 1)

    def test_foreign_key_violation_is_not_silently_ignored(self):
        path = self.silver / "encounters.csv"
        write_csv(path, [{"encounter_id": "bad-visit", "patient_id": "nonexistent"}], ["encounter_id", "patient_id"])
        with self.assertRaises(sqlite3.IntegrityError):
            create_gold(self.silver, self.db, self.reports)
        self.assertFalse(self.db.exists())


if __name__ == "__main__":
    unittest.main()
