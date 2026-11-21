"""Phase 8.1 offline tests — no network, Ollama, ChromaDB or real data."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src import reliable_assistant, evaluate_reliability, evaluate_hybrid

SQL = "[SQL:vitals:obs-01]"
DOC = "[DOC:note-01#chunk:0]"
PATIENT = "synthetic-patient-01"


def evidence(sql=True, rag=True):
    return {
        "patient": {"patient_id": PATIENT, "full_name": "Avery10 Example20"},
        "question": "Summarize vitals and the most recent clinical note.",
        "route": {"mode": "hybrid"},
        "sql_record_count": 1 if sql else 0,
        "rag_passage_count": 1 if rag else 0,
        "sql_evidence": (
            [{"source_marker": SQL, "topic": "vitals",
              "record": {"measurement_display": "Heart rate", "value_numeric": 84,
                         "unit_code": "/min", "quality_status": "PASS_STRUCTURAL_CHECKS",
                         "effective_datetime_utc": "2026-01-01"}}]
            if sql else []
        ),
        "rag_evidence": (
            [{"source_marker": DOC, "document_id": "note-01", "document_type": "Clinical note",
              "document_date": "2026-01-02", "text": "No active medications documented."}]
            if rag else []
        ),
    }


class CitationGuardTests(unittest.TestCase):
    def test_accepts_only_exact_sources_from_both_modalities(self):
        audit = reliable_assistant.audit_citations(f"Heart rate 84 {SQL}. Note {DOC}.", evidence())
        self.assertTrue(audit["valid"])
        self.assertEqual(audit["unknown_markers"], [])

    def test_detects_unknown_partial_and_missing_modality(self):
        audit = reliable_assistant.audit_citations(f"Heart rate {SQL} [DOC:note-01]. [SQL:bad", evidence())
        self.assertFalse(audit["valid"])
        self.assertIn("[DOC:note-01]", audit["unknown_markers"])
        self.assertEqual(audit["partial_marker_count"], 1)
        self.assertIn("DOC:", audit["missing_evidence_types"])

    def test_retries_invalid_citation_then_validates(self):
        responses = [
            {"message": {"content": "No prescriptions. [SQL: ...]"}},
            {"message": {"content": f"Heart rate 84 /min {SQL}. The note says no active medications {DOC}."}},
        ]
        with patch.object(reliable_assistant.rag_assistant, "_post_ollama", side_effect=responses) as mocked:
            result = reliable_assistant.generate_reliable_answer(evidence())
        self.assertEqual(result["status"], "CITATION_IDS_VALID")
        self.assertEqual(result["attempts"], 2)
        self.assertEqual(mocked.call_count, 2)
        self.assertNotIn("[SQL: ...]", result["answer"])

    def test_falls_back_when_model_repeatedly_invents_source(self):
        response = {"message": {"content": "Patient has no medication requests [SQL: ...]."}}
        with patch.object(reliable_assistant.rag_assistant, "_post_ollama", return_value=response) as mocked:
            result = reliable_assistant.generate_reliable_answer(evidence())
        self.assertEqual(result["status"], "EVIDENCE_ONLY_FALLBACK")
        self.assertEqual(result["attempts"], 2)
        self.assertEqual(mocked.call_count, 2)
        self.assertIn(SQL, result["answer"])
        self.assertIn(DOC, result["answer"])
        self.assertNotIn("[SQL: ...]", result["answer"])
        self.assertNotIn("No active medications documented", result["answer"])

    def test_empty_structured_section_cannot_force_sql_citation(self):
        d = evidence(sql=False)
        response = {"message": {"content": f"The note says no active medications {DOC}."}}
        with patch.object(reliable_assistant.rag_assistant, "_post_ollama", return_value=response):
            result = reliable_assistant.generate_reliable_answer(d)
        self.assertEqual(result["status"], "CITATION_IDS_VALID")
        self.assertNotIn("SQL:", result["audit"]["missing_evidence_types"])

    def test_no_evidence_never_calls_model(self):
        d = evidence(sql=False, rag=False)
        with patch.object(reliable_assistant.rag_assistant, "_post_ollama", side_effect=AssertionError("Do not call")):
            result = reliable_assistant.generate_reliable_answer(d)
        self.assertEqual(result["status"], "NO_ELIGIBLE_EVIDENCE")

    def test_plain_valid_citation_does_not_claim_factual_proof(self):
        audit = reliable_assistant.audit_citations(f"False claim {SQL}. Note {DOC}.", evidence())
        self.assertTrue(audit["valid"])
        self.assertIn("NOT factual", audit["interpretation"])


class ReliabilityEvaluationTests(unittest.TestCase):
    def test_run_case_and_summary(self):
        case = evaluate_hybrid.CASES[4]
        with patch.object(evaluate_reliability.hybrid_assistant, "retrieve_hybrid", return_value=evidence()):
            with patch.object(evaluate_reliability.reliable_assistant, "generate_reliable_answer", return_value={
                "status": "CITATION_IDS_VALID", "answer": f"Heart rate 84 {SQL}; note {DOC}",
                "attempts": 1, "warning": "exact ID only",
            }):
                args = argparse.Namespace(database=Path("dummy.db"), index_dir=Path("fake.index"),
                                          sql_limit=5, top_k=2, embed_model="nomic-embed-text",
                                          ollama_url="http://127.0.0.1:11434", chat_model="qwen3.5:4b",
                                          max_retries=1)
                row = evaluate_reliability.run_reliability_case(case, PATIENT, args)
        self.assertEqual(row["status"], "GENERATED")
        self.assertTrue(row["citation_audit"]["all_citations_refer_to_retrieved_sources"])
        self.assertEqual(evaluate_reliability.summary_for([row])["citation_ids_valid_responses"], 1)

    def test_comparison_preserves_original_baseline_and_flags_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            baseline = Path(tmp) / "baseline.jsonl"
            row = {"case_id":"vitals_sql","question":"Q",
                   "citation_audit":{"unknown_cited_markers":["[SQL: ...]"]}}
            baseline.write_text(json.dumps(row) + "\n", encoding="utf-8")
            new = {"case_id":"vitals_sql","question":"Q",
                   "guard_status":"EVIDENCE_ONLY_FALLBACK",
                   "citation_audit":{"unknown_cited_markers":[]}}
            comparison = evaluate_reliability.compare_baseline([new], baseline)
            self.assertEqual(comparison["baseline_unknown_source_markers"], 1)
            self.assertEqual(comparison["new_unknown_source_markers_in_displayed_answers"], 0)
            self.assertEqual(comparison["new_fallbacks_among_matched"], 1)

    def test_rejects_nonempty_output_directory_without_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "existing.txt").write_text("keep")
            args = argparse.Namespace(
                output=out, patient_id=PATIENT, max_cases=1
            )
            with self.assertRaises(FileExistsError):
                evaluate_reliability.run_suite(args)


if __name__ == "__main__":
    unittest.main()
