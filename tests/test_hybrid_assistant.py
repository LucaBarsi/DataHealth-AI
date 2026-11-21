"""Phase 7 tests: routing, read-only SQL and patient-scoped RAG."""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from src import hybrid_assistant


class HybridAssistantTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "test.db"
        self.index = Path(self.tmp.name) / "index"
        self.id1 = "synthetic-patient-1"
        self.id2 = "synthetic-patient-2"
        conn = sqlite3.connect(self.db)
        try:
            conn.executescript("""
                CREATE TABLE patients (patient_id TEXT PRIMARY KEY, full_name TEXT, gender TEXT, birth_date TEXT);
                CREATE TABLE medication_requests (medication_request_id TEXT PRIMARY KEY, patient_id TEXT, authored_on_utc TEXT, medication_display TEXT, status TEXT, intent TEXT);
                CREATE VIEW v_patient_overview AS SELECT patient_id, full_name, gender, birth_date FROM patients;
                CREATE VIEW v_observations AS SELECT '' AS patient_id, '' AS observation_id,
                    '' AS effective_datetime_utc, '' AS measurement_code, '' AS measurement_display,
                    NULL AS value_numeric, '' AS value_text, '' AS unit_code, '' AS quality_status,
                    '' AS quality_flags, '' AS category;
            """)
            conn.executemany("INSERT INTO patients VALUES (?, ?, ?, ?)", [
                (self.id1, "Avery10 Example20", "female", "2012-01-01"),
                (self.id2, "Blake30 Sample40", "male", "2018-01-01"),
            ])
            conn.executemany("INSERT INTO medication_requests VALUES (?, ?, ?, ?, ?, ?)", [
                ("rx-1", self.id1, "2026-01-01", "Synthetic Medication Alpha", "active", "order"),
                ("rx-2", self.id2, "2026-01-01", "Synthetic Medication Beta", "active", "order"),
            ])
            conn.commit()
        finally:
            conn.close()

    def fake_rag(self, database, index_dir, patient_id, question, embed_model, ollama_url, top_k):
        self.assertEqual(patient_id, self.id1)
        return {
            "patient": {"patient_id": self.id1, "full_name": "Avery10 Example20"},
            "question": question,
            "passages": [{"source_marker": "[DOC:note-1#chunk:0]", "document_id": "note-1",
                         "document_date": "2026-02-02", "document_type": "Clinical note",
                         "distance": 0.2, "text": "Synthetic note: no active medications documented."}]
        }

    def test_route_modes(self):
        self.assertEqual(hybrid_assistant.route_question("Show the latest heart rate")["mode"], "sql")
        self.assertEqual(hybrid_assistant.route_question("Summarize the latest clinical note")["mode"], "rag")
        result = hybrid_assistant.route_question("Compare medications with the latest clinical note")
        self.assertEqual(result["mode"], "hybrid")
        self.assertIn("medications", result["sql_topics"])
        self.assertEqual(hybrid_assistant.route_question("Summarize clinical notes", mode="sql", topic="overview")["mode"], "sql")
        self.assertEqual(hybrid_assistant.route_question("Explain these results", topic="vitals")["mode"], "sql")

    def test_structured_query_is_patient_scoped(self):
        with patch.object(hybrid_assistant.rag_assistant, "retrieve", side_effect=AssertionError("RAG should not run")):
            result = hybrid_assistant.retrieve_hybrid(self.db, self.index, self.id1,
                            "What medications were prescribed?", mode="sql", topic="medications")
        self.assertEqual(result["sql_record_count"], 1)
        self.assertEqual(result["rag_passage_count"], 0)
        self.assertEqual(result["sql_evidence"][0]["source_marker"], "[SQL:medications:rx-1]")
        self.assertNotIn("Beta", json.dumps(result))

    def test_hybrid_retrieval_combines_distinct_sources(self):
        with patch.object(hybrid_assistant.rag_assistant, "retrieve", side_effect=self.fake_rag):
            result = hybrid_assistant.retrieve_hybrid(self.db, self.index, self.id1,
                            "Compare medications with the latest clinical note")
        self.assertEqual(result["route"]["mode"], "hybrid")
        self.assertEqual(result["sql_record_count"], 1)
        self.assertEqual(result["rag_passage_count"], 1)
        self.assertIn("[DOC:note-1#chunk:0]", json.dumps(result))
        self.assertNotIn("Beta", json.dumps(result))

    def test_unknown_patient_fails_before_retrieval(self):
        with patch.object(hybrid_assistant.rag_assistant, "retrieve", side_effect=AssertionError("Should not retrieve")):
            with self.assertRaises(ValueError):
                hybrid_assistant.retrieve_hybrid(self.db, self.index, "unknown", "Clinical notes", mode="rag")

    def test_wrong_patient_from_retrieval_is_rejected(self):
        with patch.object(hybrid_assistant.rag_assistant, "retrieve", return_value={
                "patient": {"patient_id": self.id2}, "passages": []}):
            with self.assertRaises(RuntimeError):
                hybrid_assistant.retrieve_hybrid(self.db, self.index, self.id1, "Clinical notes", mode="rag")

    def test_no_evidence_does_not_call_llm(self):
        evidence = hybrid_assistant.retrieve_hybrid(self.db, self.index, self.id1,
                            "Heart rate?", mode="sql", topic="vitals")
        with patch.object(hybrid_assistant.rag_assistant, "_post_ollama", side_effect=AssertionError("LLM should not run")):
            msg = hybrid_assistant.generate_answer(evidence)
        self.assertIn("No eligible evidence", msg)

    def test_llm_receives_two_separate_evidence_types(self):
        with patch.object(hybrid_assistant.rag_assistant, "retrieve", side_effect=self.fake_rag):
            evidence = hybrid_assistant.retrieve_hybrid(self.db, self.index, self.id1,
                                    "Compare medications with the latest clinical note")
        captured = {}
        def fake_post(url, endpoint, payload):
            captured.update(payload)
            return {"message": {"content": "The note and prescription records differ [SQL:medications:rx-1] [DOC:note-1#chunk:0]."}}
        with patch.object(hybrid_assistant.rag_assistant, "_post_ollama", side_effect=fake_post):
            answer = hybrid_assistant.generate_answer(evidence)
        self.assertIn("differ", answer)
        self.assertEqual(captured["model"], "qwen3.5:4b")
        message = json.loads(captured["messages"][1]["content"])
        self.assertEqual(len(message["structured_evidence"]), 1)
        self.assertEqual(len(message["documentary_evidence"]), 1)
        self.assertNotIn("Beta", json.dumps(message))


if __name__ == "__main__":
    unittest.main()
