"""Regression tests for synthetic patient-name extraction and Gold display fields."""
from __future__ import annotations

import csv
from pathlib import Path
import json
import sqlite3
import tempfile
import unittest

from src.transform_fhir import extract_patient_name, transform
from src.build_silver import build_silver
from src.build_gold import create_gold
from src.query_gold import run_query


class PatientNamesTest(unittest.TestCase):
    def test_name_preference_and_middle_names(self):
        example = {"name": [
            {"use": "nickname", "given": ["Abe"], "family": "H."},
            {"use": "official", "given": ["Abraham100", "James"], "family": "Hackett68"},
        ]}
        self.assertEqual(extract_patient_name(example), {
            "first_name": "Abraham100", "last_name": "Hackett68",
            "full_name": "Abraham100 James Hackett68",
        })
        self.assertEqual(extract_patient_name({}), {
            "first_name": "", "last_name": "", "full_name": "",
        })

    def test_fhir_to_gold_preserves_names_and_ids(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "raw"
            source.mkdir()
            records = [
                {"resourceType": "Patient", "id": "p001", "gender": "male", "birthDate": "2026-07-01",
                 "name": [{"use": "official", "given": ["Abraham100"], "family": "Hackett68"}]},
                {"resourceType": "Patient", "id": "p002", "gender": "unknown"},
                {"resourceType": "Encounter", "id": "enc001", "status": "finished",
                 "subject": {"reference": "urn:uuid:p001"}, "period": {"start": "2026-07-01T00:00:00+00:00"}},
                {"resourceType": "Observation", "id": "obs001", "status": "final",
                 "subject": {"reference": "urn:uuid:p001"},
                 "encounter": {"reference": "urn:uuid:enc001"},
                 "code": {"coding": [{"system": "http://loinc.org", "code": "8867-4", "display": "Heart rate"}]},
                 "effectiveDateTime": "2026-07-01T00:00:00+00:00",
                 "valueQuantity": {"value": 82, "unit": "/min", "code": "/min", "system": "http://unitsofmeasure.org"}},
            ]
            (source / "synthetic.json").write_text(json.dumps({"resourceType": "Bundle", "type": "transaction", "entry": [{"resource": item} for item in records]}), encoding="utf-8")
            transformed = root / "processed"
            silver = root / "silver"
            db = root / "gold" / "datahealth.db"
            transform(source, transformed)
            with (transformed / "patients.csv").open(newline="", encoding="utf-8") as handle:
                patients = list(csv.DictReader(handle))
            self.assertEqual(patients[0]["full_name"], "Abraham100 Hackett68")
            self.assertEqual(patients[1]["full_name"], "")
            build_silver(transformed, silver, root / "silver_reports")
            gold_summary = create_gold(silver, db, root / "gold_reports")
            self.assertEqual(gold_summary["patients_with_full_name"], 1)
            self.assertEqual(gold_summary["foreign_key_violations"], 0)
            self.assertEqual(gold_summary["gold_table_counts"]["observation_values"], 1)
            rows = run_query(db, "list-patients", limit=10)
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["patient_id"], "p001")
            self.assertEqual(rows[0]["first_name"], "Abraham100")
            self.assertEqual(rows[0]["last_name"], "Hackett68")
            self.assertEqual(rows[0]["full_name"], "Abraham100 Hackett68")
            self.assertIsNone(rows[1]["full_name"])
            overview = run_query(db, "patient-overview", patient_id="p001")
            self.assertEqual(overview[0]["full_name"], "Abraham100 Hackett68")
            self.assertEqual(overview[0]["observation_event_count"], 1)
            conn = sqlite3.connect(db)
            try:
                self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
