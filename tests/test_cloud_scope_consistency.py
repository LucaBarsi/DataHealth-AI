"""Phase 16.1 regression: prevent unsupported absence claims in public demo.

All tests use invented fixtures and mocked inference, NEVER call a provider.
"""
from __future__ import annotations

from pathlib import Path
import json
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cloud_demo.demo_backend import (
    allowed_markers, citation_check, load_fixtures,
    open_demo_database, retrieve_evidence,
)
from cloud_demo.suggested_questions import SUGGESTED_QUESTIONS
from cloud_demo.scope_validation import retrieval_scope, negative_claim_check
from cloud_demo.evaluate_cloud import run_evaluation
from cloud_demo import remote_inference

FIXTURES = ROOT / "cloud_demo" / "sample_records.json"


class EvidenceScopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = load_fixtures(FIXTURES)
        cls.conn = open_demo_database(cls.data)

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def evidence(self, index: int, patient: str = "DEMO-P001") -> dict:
        return retrieve_evidence(self.conn, patient, SUGGESTED_QUESTIONS[index][1])

    def test_vitals_and_notes_does_not_query_conditions(self):
        scope = retrieval_scope(self.evidence(5))["categories"]
        self.assertTrue(scope["observations"]["queried"])
        self.assertTrue(scope["notes"]["queried"])
        self.assertFalse(scope["conditions"]["queried"])
        self.assertFalse(scope["medications"]["queried"])

    def test_recorded_conditions_exists_for_same_patient(self):
        conditions = self.evidence(2)["conditions"]
        self.assertEqual([r["condition_id"] for r in conditions], ["DEMO-C001"])
        self.assertEqual(conditions[0]["source_marker"], "[SQL:DEMO-C001]")

    def test_cross_query_absence_claim_rejected_even_with_valid_citation(self):
        e = self.evidence(5)
        answer = "No conditions were recorded for this patient. [SQL:DEMO-O003]"
        self.assertTrue(citation_check(answer, e)["valid"])
        self.assertFalse(negative_claim_check(answer, e)["valid"])
        self.assertIn("CATEGORY_NOT_QUERIED", {x["reason"] for x in negative_claim_check(answer, e)["violations"]})

    def test_actual_screenshot_style_recorded_conditions_overreach_rejected(self):
        e = self.evidence(2)
        answer = ("Illustrative condition entry A is active [SQL:DEMO-C001]. "
                  "No other conditions, observations, medications, or notes were found in the provided evidence.")
        result = negative_claim_check(answer, e)
        self.assertFalse(result["valid"])
        self.assertEqual({x["category"] for x in result["violations"]},
                         {"conditions", "observations", "medications", "notes"})

    def test_valid_vitals_reply_not_rejected(self):
        e = self.evidence(0)
        reply = ("Heart rate: 79 /min [SQL:DEMO-O003]. "
                 "Respiratory rate: 16 /min [SQL:DEMO-O004].")
        self.assertTrue(citation_check(reply, e)["valid"])
        self.assertTrue(negative_claim_check(reply, e)["valid"])

    def test_note_no_complaints_does_not_mean_no_notes(self):
        e = self.evidence(3)
        note_marker = e["notes"][0]["source_marker"]
        answer = f"The note reports no new complaints {note_marker}."
        self.assertTrue(negative_claim_check(answer, e)["valid"])

    def test_no_medication_requests_retrieved_allowed_when_queried_and_empty(self):
        e = self.evidence(4, patient="DEMO-P004")
        self.assertTrue(retrieval_scope(e)["categories"]["medications"]["queried"])
        self.assertFalse(e["medications"])
        self.assertTrue(negative_claim_check("No medication requests were retrieved in this query.", e)["valid"])

    def test_no_medication_requests_retrieved_not_allowed_when_not_queried(self):
        e = self.evidence(0)
        self.assertFalse(negative_claim_check("No medication requests were retrieved in this query.", e)["valid"])

    def test_absence_asserted_despite_retrieved_condition_is_rejected(self):
        e = self.evidence(2)
        self.assertFalse(negative_claim_check("No conditions were recorded for this patient.", e)["valid"])

    def test_not_queried_disclosure_is_allowed(self):
        e = self.evidence(5)
        self.assertTrue(negative_claim_check("The condition category was not queried for this question.", e)["valid"])

    def test_patient_category_scope_does_not_leak_other_patients(self):
        a, b = self.evidence(2, "DEMO-P001"), self.evidence(2, "DEMO-P002")
        self.assertFalse(allowed_markers(a) & allowed_markers(b))
        self.assertEqual(len(retrieval_scope(a)["categories"]), 4)
        self.assertNotIn("DEMO-P002", json.dumps(retrieval_scope(a)))

    def test_remote_payload_includes_scope_metadata_without_api_call(self):
        e = self.evidence(5)
        captured = {}
        class FakeResponse:
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def read(self, _size):
                return json.dumps({"choices": [{"message": {"content": "Heart rate [SQL:DEMO-O003]"}}]}).encode()
        def fake_urlopen(req, timeout):
            captured["body"] = json.loads(req.data.decode("utf-8"))
            return FakeResponse()
        with patch.object(remote_inference, "urlopen", side_effect=fake_urlopen):
            remote_inference.remote_qwen_answer(
                evidence=e, question="Compare vitals and note", api_base="https://example.com/v1",
                model_id="qwen3.5-4b", api_key="MOCK_KEY"
            )
        content = captured["body"]["messages"][1]["content"]
        self.assertIn('"retrieval_scope"', content)
        self.assertIn('"queried": false', content)
        self.assertNotIn('MOCK_KEY', content)

    def test_live_evaluator_falls_back_on_out_of_scope_claim(self):
        unsafe = "Heart rate 79 [SQL:DEMO-O003]. No conditions were recorded."
        with patch("cloud_demo.evaluate_cloud.remote_qwen_answer", return_value=unsafe):
            summary, rows = run_evaluation(
                fixtures_path=FIXTURES, mode="live", patient_id="DEMO-P001", max_cases=1,
                live_settings={"api_base": "https://example.com/v1", "api_key": "FAKE", "model_id": "qwen"},
            )
        self.assertEqual(summary["hosted_fallbacks"], 1)
        self.assertEqual(rows[0]["safe_failure_code"], "EVIDENCE_SCOPE_VIOLATION")
        self.assertEqual(rows[0]["status"], "EVIDENCE_ONLY_FALLBACK")
        self.assertNotIn("No conditions were recorded", rows[0]["displayed_answer"])

    def test_ui_scope_check_falls_back_before_displaying_generated_text(self):
        text = (ROOT / "cloud_demo" / "streamlit_app.py").read_text(encoding="utf-8")
        self.assertIn("negative_claim_check(generated, evidence)", text)
        self.assertIn('fallback_reason = "EVIDENCE_SCOPE_VIOLATION"', text)
        self.assertIn('"Not queried for this question;', text)

    def test_retrieval_scope_inference_not_a_complete_history(self):
        e = self.evidence(5)
        s = retrieval_scope(e)
        self.assertFalse(any(c["complete_history_verified"] for c in s["categories"].values()))


if __name__ == "__main__":
    unittest.main()
