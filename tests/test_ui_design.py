"""Lightweight static safety and packaging checks for the branded Streamlit UI.

These checks do not start Streamlit or access medical records.
"""
from pathlib import Path
import ast
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class UIVisualDesignTests(unittest.TestCase):
    def test_app_is_valid_python(self):
        ast.parse((PROJECT_ROOT / "app.py").read_text(encoding="utf-8"))

    def test_existing_scoped_backend_is_reused(self):
        source = (PROJECT_ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn("ui_backend.ask_synthetic_patient(", source)
        self.assertIn("ui_backend.sync_patient_session(", source)
        self.assertIn("ui_backend.source_summary(", source)

    def test_identity_and_warning_exist(self):
        source = (PROJECT_ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn("Data that connects.", source)
        self.assertIn("SYNTHETIC DATA ONLY", source)
        self.assertIn("Source ID validation does not establish clinical accuracy.", source)

    def test_css_and_theme_exist(self):
        self.assertIn(".dh-hero", (PROJECT_ROOT / "assets" / "datahealth.css").read_text(encoding="utf-8"))
        self.assertIn('base = "dark"', (PROJECT_ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
