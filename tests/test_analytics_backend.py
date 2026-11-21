"""Tests for the Phase 10 dashboard on a tiny fully synthetic Gold schema."""
from __future__ import annotations

from pathlib import Path
import sqlite3
import tempfile
import unittest

from src import analytics_backend as a


class AnalyticsBackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "synthetic_test.db"
        conn = sqlite3.connect(self.db)
        conn.executescript("""
            PRAGMA foreign_keys=ON;
            CREATE TABLE patients (patient_id TEXT PRIMARY KEY, full_name TEXT, gender TEXT, birth_date TEXT);
            CREATE TABLE encounters (encounter_id TEXT PRIMARY KEY, patient_id TEXT, start_time_utc TEXT);
            CREATE TABLE observation_events (
                observation_id TEXT PRIMARY KEY, patient_id TEXT, effective_datetime_utc TEXT, category TEXT);
            CREATE TABLE observation_values (
                observation_id TEXT, component_index INTEGER, measurement_code TEXT,
                measurement_display TEXT, value_numeric REAL, value_text TEXT, unit_code TEXT,
                quality_status TEXT, quality_flags TEXT);
            CREATE TABLE clinical_documents (document_id TEXT PRIMARY KEY, patient_id TEXT,
                status TEXT, document_date_utc TEXT);
            INSERT INTO patients VALUES ('p1','Alex Demo','male','1990-05-01');
            INSERT INTO patients VALUES ('p2','Morgan Demo','female','2002-10-01');
            INSERT INTO encounters VALUES ('e1','p1','2026-10-01T10:00:00+00:00');
            INSERT INTO encounters VALUES ('e2','p2','2026-11-02T10:00:00+00:00');
            INSERT INTO observation_events VALUES ('o1','p1','2026-10-07T10:00:00+00:00','vital-signs');
            INSERT INTO observation_events VALUES ('o2','p1','2026-11-07T10:00:00+00:00','vital-signs');
            INSERT INTO observation_events VALUES ('o3','p2','2026-10-08T10:00:00+00:00','vital-signs');
            INSERT INTO observation_events VALUES ('o4','p2','2026-11-09T10:00:00+00:00','laboratory');
            INSERT INTO observation_values VALUES ('o1',0,'8867-4','Heart rate',84,NULL,'/min','PASS_STRUCTURAL_CHECKS',NULL);
            INSERT INTO observation_values VALUES ('o2',0,'8867-4','Heart rate',88,NULL,'/min','REVIEW_REQUIRED','MIXED_UNIT_CODING');
            INSERT INTO observation_values VALUES ('o2',1,'8867-4','Heart rate',90,NULL,'bpm','REVIEW_REQUIRED','MIXED_UNIT_CODING');
            INSERT INTO observation_values VALUES ('o3',0,'8867-4','Heart rate',72,NULL,'/min','PASS_STRUCTURAL_CHECKS',NULL);
            INSERT INTO observation_values VALUES ('o4',0,'777-3','Blood test',15,NULL,'mg/dL','PASS_STRUCTURAL_CHECKS',NULL);
            INSERT INTO clinical_documents VALUES ('d1','p1','current','2026-11-07T10:00:00+00:00');
            INSERT INTO clinical_documents VALUES ('d2','p1','superseded','2026-10-07T10:00:00+00:00');
            INSERT INTO clinical_documents VALUES ('d3','p2','current','2026-11-09T10:00:00+00:00');
        """)
        conn.commit()
        conn.close()

    def tearDown(self):
        self.temp.cleanup()

    def test_population_counts_preserve_normalized_rows(self):
        k = a.kpis(self.db)
        self.assertEqual(k["population_patients"], 2)
        self.assertEqual(k["encounters"], 2)
        self.assertEqual(k["observation_events"], 4)
        self.assertEqual(k["observation_rows"], 5)
        self.assertEqual(k["flagged_rows"], 2)

    def test_patient_and_date_scope(self):
        k = a.kpis(self.db, patient_id="p1", start_date="2026-11-01", end_date="2026-11-30")
        self.assertEqual(k["population_patients"], 1)
        self.assertEqual(k["observation_events"], 1)
        self.assertEqual(k["observation_rows"], 2)
        self.assertEqual(k["flagged_rows"], 2)
        self.assertEqual(k["encounters"], 0)

    def test_patient_isolation_and_categories(self):
        labs = a.category_distribution(self.db, patient_id="p2", category="laboratory")
        self.assertEqual(labs, [{"category": "laboratory", "observation_rows": 1}])
        rows = a.latest_observations(self.db, patient_id="p1")
        self.assertEqual({r["patient_id"] for r in rows}, {"p1"})
        self.assertNotIn("o3", {r["observation_id"] for r in rows})

    def test_measurement_codes_units_never_merged(self):
        options = a.measurement_options(self.db, "p1")
        units = {(r["measurement_code"], r["unit_code"]) for r in options}
        self.assertEqual(units, {("8867-4", "/min"), ("8867-4", "bpm")})
        minute = a.measurement_series(self.db, "p1", "8867-4", "/min", include_flagged=True)
        bpm = a.measurement_series(self.db, "p1", "8867-4", "bpm", include_flagged=True)
        self.assertEqual([r["value_numeric"] for r in minute["rows"]], [84, 88])
        self.assertEqual([r["value_numeric"] for r in bpm["rows"]], [90])

    def test_flagged_rows_excluded_from_default_trend(self):
        rows = a.measurement_series(self.db, "p1", "8867-4", "/min")["rows"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["value_numeric"], 84)
        self.assertEqual(len(a.flagged_observations(self.db, patient_id="p1")), 2)

    def test_quality_flags_and_document_status(self):
        report = a.quality_summary(self.db)
        self.assertEqual(report["status"]["REVIEW_REQUIRED"], 2)
        self.assertEqual(report["flags"]["MIXED_UNIT_CODING"], 2)
        docs = a.clinical_document_status(self.db, patient_id="p1")
        self.assertEqual({r["status"]: r["count"] for r in docs}, {"current": 1, "superseded": 1})

    def test_unknown_patient_and_invalid_dates_rejected(self):
        with self.assertRaises(ValueError):
            a.kpis(self.db, patient_id="p0")
        with self.assertRaises(ValueError):
            a.kpis(self.db, start_date="2026-99-99")
        with self.assertRaises(ValueError):
            a.kpis(self.db, start_date="2026-11-01", end_date="2026-10-01")
        with self.assertRaises(ValueError):
            a.kpis(self.db, category="');DROP TABLE patients;--")

    def test_connection_is_read_only_and_closed(self):
        with a._db(self.db) as conn:
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute("DELETE FROM patients")
        self.assertEqual(len(a.list_patients(self.db)), 2)

    def test_activity_and_date_bounds(self):
        self.assertEqual(a.observation_date_bounds(self.db), ("2026-10-07", "2026-11-09"))
        months = a.observation_activity(self.db, granularity="month")
        self.assertEqual(months, [{"period": "2026-10", "observation_rows": 2},
                                  {"period": "2026-11", "observation_rows": 3}])
        encounters = a.encounter_activity(self.db, granularity="month")
        self.assertEqual(sum(r["encounters"] for r in encounters), 2)

    def test_empty_filters_and_record_limit(self):
        k = a.kpis(self.db, start_date="2030-01-01", end_date="2030-12-31")
        self.assertEqual(k["observation_rows"], 0)
        self.assertEqual(k["flagged_rows"], 0)
        self.assertEqual(a.measurement_options(self.db, "p1", start_date="2030-01-01"), [])
        with self.assertRaises(ValueError):
            a.latest_observations(self.db, limit=9999)


if __name__ == "__main__":
    unittest.main()
