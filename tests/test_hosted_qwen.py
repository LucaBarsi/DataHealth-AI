"""Offline contract tests for the optional hosted Qwen deployment adapter."""
import unittest
from unittest.mock import patch

from cloud_demo.usage_controls import SharedProcessBudget
from src.hosted_qwen import (
    HostedQwenSettings, _completion_url, generate_guarded_hosted_answer,
)


def synthetic_evidence():
    return {
        "patient": {"patient_id": "synthetic-001", "full_name": "Sample Patient"},
        "question": "List the recorded measurement.",
        "route": {"mode": "sql"},
        "sql_evidence": [{
            "source_marker": "[SQL:vitals:obs-001]",
            "topic": "vitals",
            "record": {"observation_id": "obs-001", "measurement_display": "Heart rate",
                       "value_numeric": 74, "unit_code": "/min",
                       "effective_datetime_utc": "2026-11-01T08:00:00Z"},
        }],
        "rag_evidence": [],
    }


class HostedQwenTests(unittest.TestCase):
    def setUp(self):
        self.evidence = synthetic_evidence()
        self.settings = HostedQwenSettings(api_key="test-key-never-sent")
        self.session = {}
        self.budget = SharedProcessBudget(max_calls=24, window_seconds=3600)

    def run_guarded(self):
        return generate_guarded_hosted_answer(
            self.evidence,
            settings=self.settings,
            session_state=self.session,
            shared_budget=self.budget,
        )

    def test_pinned_https_endpoint(self):
        self.assertEqual(
            _completion_url("https://mixlayer.ai/v1"),
            "https://mixlayer.ai/v1/chat/completions",
        )
        for value in ("http://mixlayer.ai/v1",
                      "https://example.org/v1",
                      "https://mixlayer.ai.evil.org/v1",
                      "https://mixlayer.ai/v1?x=1"):
            with self.subTest(value=value):
                with self.assertRaises(Exception):
                    _completion_url(value)

    @patch("src.hosted_qwen.call_hosted_qwen")
    def test_exact_citations_pass(self, generate):
        generate.return_value = "Recorded heart rate 74 /min [SQL:vitals:obs-001]."
        result = self.run_guarded()
        self.assertEqual(result["status"], "CITATION_IDS_VALID")
        self.assertTrue(result["audit"]["valid"])
        self.assertEqual(generate.call_count, 1)

    @patch("src.hosted_qwen.call_hosted_qwen")
    def test_unknown_citations_fail_closed(self, generate):
        generate.return_value = "Heart rate recorded [SQL:vitals:made-up]."
        result = self.run_guarded()
        self.assertEqual(result["status"], "EVIDENCE_ONLY_FALLBACK")
        self.assertEqual(result["reason"], "CITATION_CHECK_FAILED")
        self.assertNotIn("made-up", result["answer"])

    @patch("src.hosted_qwen.call_hosted_qwen")
    def test_session_cooldown_prevents_second_request(self, generate):
        generate.return_value = "Recorded rate [SQL:vitals:obs-001]."
        first = self.run_guarded()
        second = self.run_guarded()
        self.assertEqual(first["status"], "CITATION_IDS_VALID")
        self.assertEqual(second["reason"], "SESSION_COOLDOWN")
        self.assertEqual(generate.call_count, 1)

    @patch("src.hosted_qwen.call_hosted_qwen")
    def test_missing_key_skips_network(self, generate):
        result = generate_guarded_hosted_answer(
            self.evidence,
            settings=HostedQwenSettings(api_key=""),
            session_state=self.session,
            shared_budget=self.budget,
        )
        self.assertEqual(result["reason"], "HOSTED_QWEN_NOT_CONFIGURED")
        generate.assert_not_called()

    @patch("src.hosted_qwen.call_hosted_qwen")
    def test_no_evidence_skips_network(self, generate):
        evidence = synthetic_evidence()
        evidence["sql_evidence"] = []
        result = generate_guarded_hosted_answer(
            evidence, settings=self.settings, session_state=self.session,
            shared_budget=self.budget,
        )
        self.assertEqual(result["status"], "NO_ELIGIBLE_EVIDENCE")
        generate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
