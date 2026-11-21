"""Phase 11: tests for evidence-linked, patient-safe chart queries."""
from __future__ import annotations

import ast
from pathlib import Path
import sqlite3
import tempfile
import unittest

from src.contextual_charts import ChartTarget, chart_series, chart_targets


ROOT = Path(__file__).resolve().parents[1]


class ContextualChartsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "tiny_synthetic.db"
        conn = sqlite3.connect(self.db)
        conn.executescript("""
            CREATE TABLE patients (patient_id TEXT PRIMARY KEY, full_name TEXT);
            CREATE TABLE observation_events (
                observation_id TEXT PRIMARY KEY, patient_id TEXT, effective_datetime_utc TEXT, category TEXT);
            CREATE TABLE observation_values (
                observation_id TEXT, component_index INTEGER, measurement_code TEXT,
                measurement_display TEXT, value_numeric REAL, value_text TEXT,
                unit_code TEXT, quality_status TEXT, quality_flags TEXT);
            INSERT INTO patients VALUES ('p1','Pat One'),('p2','Pat Two');
            INSERT INTO observation_events VALUES
                ('a1','p1','2026-01-01T10:00:00+00:00','vital-signs'),
                ('a2','p1','2026-02-01T10:00:00+00:00','vital-signs'),
                ('a3','p1','2026-03-01T10:00:00+00:00','vital-signs'),
                ('b1','p2','2026-01-02T10:00:00+00:00','vital-signs');
            INSERT INTO observation_values VALUES
                ('a1',0,'8867-4','Heart rate',84,NULL,'/min','PASS_STRUCTURAL_CHECKS',NULL),
                ('a2',0,'8867-4','Heart rate',88,NULL,'/min','REVIEW_REQUIRED','MIXED_UNIT_CODING'),
                ('a3',0,'8867-4','Heart rate',90,NULL,'bpm','REVIEW_REQUIRED','MIXED_UNIT_CODING'),
                ('b1',0,'8867-4','Heart rate',42,NULL,'/min','PASS_STRUCTURAL_CHECKS',NULL);
        """)
        conn.commit()
        conn.close()
        self.context = {
            "patient": {"patient_id": "p1"},
            "sql_evidence": [
                {"topic": "vitals", "source_marker": "[SQL:vitals:a1]",
                 "record": {"observation_id":"a1", "measurement_code": "8867-4",
                            "measurement_display": "Heart rate", "unit_code": "/min",
                            "value_numeric": 84}},
                {"topic": "vitals", "source_marker": "[SQL:vitals:a2]",
                 "record": {"observation_id":"a2", "measurement_code": "8867-4",
                            "measurement_display": "Heart rate", "unit_code": "/min",
                            "value_numeric": 88}},
                {"topic": "vitals", "source_marker": "[SQL:vitals:a3]",
                 "record": {"observation_id":"a3", "measurement_code": "8867-4",
                            "measurement_display": "Heart rate", "unit_code": "bpm",
                            "value_numeric": 90}},
            ],
            "rag_evidence": [{"text": "The text says heart rate was 999", "source_marker": "[DOC:x#chunk:0]"}],
        }

    def tearDown(self):
        self.tmp.cleanup()

    def test_extract_code_and_unit_as_distinct_targets(self):
        choices = chart_targets(self.context, "p1")
        self.assertEqual(len(choices), 2)
        self.assertEqual([(c.code, c.unit) for c in choices], [("8867-4", "/min"), ("8867-4", "bpm")])

    def test_patient_scope_rejects_mismatch(self):
        with self.assertRaises(ValueError):
            chart_targets(self.context, "p2")
        with self.assertRaises(ValueError):
            chart_series(self.db, self.context, "p2", chart_targets(self.context, "p1")[0])

    def test_other_patient_rows_never_appear(self):
        target = chart_targets(self.context, "p1")[0]
        result = chart_series(self.db, self.context, "p1", target, include_flagged=True)
        self.assertEqual({r["patient_id"] for r in result["rows"]}, {"p1"})
        self.assertNotIn(42, [r["value_numeric"] for r in result["rows"]])

    def test_quality_flags_excluded_by_default(self):
        target = chart_targets(self.context, "p1")[0]
        result = chart_series(self.db, self.context, "p1", target)
        self.assertEqual([r["value_numeric"] for r in result["rows"]], [84])
        with_review = chart_series(self.db, self.context, "p1", target, include_flagged=True)
        self.assertEqual([r["value_numeric"] for r in with_review["rows"]], [84, 88])

    def test_units_do_not_mix(self):
        target = chart_targets(self.context, "p1")[1]
        result = chart_series(self.db, self.context, "p1", target, include_flagged=True)
        self.assertEqual([r["value_numeric"] for r in result["rows"]], [90])

    def test_rag_only_has_no_targets(self):
        context = {"patient": {"patient_id":"p1"}, "sql_evidence": [], "rag_evidence": self.context["rag_evidence"]}
        self.assertEqual(chart_targets(context, "p1"), [])

    def test_only_numeric_vitals_labs_can_be_plotted(self):
        context = {"patient": {"patient_id": "p1"}, "sql_evidence": [
            {"topic": "medications", "source_marker": "[SQL:medications:xx]", "record": {"measurement_code":"8867-4", "value_numeric":12}},
            {"topic": "vitals", "source_marker": "[SQL:vitals:xx]", "record": {"measurement_code":"8867-4", "value_numeric":None}},
            {"topic": "vitals", "source_marker": "[SQL:vitals:yy]", "record": {"measurement_code":"8867-4", "value_numeric":float('nan')}},
        ]}
        self.assertEqual(chart_targets(context,"p1"), [])

    def test_invalid_or_unlinked_target_rejected(self):
        wrong = ChartTarget("different", "/min", "Fake", "vitals", "[SQL:vitals:a1]")
        with self.assertRaises(ValueError):
            chart_series(self.db, self.context, "p1", wrong)

    def test_evidence_rows_explicitly_from_other_patient_skipped(self):
        other = dict(self.context)
        other["sql_evidence"] = [
            {"topic": "vitals", "source_marker":"[SQL:vitals:b1]",
             "record": {"patient_id":"p2", "measurement_code":"8867-4", "value_numeric": 42}},
        ]
        self.assertEqual(chart_targets(other, "p1"), [])

    def test_limits_and_read_only_storage(self):
        target = chart_targets(self.context, "p1")[0]
        limited = chart_series(self.db, self.context, "p1", target, include_flagged=True, limit=1)
        self.assertTrue(limited["truncated"])
        self.assertEqual(len(limited["rows"]), 1)
        with self.assertRaises(ValueError):
            chart_targets(self.context, "p1", max_targets=0)
        with sqlite3.connect(self.db) as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM observation_values").fetchone()[0], 4)

    def test_app_integration_remains_explicit_and_syntactically_valid(self):
        source = (ROOT / "Clinical_Assistant.py").read_text(encoding="utf-8")
        ast.parse(source)
        self.assertIn("ui_backend.ask_synthetic_patient(", source)
        self.assertIn("ui_backend.sync_patient_session(", source)
        self.assertIn("contextual_chart_panel(result, selected_patient_id", source)
        self.assertIn('contextual_chart_panel(message["result"], selected_patient_id', source)
        self.assertIn("SYNTHETIC DATA ONLY", source)
        self.assertIn("SUGGESTED_QUESTIONS", source)


if __name__ == "__main__":
    unittest.main()
