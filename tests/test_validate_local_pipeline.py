"""Standard-library-only tests for Phase 20 audit helpers.

These tests do not read or change any project datasets and do not need Spark.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
import tempfile
import unittest
from pathlib import Path

from src.validate_local_pipeline import compare_sqlite_counts, equal_counts, records_to_counts


class LocalPipelineAuditHelperTests(unittest.TestCase):
    def test_compare_equal_counts_ignores_mapping_order(self):
        self.assertTrue(equal_counts({"Observation": 2, "Patient": 1},
                                     {"Patient": 1, "Observation": 2}))
        self.assertFalse(equal_counts({"Patient": 1}, {"Patient": 2}))

    def test_aggregate_rows_with_nullable_label(self):
        rows = [{"category": None, "count": 2}, {"category": "vital-signs", "count": 5}]
        self.assertEqual(records_to_counts(rows, "category", "count"),
                         {"(null)": 2, "vital-signs": 5})

    def test_duplicate_group_labels_rejected(self):
        with self.assertRaises(ValueError):
            records_to_counts([{"k": "a", "v": 1}, {"k": "a", "v": 1}], "k", "v")

    def test_missing_sqlite_is_optional(self):
        with tempfile.TemporaryDirectory() as folder:
            result = compare_sqlite_counts(Path(folder) / "missing.db", {"Patient": 1})
        self.assertEqual(result["status"], "NOT_FOUND")

    def test_sqlite_comparison_is_read_only_and_informational(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / "db.sqlite"
            with closing(sqlite3.connect(db)) as conn:
                with conn:
                    conn.execute("CREATE TABLE patients (patient_id TEXT)")
                    conn.execute("INSERT INTO patients VALUES ('invented')")
            result = compare_sqlite_counts(db, {"Patient": 2})
            self.assertEqual(result["status"], "COMPARED_INFORMATIONALLY")
            self.assertFalse(result["tables"]["patients"]["equal"])
            self.assertEqual(result["tables"]["patients"]["difference_sqlite_minus_raw"], -1)
            with closing(sqlite3.connect(db)) as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM patients").fetchone()[0], 1)


    def test_sqlite_comparison_closes_read_only_connection(self):
        """The Phase 20 helper must not leave SQLite files locked on Windows."""
        from unittest.mock import patch

        class TrackingConnection(sqlite3.Connection):
            was_closed = False

            def close(self):
                self.was_closed = True
                return super().close()

        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / "db.sqlite"
            with closing(sqlite3.connect(db)) as conn:
                with conn:
                    conn.execute("CREATE TABLE patients (patient_id TEXT)")

            original_connect = sqlite3.connect
            opened = []

            def tracked_connect(*args, **kwargs):
                connection = original_connect(*args, factory=TrackingConnection, **kwargs)
                opened.append(connection)
                return connection

            with patch("src.validate_local_pipeline.sqlite3.connect", side_effect=tracked_connect):
                result = compare_sqlite_counts(db, {"Patient": 0})

            self.assertEqual(result["status"], "COMPARED_INFORMATIONALLY")
            self.assertEqual(len(opened), 1)
            self.assertTrue(opened[0].was_closed)


if __name__ == "__main__":
    unittest.main()
