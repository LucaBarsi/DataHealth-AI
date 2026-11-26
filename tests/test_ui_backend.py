"""Offline Phase 9 tests; do not require Streamlit, Ollama, or ChromaDB runtime."""
from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from src import ui_backend


class UIBackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name) / "synthetic.db"
        # The sqlite3 connection context manages transactions, but does not close
        # the connection. Explicit closing avoids WinError 32 on Windows cleanup.
        with closing(sqlite3.connect(self.database)) as conn:
            with conn:
                conn.execute("CREATE TABLE patients (patient_id TEXT, full_name TEXT, gender TEXT, birth_date TEXT)")
                conn.executemany("INSERT INTO patients VALUES (?,?,?,?)", [
                    ("patient-b", "Beta22", "male", "2000-01-01"),
                    ("patient-a", "Alpha11", "female", "2001-01-01"),
                ])

    def test_patient_list_is_sorted_and_scoped(self):
        patients = ui_backend.list_synthetic_patients(self.database)
        self.assertEqual([x["patient_id"] for x in patients], ["patient-a", "patient-b"])
        self.assertEqual(patients[0]["full_name"], "Alpha11")

    def test_patient_list_missing_database(self):
        with self.assertRaises(FileNotFoundError):
            ui_backend.list_synthetic_patients(self.database.with_name("missing.db"))

    def test_switching_patient_clears_previous_messages(self):
        state = {"active_patient_id": "patient-a", "chat_messages": [{"role": "assistant", "content": "old"}]}
        self.assertTrue(ui_backend.sync_patient_session(state, "patient-b"))
        self.assertEqual(state["chat_messages"], [])
        self.assertFalse(ui_backend.sync_patient_session(state, "patient-b"))

    def test_invalid_input_does_not_call_retrieval(self):
        with patch.object(ui_backend.hybrid_assistant, "retrieve_hybrid") as retrieval:
            with self.assertRaises(ValueError):
                ui_backend.ask_synthetic_patient(database=self.database, index_dir=Path(self.temp.name),
                                                 patient_id="patient-a", question=" ")
            retrieval.assert_not_called()

    def test_retrieval_and_guard_are_used(self):
        evidence = {"patient": {"patient_id": "patient-a"}, "sql_evidence": [], "rag_evidence": []}
        answer = {"status": "NO_ELIGIBLE_EVIDENCE", "answer": "No evidence.", "warning": "No patient conclusion."}
        with patch.object(ui_backend.hybrid_assistant, "retrieve_hybrid", return_value=evidence) as retrieval, \
             patch.object(ui_backend.reliable_assistant, "generate_reliable_answer", return_value=answer) as generator:
            result = ui_backend.ask_synthetic_patient(database=self.database,
                     index_dir=Path(self.temp.name), patient_id="patient-a", question="Any records?", mode="sql")
            self.assertEqual(result["response"]["status"], "NO_ELIGIBLE_EVIDENCE")
            self.assertEqual(retrieval.call_args.args[2], "patient-a")
            generator.assert_called_once()

    def test_scope_mismatch_blocks_generation(self):
        evidence = {"patient": {"patient_id": "patient-b"}, "sql_evidence": [], "rag_evidence": []}
        with patch.object(ui_backend.hybrid_assistant, "retrieve_hybrid", return_value=evidence), \
             patch.object(ui_backend.reliable_assistant, "generate_reliable_answer") as generator:
            with self.assertRaises(RuntimeError):
                ui_backend.ask_synthetic_patient(database=self.database,
                     index_dir=Path(self.temp.name), patient_id="patient-a", question="What happened?", mode="sql")
            generator.assert_not_called()

    def test_source_summary(self):
        data = {
            "sql_evidence": [{"source_marker": "[SQL:vitals:x]", "topic": "vitals", "record": {
                "measurement_display": "Heart rate", "quality_status": "PASS_STRUCTURAL_CHECKS"}}],
            "rag_evidence": [{"source_marker": "[DOC:y#chunk:0]", "document_type": "History and physical note"}],
        }
        result = ui_backend.source_summary(data)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["source"], "[SQL:vitals:x]")
        self.assertEqual(result[1]["type"], "RAG")


if __name__ == "__main__":
    unittest.main()
