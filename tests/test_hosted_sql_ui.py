"""Offline integration tests for the SQL-only hosted deployment adapter."""
from pathlib import Path
import unittest
from unittest.mock import patch

from src import ui_backend


def scoped_evidence():
    return {
        "patient": {"patient_id": "synthetic-001"},
        "question": "Show latest vital signs.",
        "route": {"mode": "sql", "use_rag": False},
        "sql_evidence": [
            {"source_marker": "[SQL:vitals:obs-001]", "topic": "vitals", "record": {
                "observation_id": "obs-001", "measurement_display": "Heart rate",
                "value_numeric": 74,
            }}
        ],
        "rag_evidence": [],
    }


class HostedSQLBackendTests(unittest.TestCase):
    def setUp(self):
        self.database = Path(__file__).parent / "test-fixture.db"
        self.index = Path(__file__).parent
        self.expected_answer = {
            "answer": "Recorded heart rate 74 [SQL:vitals:obs-001].",
            "status": "CITATION_IDS_VALID",
            "reason": "HOSTED_QWEN",
        }

    def ask(self, **kwargs):
        return ui_backend.ask_synthetic_patient(
            database=self.database, index_dir=self.index,
            patient_id="synthetic-001",
            question="Show latest vital signs.",
            mode="sql", allow_rag=False, **kwargs,
        )

    @patch("src.ui_backend.Path.is_file", return_value=True)
    @patch("src.ui_backend.hybrid_assistant.retrieve_hybrid")
    @patch("src.ui_backend.reliable_assistant.generate_reliable_answer")
    def test_hosted_generator_replaces_local_ollama_generation(
        self, local_generate, retrieval, is_file
    ):
        retrieval.return_value = scoped_evidence()
        with patch("src.ui_backend.hybrid_assistant.route_question",
                   return_value={"mode": "sql", "use_rag": False}):
            generated = []
            def hosted(evidence):
                generated.append(evidence)
                return self.expected_answer

            result = self.ask(answer_generator=hosted)
        self.assertEqual(result["response"]["reason"], "HOSTED_QWEN")
        self.assertEqual(len(generated), 1)
        self.assertEqual(generated[0]["patient"]["patient_id"], "synthetic-001")
        local_generate.assert_not_called()

    @patch("src.ui_backend.Path.is_file", return_value=True)
    @patch("src.ui_backend.hybrid_assistant.retrieve_hybrid")
    def test_rag_route_is_blocked_before_retrieval(self, retrieval, is_file):
        with patch("src.ui_backend.hybrid_assistant.route_question",
                   return_value={"mode": "rag", "use_rag": True}):
            with self.assertRaisesRegex(ValueError, "Hosted RAG is not available"):
                self.ask(answer_generator=lambda evidence: self.expected_answer)
        retrieval.assert_not_called()

    @patch("src.ui_backend.Path.is_file", return_value=True)
    @patch("src.ui_backend.hybrid_assistant.retrieve_hybrid")
    def test_cross_patient_evidence_blocked_before_hosted_generation(
        self, retrieval, is_file
    ):
        wrong = scoped_evidence()
        wrong["patient"] = {"patient_id": "synthetic-other"}
        retrieval.return_value = wrong
        with patch("src.ui_backend.hybrid_assistant.route_question",
                   return_value={"mode": "sql", "use_rag": False}):
            calls = []
            with self.assertRaisesRegex(RuntimeError, "Patient scope mismatch"):
                self.ask(answer_generator=lambda evidence: calls.append(evidence))
        self.assertEqual(calls, [])

    @patch("src.ui_backend.Path.is_file", return_value=True)
    @patch("src.ui_backend.hybrid_assistant.retrieve_hybrid")
    @patch("src.ui_backend.reliable_assistant.generate_reliable_answer")
    def test_local_default_generator_remains_available(
        self, local_generate, retrieval, is_file
    ):
        retrieval.return_value = scoped_evidence()
        local_generate.return_value = self.expected_answer
        with patch("src.ui_backend.hybrid_assistant.route_question",
                   return_value={"mode": "sql", "use_rag": False}):
            ui_backend.ask_synthetic_patient(
                database=self.database, index_dir=self.index,
                patient_id="synthetic-001", question="Show latest vital signs.",
                mode="sql",
            )
        local_generate.assert_called_once()


if __name__ == "__main__":
    unittest.main()
