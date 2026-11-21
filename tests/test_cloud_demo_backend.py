"""Phase 13 — public demo tests (no network, no Streamlit server)."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cloud_demo"))
import demo_backend as b
import remote_inference as r

DATA = ROOT / "cloud_demo" / "sample_records.json"


class CloudDemoBackendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = b.load_fixtures(DATA)

    def setUp(self):
        self.conn = b.open_demo_database(self.fixture)

    def tearDown(self):
        self.conn.close()

    def test_explicit_demo_provenance(self):
        self.assertTrue(self.fixture["synthetic_only"])
        self.assertIn("not exported", self.fixture["dataset_provenance"])
        self.assertEqual(len(b.list_patients(self.conn)), 4)

    def test_in_memory_database_read_only(self):
        with self.assertRaises(Exception):
            self.conn.execute("DELETE FROM patients")

    def test_patient_isolation(self):
        first = b.retrieve_evidence(self.conn, "DEMO-P001", "latest heart rate and note", mode="combined")
        second = b.retrieve_evidence(self.conn, "DEMO-P002", "latest heart rate and note", mode="combined")
        ids_first = {x["observation_id"] for x in first["observations"]}
        ids_second = {x["observation_id"] for x in second["observations"]}
        self.assertFalse(ids_first & ids_second)
        self.assertNotEqual(first["notes"][0]["document_id"], second["notes"][0]["document_id"])

    def test_patient_id_sql_injection_not_accepted(self):
        with self.assertRaises(ValueError):
            b.retrieve_evidence(self.conn, "DEMO-P001' OR 1=1 --", "heart rate")

    def test_fixed_query_routing(self):
        self.assertEqual(b.route_question("Summarize the most recent clinical note", "auto"), (False, True, False))
        self.assertEqual(b.route_question("Heart rate trend", "auto"), (True, False, False))
        self.assertEqual(b.route_question("Compare medication requests with the clinical note", "auto"), (False, True, True))

    def test_measurement_code_and_unit_isolation(self):
        rows = b.series_for_patient(self.conn, "DEMO-P001", "8867-4", "/min")
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(x["code"] == "8867-4" and x["unit"] == "/min" for x in rows))
        self.assertFalse(any(x["observation_id"].startswith("DEMO-O008") for x in rows))

    def test_flagged_quality_filter(self):
        without = b.series_for_patient(self.conn, "DEMO-P003", "8867-4", "/min")
        with_flags = b.series_for_patient(self.conn, "DEMO-P003", "8867-4", "/min", include_flagged=True)
        self.assertEqual(len(without), 2)
        self.assertEqual(len(with_flags), 3)
        self.assertTrue(any(x["quality_status"] == "REVIEW_REQUIRED" for x in with_flags))

    def test_sources_present_in_evidence_preview(self):
        e = b.retrieve_evidence(self.conn, "DEMO-P001", "Compare medications with a clinical note", "combined")
        answer = b.evidence_only_answer(e)
        self.assertIn("[DOC:DEMO-D001#chunk:0]", answer)
        self.assertIn("[SQL:DEMO-M001]", answer)
        self.assertTrue(b.citation_check(answer, e)["valid"])

    def test_citation_unknown_rejected(self):
        e = b.retrieve_evidence(self.conn, "DEMO-P001", "heart rate", "measurements")
        self.assertFalse(b.citation_check("Something [SQL:DEMO-O999]", e)["valid"])
        self.assertFalse(b.citation_check("Citation missing", e)["valid"])
        self.assertFalse(b.citation_check("Fake [SQL: ...]", e)["valid"])

    def test_unscoped_queries_do_not_get_invented_results(self):
        e = b.retrieve_evidence(self.conn, "DEMO-P004", "medication requests", "auto")
        self.assertFalse(e["medications"])
        self.assertIn("not proof of no medication use", b.evidence_only_answer(e))

    def test_no_retrieval_allows_no_foreign_results(self):
        e = b.retrieve_evidence(self.conn, "DEMO-P001", "note", "notes")
        self.assertFalse(e["observations"])
        self.assertFalse(e["medications"])
        self.assertEqual(len(e["notes"]), 1)


class HostedInferenceTests(unittest.TestCase):
    def test_https_remote_only(self):
        self.assertEqual(r.chat_completion_url("https://example-provider.com/v1"),
                         "https://example-provider.com/v1/chat/completions")
        for value in ("http://localhost:11434/v1", "https://127.0.0.1/v1",
                      "http://example-provider.com/v1", "https://192.168.1.3/v1",
                      "https://provider.internal/v1", "https://example.com/v1?token=bad"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                r.chat_completion_url(value)

    def test_remote_provider_error_is_nonrevealing(self):
        with patch.object(r, "urlopen", side_effect=OSError("secret endpoint/path")):
            with self.assertRaises(r.RemoteInferenceError) as ctx:
                r.remote_qwen_answer(evidence={"patient":{},"observations":[],"medications":[],"notes":[],"limitations":""},
                                    question="Hello", api_base="https://example.com/v1",
                                    model_id="qwen3.5-4b", api_key="TOP_SECRET_KEY")
        self.assertNotIn("TOP_SECRET_KEY", str(ctx.exception))
        self.assertNotIn("secret endpoint", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
