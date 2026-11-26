"""Pure-stdlib tests: dashboard reads Phase 18 aggregated reports, never retrains."""
from __future__ import annotations

import csv
import json
from pathlib import Path
import tempfile
import unittest
from src.ml_dashboard_data import read_report


class ReportReaderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        months = [f"2026-{i:02d}" for i in range(1, 7)]
        audit = {
            "status": "SUFFICIENT_FOR_EXPLORATORY_TEST", "window_months": 6,
            "encounters_in_window": 66, "first_complete_month": months[0], "last_complete_month": months[-1],
        }
        metrics = {"mae": 2.0, "rmse": 2.3, "wape_pct": 15.0}
        summary = {
            "status": "EXPLORATORY_ONLY_NOT_FOR_OPERATIONAL_USE", "candidate_models": ["last_month", "random_forest"],
            "selected_model_by_validation_mae": "random_forest",
            "validation_metrics": {"last_month": metrics, "random_forest": metrics},
            "test_metrics_including_diagnostics_only": {"last_month": metrics, "random_forest": metrics},
            "test_months": 2, "test_first_month": "2026-05", "test_last_month": "2026-06",
        }
        (self.path / "data_audit.json").write_text(json.dumps(audit), encoding="utf8")
        (self.path / "evaluation_summary.json").write_text(json.dumps(summary), encoding="utf8")
        self.write_csv("monthly_encounters.csv", ["period", "count"],
                       [[m, i + 8] for i, m in enumerate(months)])
        # counts 8+9+10+11+12+13 = 63, adjust audit below
        audit["encounters_in_window"] = 63
        (self.path / "data_audit.json").write_text(json.dumps(audit), encoding="utf8")
        self.write_csv("test_predictions.csv",
                       ["month", "actual_encounters", "selected_model", "predicted_encounters", "last_month_baseline", "seasonal_12_baseline"],
                       [["2026-05", "12", "random_forest", "11", "11", "9"],
                        ["2026-06", "13", "random_forest", "11", "12", "10"]])

    def write_csv(self, filename, headers, rows):
        with (self.path / filename).open("w", newline="", encoding="utf8") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            writer.writerows(rows)

    def test_load_valid_existing_reports(self):
        data = read_report(self.path)
        self.assertEqual(data["selected_model"], "random_forest")
        self.assertEqual(len(data["monthly"]), 6)
        self.assertEqual(len(data["predictions"]), 2)
        self.assertEqual(len(data["models"]), 2)

    def test_missing_file_is_explained(self):
        (self.path / "test_predictions.csv").unlink()
        with self.assertRaisesRegex(FileNotFoundError, "test_predictions.csv"):
            read_report(self.path)

    def test_model_mismatch_is_rejected(self):
        (self.path / "test_predictions.csv").write_text(
            (self.path / "test_predictions.csv").read_text().replace("random_forest", "ridge"), encoding="utf8")
        with self.assertRaisesRegex(ValueError, "different model"):
            read_report(self.path)

    def test_disagreeing_history_is_rejected(self):
        (self.path / "monthly_encounters.csv").write_text(
            (self.path / "monthly_encounters.csv").read_text().replace("2026-05,12", "2026-05,99"), encoding="utf8")
        with self.assertRaisesRegex(ValueError, "does not match"):
            read_report(self.path)

    def test_report_has_no_patient_identifiers(self):
        data = read_report(self.path)
        self.assertEqual(set(data["monthly"][0]), {"month", "encounters"})
        self.assertEqual(set(data["predictions"][0]), {"month", "observed", "predicted", "last_month", "seasonal_12"})

    def test_invalid_duplicate_month_is_rejected(self):
        text = (self.path / "monthly_encounters.csv").read_text()
        (self.path / "monthly_encounters.csv").write_text(text.replace("2026-02,9", "2026-01,9"), encoding="utf8")
        with self.assertRaisesRegex(ValueError, "distinct"):
            read_report(self.path)

    def test_nonfinite_prediction_is_rejected(self):
        text = (self.path / "test_predictions.csv").read_text()
        (self.path / "test_predictions.csv").write_text(text.replace("2026-05,12,random_forest,11", "2026-05,12,random_forest,nan"), encoding="utf8")
        with self.assertRaisesRegex(ValueError, "finite"):
            read_report(self.path)


if __name__ == "__main__":
    unittest.main()
