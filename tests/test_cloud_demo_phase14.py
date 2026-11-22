"""Phase 14 regression tests: six suggestions, scoped retrieval, optional hosted Qwen.

No real API calls, no patient information, and no Streamlit server required.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cloud_demo"))

import demo_backend as b
import remote_inference as r
from suggested_questions import SUGGESTED_QUESTIONS


class Phase14Tests(unittest.TestCase):
    def setUp(self):
        self.conn = b.open_demo_database(b.load_fixtures(ROOT / "cloud_demo" / "sample_records.json"))

    def tearDown(self):
        self.conn.close()

    def test_six_suggestions_are_unique_and_nonempty(self):
        self.assertEqual(len(SUGGESTED_QUESTIONS), 6)
        self.assertEqual(len({label for label, _ in SUGGESTED_QUESTIONS}), 6)
        self.assertTrue(all(label and len(question) > 20 for label, question in SUGGESTED_QUESTIONS))

    def test_every_suggestion_has_a_source_aware_response(self):
        for label, question in SUGGESTED_QUESTIONS:
            with self.subTest(label=label):
                e = b.retrieve_evidence(self.conn, "DEMO-P001", question, mode="auto")
                answer = b.evidence_only_answer(e)
                self.assertIn("Evidence-only preview", answer)
                self.assertTrue(b.citation_check(answer, e)["valid"], label)

    def test_latest_vitals_only_filters_vital_codes(self):
        q = SUGGESTED_QUESTIONS[0][1]
        e = b.retrieve_evidence(self.conn, "DEMO-P001", q)
        self.assertTrue(e["observations"])
        self.assertTrue(all(row["code"] in b.VITAL_CODES for row in e["observations"]))
        self.assertNotIn("2093-3", {row["code"] for row in e["observations"]})

    def test_laboratory_results_only_filters_lab_codes(self):
        q = SUGGESTED_QUESTIONS[1][1]
        e = b.retrieve_evidence(self.conn, "DEMO-P001", q)
        self.assertTrue(e["observations"])
        self.assertTrue(all(row["code"] in b.LAB_CODES for row in e["observations"]))
        self.assertEqual({row["unit"] for row in e["observations"]}, {"mg/dL"})

    def test_recorded_conditions_isolated_and_citable(self):
        q = SUGGESTED_QUESTIONS[2][1]
        e = b.retrieve_evidence(self.conn, "DEMO-P001", q)
        self.assertEqual(len(e["conditions"]), 1)
        self.assertEqual(e["conditions"][0]["source_marker"], "[SQL:DEMO-C001]")
        self.assertFalse(e["observations"] or e["notes"] or e["medications"])
        self.assertTrue(b.citation_check(b.evidence_only_answer(e), e)["valid"])

    def test_no_conditions_is_reported_not_inferred(self):
        q = SUGGESTED_QUESTIONS[2][1]
        e = b.retrieve_evidence(self.conn, "DEMO-P004", q)
        self.assertFalse(e["conditions"])
        a = b.evidence_only_answer(e)
        self.assertIn("No structured condition entries", a)
        self.assertIn("do not infer diagnoses", a)

    def test_clinical_history_only_uses_notes(self):
        e = b.retrieve_evidence(self.conn, "DEMO-P001", SUGGESTED_QUESTIONS[3][1])
        self.assertTrue(e["notes"])
        self.assertFalse(e["observations"] or e["conditions"] or e["medications"])

    def test_medication_comparison_retrieves_both_types(self):
        e = b.retrieve_evidence(self.conn, "DEMO-P001", SUGGESTED_QUESTIONS[4][1])
        self.assertTrue(e["medications"] and e["notes"])
        self.assertTrue(b.citation_check(b.evidence_only_answer(e), e)["valid"])

    def test_compare_vitals_and_notes_retrieves_both(self):
        e = b.retrieve_evidence(self.conn, "DEMO-P001", SUGGESTED_QUESTIONS[5][1])
        self.assertTrue(e["observations"] and e["notes"])
        self.assertTrue(all(row["code"] in b.VITAL_CODES for row in e["observations"]))

    def test_patient_isolation_conditions_and_observations(self):
        question = SUGGESTED_QUESTIONS[2][1]
        a = b.retrieve_evidence(self.conn, "DEMO-P001", question)
        c = b.retrieve_evidence(self.conn, "DEMO-P003", question)
        self.assertFalse(b.allowed_markers(a) & b.allowed_markers(c))
        with self.assertRaises(ValueError):
            b.retrieve_evidence(self.conn, "DEMO-P001' OR 1=1 --", question)

    def test_unknown_condition_citation_rejected(self):
        e = b.retrieve_evidence(self.conn, "DEMO-P001", SUGGESTED_QUESTIONS[2][1])
        self.assertFalse(b.citation_check("Guess [SQL:DEMO-C999]", e)["valid"])

    def test_backend_remains_read_only(self):
        with self.assertRaises(Exception):
            self.conn.execute("DROP TABLE conditions")

    def test_combined_mode_includes_conditions(self):
        e = b.retrieve_evidence(self.conn, "DEMO-P001", "Compare relevant information", mode="combined")
        self.assertTrue(e["conditions"] and e["observations"] and e["notes"] and e["medications"])

    def test_invalid_or_private_endpoint_is_rejected(self):
        for host in ("http://example.com/v1", "https://localhost:11434/v1", "https://127.0.0.1/v1", "https://10.0.0.1/v1", "https://server.internal/v1"):
            with self.subTest(host=host), self.assertRaises(ValueError):
                r.chat_completion_url(host)

    def test_remote_request_includes_conditions_and_source_markers(self):
        e = b.retrieve_evidence(self.conn, "DEMO-P001", SUGGESTED_QUESTIONS[2][1])
        captured = {}
        class FakeResponse:
            def __enter__(self): return self
            def __exit__(self, *_): return None
            def read(self, limit):
                return json.dumps({"choices":[{"message":{"content":"Condition: [SQL:DEMO-C001]"}}]}).encode()
        def fake_urlopen(request, timeout):
            captured["req"] = request
            captured["timeout"] = timeout
            return FakeResponse()
        with patch.object(r, "urlopen", side_effect=fake_urlopen):
            result = r.remote_qwen_answer(evidence=e, question="List the recorded condition", api_base="https://example.com/v1", model_id="qwen3.5-4b", api_key="SECRET-NOT-SHARED")
        self.assertEqual(result, "Condition: [SQL:DEMO-C001]")
        self.assertIn("DEMO-C001", captured["req"].data.decode())
        self.assertIn('"conditions"', json.loads(captured["req"].data.decode())["messages"][1]["content"])
        self.assertEqual(captured["req"].get_header("Authorization"), "Bearer SECRET-NOT-SHARED")
        self.assertTrue(b.citation_check(result, e)["valid"])

    def test_remote_error_does_not_leak_key(self):
        e = b.retrieve_evidence(self.conn, "DEMO-P001", SUGGESTED_QUESTIONS[0][1])
        with patch.object(r, "urlopen", side_effect=OSError("private-secret: abc")):
            with self.assertRaises(r.RemoteInferenceError) as ctx:
                r.remote_qwen_answer(evidence=e, question="Heart rate", api_base="https://example.com/v1", model_id="qwen3.5-4b", api_key="private-secret")
        self.assertNotIn("private-secret", str(ctx.exception))

if __name__ == "__main__":
    unittest.main()
