"""Unit tests for Phase 18. Uses ONLY generated fictional encounter timestamps."""
import contextlib
from datetime import date, datetime, timezone
import io
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

from src.workload_forecast import (
    chronological_split, features, metrics, month_label, month_number,
    monthly_audit, parse_utc, read_gold_encounters, run_cli, run_models,
)

AS_OF = date(2026, 11, 22)


def make_rows(months=60, per_month=8):
    start = month_number(AS_OF) - months
    return [
        (f"DEMO-E-{i:03d}-{j:03d}", f"{month_label(start+i)}-10T10:30:00+00:00")
        for i in range(months) for j in range(per_month + (i % 4))
    ]


class AuditTests(unittest.TestCase):
    def test_parse_utc_rejects_naive(self):
        self.assertIsNone(parse_utc("2026-10-01T12:00:00"))

    def test_parse_utc_accepts_z(self):
        self.assertEqual(parse_utc("2026-10-10T00:00:00Z").tzinfo, timezone.utc)

    def test_month_label(self):
        self.assertEqual(month_label(month_number(date(2026, 10, 1))), "2026-10")

    def test_excludes_incomplete_month(self):
        series, audit = monthly_audit(make_rows(60, 1) + [
            ("current", "2026-11-01T00:00:00+00:00"),
            ("future", "2027-02-01T00:00:00+00:00"),
        ], AS_OF)
        self.assertEqual(series[-1]["period"], "2026-10")
        self.assertEqual(audit["excluded_current_or_future_month"], 2)

    def test_duplicates_counted_once(self):
        rows = make_rows()
        _, audit = monthly_audit(rows + [rows[0]], AS_OF)
        self.assertEqual(audit["duplicate_encounter_ids"], 1)
        self.assertEqual(audit["encounters_in_window"], len(rows))

    def test_missing_date_excluded(self):
        _, audit = monthly_audit(make_rows() + [("bad", None)], AS_OF)
        self.assertEqual(audit["invalid_or_missing_start_time"], 1)

    def test_sparse_dataset_blocks_model(self):
        series, audit = monthly_audit(make_rows(2, 1), AS_OF)
        self.assertEqual(audit["status"], "INSUFFICIENT_FOR_MEANINGFUL_MODELING")
        with self.assertRaises(ValueError):
            run_models(series, audit)

    def test_older_history_excluded(self):
        _, audit = monthly_audit(make_rows() + [("old", "2000-01-05T00:00:00+00:00")], AS_OF)
        self.assertEqual(audit["excluded_before_window"], 1)

    def test_window_bounds(self):
        with self.assertRaises(ValueError):
            monthly_audit(make_rows(), AS_OF, 12)

    def test_gaps_preserved_as_zero_months(self):
        sparse = [(f"ONLY-{i:03d}", f"{month_label(month_number(AS_OF)-60+i)}-10T10:30:00+00:00")
                  for i in range(0, 60, 2)]
        series, audit = monthly_audit(sparse, AS_OF)
        self.assertEqual(len(series), 60)
        self.assertGreater(audit["months_without_encounters"], 0)

    def test_read_gold_encounters_read_only(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / 'gold.db'
            with sqlite3.connect(db) as conn:
                conn.execute('CREATE TABLE encounters (encounter_id TEXT, start_time_utc TEXT)')
                conn.execute('INSERT INTO encounters VALUES (?, ?)', ("E1", "2026-10-12T00:00:00+00:00"))
            conn.close()
            self.assertEqual(read_gold_encounters(db), [("E1", "2026-10-12T00:00:00+00:00")])

    def test_read_gold_requires_schema(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / 'bad.db'
            with sqlite3.connect(db) as conn:
                conn.execute('CREATE TABLE encounters (encounter_id TEXT)')
            conn.close()
            with self.assertRaisesRegex(ValueError, "start_time_utc"):
                read_gold_encounters(db)


class ForecastTests(unittest.TestCase):
    def setUp(self):
        self.series, self.audit = monthly_audit(make_rows(), AS_OF)

    def test_features_have_twelve_month_warmup(self):
        x, y, labels, offsets = features(self.series)
        self.assertEqual(len(x), 48)
        self.assertEqual(len(y), 48)
        self.assertEqual(labels[0], self.series[12]["period"])
        self.assertEqual(offsets[0], 12)

    def test_lag_features_use_past_only(self):
        x, y, _, _ = features(self.series)
        self.assertEqual(x[0][0], self.series[11]["count"])
        self.assertEqual(x[0][4], self.series[0]["count"])
        self.assertEqual(y[0], self.series[12]["count"])

    def test_split_chronological_and_disjoint(self):
        tr, va, te = chronological_split(48)
        self.assertEqual(tr.stop, va.start)
        self.assertEqual(va.stop, te.start)
        self.assertEqual(te.stop, 48)

    def test_short_split_rejected(self):
        with self.assertRaises(ValueError):
            chronological_split(20)

    def test_metrics_correct(self):
        m = metrics([10, 20], [12, 16])
        self.assertAlmostEqual(m["mae"], 3.0)
        self.assertAlmostEqual(m["rmse"], (10 ** 0.5), places=4)
        self.assertAlmostEqual(m["wape_pct"], 20.0)

    def test_metrics_zero_wape_is_null(self):
        self.assertIsNone(metrics([0, 0], [1, 2])["wape_pct"])

    def test_run_models_selects_from_prespecified_candidates(self):
        result, preds = run_models(self.series, self.audit)
        self.assertIn(result["selected_model_by_validation_mae"], result["candidate_models"])
        self.assertEqual(len(preds), result["test_months"])
        self.assertTrue(all(p["predicted_encounters"] >= 0 for p in preds))
        self.assertTrue(all(p["month"] > result["validation_last_month"] for p in preds))

    def test_cli_audit_writes_no_model_predictions(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            db = root / "test.db"
            with sqlite3.connect(db) as conn:
                conn.execute('CREATE TABLE encounters (encounter_id TEXT PRIMARY KEY, start_time_utc TEXT)')
                conn.executemany('INSERT INTO encounters VALUES (?, ?)', make_rows())
            conn.close()
            out = root / "reports"
            with contextlib.redirect_stdout(io.StringIO()):
                code = run_cli(['audit', '--database', str(db), '--output', str(out),
                                '--as-of', '2026-11-22'])
            self.assertEqual(code, 0)
            self.assertTrue((out/'data_audit.json').is_file())
            self.assertFalse((out/'evaluation_summary.json').exists())
            self.assertTrue((out/'monthly_encounters.csv').is_file())


if __name__ == "__main__":
    unittest.main()
