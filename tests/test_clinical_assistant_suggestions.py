r"""Static tests for the Clinical Assistant navigation and suggested prompts.

Run inside the DataHealth AI repository with:
    .\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_clinical_assistant_suggestions.py" -v
"""
from pathlib import Path
import ast
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "Clinical_Assistant.py"


class ClinicalAssistantSuggestionsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SOURCE.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)

    def test_new_entrypoint_has_valid_syntax(self):
        self.assertGreater(len(self.tree.body), 0)

    def test_clinical_patient_backend_is_unchanged(self):
        for marker in (
            "ui_backend.ask_synthetic_patient(",
            "ui_backend.sync_patient_session(",
            "ui_backend.source_summary(",
        ):
            self.assertIn(marker, self.source)

    def test_six_suggestions_and_routing_categories(self):
        for name in (
            "Latest vital signs", "Laboratory results", "Recorded conditions",
            "Clinical history", "Medication comparison", "Compare vitals & notes",
        ):
            self.assertIn(name, self.source)
        self.assertIn('if mode == "sql":', self.source)
        self.assertIn('elif mode == "rag":', self.source)

    def test_suggestions_submit_to_original_chat_flow(self):
        self.assertIn("quick_prompt = prompt", self.source)
        self.assertIn("question = typed_question or quick_prompt", self.source)
        self.assertIn('"chat_messages"', self.source)

    def test_safety_warning_and_source_display_remain(self):
        self.assertIn("SYNTHETIC DATA ONLY", self.source)
        self.assertIn("Source ID validation does not establish clinical accuracy.", self.source)
        self.assertIn("evidence_panel(result)", self.source)


if __name__ == "__main__":
    unittest.main()
