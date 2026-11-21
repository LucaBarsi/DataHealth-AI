"""Offline Phase 8 tests: no real Ollama, Chroma, or patient data required."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src import evaluate_hybrid

PATIENT = "synthetic-patient-1"
S_SQL = "[SQL:vitals:obs-1]"
S_DOC = "[DOC:note-1#chunk:0]"


def fake_evidence():
    return {
        "patient": {"patient_id": PATIENT, "full_name": "Avery10 Example20"},
        "route": {"mode": "hybrid"},
        "sql_record_count": 1,
        "rag_passage_count": 1,
        "sql_evidence": [{"source_marker": S_SQL, "topic": "vitals",
                          "record": {"observation_id": "obs-1", "value_numeric": 84, "unit_code": "/min"}}],
        "rag_evidence": [{"source_marker": S_DOC, "document_id": "note-1", "document_date": "2026-01-01",
                          "document_type": "Synthetic note", "text": "No current complaints."}],
    }


class Phase8Tests(unittest.TestCase):
    def test_citation_source_ids_are_matched_exactly(self):
        output = evaluate_hybrid.analyze_citations(
            "Heart rate 84 [SQL:vitals:obs-1]. Other [DOC:invented#chunk:0].", [S_SQL, S_DOC]
        )
        self.assertEqual(output["valid_cited_markers"], [S_SQL])
        self.assertEqual(output["unknown_cited_markers"], ["[DOC:invented#chunk:0]"])
        self.assertFalse(output["all_citations_refer_to_retrieved_sources"])

    def test_citation_presence_not_treated_as_factual_accuracy(self):
        output = evaluate_hybrid.analyze_citations("False statement [SQL:vitals:obs-1]", [S_SQL])
        self.assertTrue(output["all_citations_refer_to_retrieved_sources"])
        self.assertIn("NOT an assessment of factual support", output["limitation"])

    def test_run_case_retrieves_once_and_uses_allowlisted_evidence(self):
        case = evaluate_hybrid.CASES[4]
        with patch.object(evaluate_hybrid.hybrid_assistant, "retrieve_hybrid", return_value=fake_evidence()) as retrieve:
            with patch.object(evaluate_hybrid.hybrid_assistant, "generate_answer",
                              return_value=f"Heart rate 84 {S_SQL}. Note {S_DOC}.") as generate:
                result = evaluate_hybrid.run_case(case, PATIENT, Path("fake.db"), Path("fake.index"),
                                                   5, 2, "qwen3.5:4b", "nomic-embed-text", "http://127.0.0.1:11434", False)
        self.assertEqual(result["status"], "GENERATED")
        self.assertEqual(result["sql_record_count"], 1)
        self.assertEqual(result["rag_passage_count"], 1)
        self.assertTrue(result["citation_audit"]["all_citations_refer_to_retrieved_sources"])
        self.assertEqual(retrieve.call_count, 1)
        self.assertEqual(generate.call_count, 1)

    def test_no_evidence_does_not_call_the_llm(self):
        data = fake_evidence()
        data.update(sql_record_count=0, rag_passage_count=0, sql_evidence=[], rag_evidence=[])
        with patch.object(evaluate_hybrid.hybrid_assistant, "retrieve_hybrid", return_value=data):
            with patch.object(evaluate_hybrid.hybrid_assistant, "generate_answer",
                              side_effect=AssertionError("LLM must not be called")):
                result = evaluate_hybrid.run_case(evaluate_hybrid.CASES[0], PATIENT,
                                                   Path("fake.db"), Path("fake.index"), 5, 2,
                                                   "qwen3.5:4b", "nomic-embed-text", "http://127.0.0.1:11434", False)
        self.assertEqual(result["status"], "NO_ELIGIBLE_EVIDENCE")
        self.assertEqual(result["answer"], "")

    def test_patient_scope_is_checked(self):
        data = fake_evidence()
        data["patient"] = {"patient_id": "different-patient"}
        with patch.object(evaluate_hybrid.hybrid_assistant, "retrieve_hybrid", return_value=data):
            with self.assertRaises(RuntimeError):
                evaluate_hybrid.run_case(evaluate_hybrid.CASES[0], PATIENT,
                                          Path("fake.db"), Path("fake.index"), 5, 2,
                                          "qwen3.5:4b", "nomic-embed-text", "http://127.0.0.1:11434", True)

    def test_output_creation_and_manual_review_aggregation(self):
        with tempfile.TemporaryDirectory() as temp:
            dest = Path(temp) / "run"
            args = argparse.Namespace(patient_id=PATIENT, database=Path("fake.db"), index_dir=Path("fake.index"),
                output=dest, chat_model="qwen3.5:4b", embed_model="nomic-embed-text",
                ollama_url="http://127.0.0.1:11434", sql_limit=5, top_k=2, max_cases=1, dry_run=False)
            with patch.object(evaluate_hybrid.hybrid_assistant, "retrieve_hybrid", return_value=fake_evidence()):
                with patch.object(evaluate_hybrid.hybrid_assistant, "generate_answer", return_value=f"84 /min {S_SQL}"):
                    self.assertEqual(evaluate_hybrid.run_suite(args), 0)
            summary = json.loads((dest / "evaluation_summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["responses_generated"], 1)
            self.assertIsNone(summary["automated_factual_accuracy"])
            review_file = dest / "manual_review.csv"
            with review_file.open("r", encoding="utf-8-sig", newline="") as f:
                reviewer_rows = list(csv.DictReader(f))
            reviewer_rows[0].update(factual_accuracy="correct", citation_support="supported",
                                    patient_isolation="pass", unsafe_clinical_advice="no",
                                    factual_claims="2", unsupported_claims="0", reviewer_notes="Grounded synthetic test")
            with review_file.open("w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=evaluate_hybrid.REVIEW_COLUMNS)
                writer.writeheader()
                writer.writerows(reviewer_rows)
            scored = evaluate_hybrid.summarize_manual_review(review_file, dest / "evaluation_results.jsonl")
            self.assertEqual(scored["reviewed_cases"], 1)
            self.assertEqual(scored["fully_correct_rate_among_reviewed"], 1.0)
            self.assertEqual(scored["unsupported_claim_fraction_among_reviewed"], 0)
            with self.assertRaises(FileExistsError):
                evaluate_hybrid.run_suite(args)

    def test_invalid_manual_annotations_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            d = Path(temp)
            (d / "evaluation_results.jsonl").write_text(json.dumps({"case_id": "x", "status": "GENERATED"}) + "\n", encoding="utf-8")
            with (d / "manual_review.csv").open("w", encoding="utf-8-sig", newline="") as f:
                w = csv.DictWriter(f, fieldnames=evaluate_hybrid.REVIEW_COLUMNS)
                w.writeheader()
                w.writerow({"case_id": "x", "factual_accuracy": "correct", "citation_support": "supported",
                            "patient_isolation": "pass", "unsafe_clinical_advice": "no",
                            "factual_claims": "1", "unsupported_claims": "2"})
            with self.assertRaisesRegex(ValueError, "exceed"):
                evaluate_hybrid.summarize_manual_review(d / "manual_review.csv", d / "evaluation_results.jsonl")


if __name__ == "__main__":
    unittest.main()
