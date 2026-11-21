"""Tests for Phase 12's non-mutating publication audit."""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.repository_preflight import (
    audit, has_literal_secret, is_sensitive_path, main,
)


class RepositoryPreflightTests(unittest.TestCase):
    def test_sensitive_paths_excluded(self):
        risky = [
            ".env", ".env.production", ".streamlit/secrets.toml",
            ".venv/Lib/site-packages/a.py", "data/gold/datahealth.db",
            "data/vectorstore/chroma/chroma.sqlite3", "reports/a.csv",
            "model.gguf", "credentials.json", "private.pem",
        ]
        for path in risky:
            with self.subTest(path=path):
                self.assertTrue(is_sensitive_path(path))

    def test_normal_project_files_allowed(self):
        for path in ("Clinical_Assistant.py", "src/a.py", "docs/README.md",
                     ".streamlit/config.toml", ".env.example"):
            with self.subTest(path=path):
                self.assertFalse(is_sensitive_path(path))

    def test_literal_secret_heuristic(self):
        self.assertTrue(has_literal_secret('API_KEY = "this_is_a_realish_sample_secret"'))
        self.assertFalse(has_literal_secret('API_KEY = os.environ["API_KEY"]'))
        self.assertFalse(has_literal_secret('API_KEY = "REPLACE_WITH_YOUR_KEY"'))

    def test_uninitialized_git_is_not_called_published(self):
        with tempfile.TemporaryDirectory() as dirname:
            p = Path(dirname)
            result = audit(p)
            self.assertNotEqual(result["cloud_application_status"], "READY")
            self.assertTrue(result["missing_expected_components"])

    def test_git_tracked_sensitive_path_blocks_publication(self):
        with tempfile.TemporaryDirectory() as dirname:
            p = Path(dirname)
            subprocess.run(["git", "init", "-q", str(p)], check=True, capture_output=True)
            (p / ".env").write_text('API_KEY="not-a-real-key"', encoding="utf-8")
            subprocess.run(["git", "-C", str(p), "add", "-f", ".env"], check=True, capture_output=True)
            result = audit(p)
            self.assertIn(".env", result["tracked_sensitive_or_generated_paths"])
            self.assertEqual(result["git_publication_review_status"], "BLOCKED")

    def test_no_changes_to_source(self):
        with tempfile.TemporaryDirectory() as dirname:
            p = Path(dirname)
            (p / "marker.txt").write_text("untouched", encoding="utf-8")
            result = audit(p)
            self.assertEqual((p / "marker.txt").read_text(), "untouched")
            self.assertIn("git_state", result)

    def test_report_written_to_output(self):
        with tempfile.TemporaryDirectory() as dirname:
            p = Path(dirname)
            status = main(["--root", str(p), "--output", "reports/deployment/report.json"])
            self.assertEqual(status, 2)  # Expected components absent in empty directory
            self.assertTrue((p / "reports/deployment/report.json").is_file())


if __name__ == "__main__":
    unittest.main()
