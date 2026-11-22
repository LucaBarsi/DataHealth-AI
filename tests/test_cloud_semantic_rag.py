"""Phase 17 offline tests (no hosted Qwen, no FastEmbed download)."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cloud_demo.demo_backend import (
    allowed_markers, citation_check, load_fixtures, open_demo_database,
    retrieve_evidence,
)
from cloud_demo.scope_validation import negative_claim_check
from cloud_demo.semantic_retrieval import (
    MODEL_NAME, SemanticRetriever, build_index, corpus_hash, note_corpus,
    rank_documents, validate_index, write_index,
)

DATA_FILE = ROOT / "cloud_demo" / "sample_records.json"


class FakeEmbedder:
    """Stub vectors exclusively for verifying the retrieval plumbing."""
    def embed(self, texts):
        for text in texts:
            value = text.lower()
            if "cholesterol" in value or "lipid" in value:
                yield [0.0, 1.0, 0.0]
            elif "medication" in value:
                yield [0.0, 0.0, 1.0]
            else:
                yield [1.0, 0.0, 0.0]


class CloudSemanticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = load_fixtures(DATA_FILE)
        cls.conn = open_demo_database(cls.data)

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def test_demo_corpus_only_contains_fake_patients(self):
        docs = note_corpus(self.data)
        self.assertEqual(len(docs), 4)
        self.assertTrue(all(row["patient_id"].startswith("DEMO-P") for row in docs))
        self.assertTrue(all(row["source_marker"].endswith("#chunk:0]") for row in docs))

    def test_build_index_is_small_and_has_no_raw_note_text(self):
        index = build_index(self.data, FakeEmbedder().embed)
        self.assertEqual(index["dimension"], 3)
        self.assertEqual(len(index["documents"]), 4)
        self.assertNotIn("outpatient note:", json.dumps(index))
        self.assertEqual(index["model"], MODEL_NAME)
        self.assertIs(validate_index(index, self.data), index)

    def test_query_is_restricted_to_one_patient(self):
        idx = build_index(self.data, FakeEmbedder().embed)
        results = rank_documents(idx, patient_id="DEMO-P001", query_vector=[1, 0, 0])
        self.assertEqual([r["document_id"] for r in results], ["DEMO-D001"])
        self.assertEqual(results[0]["source_marker"], "[DOC:DEMO-D001#chunk:0]")

    def test_unknown_patient_does_not_expose_other_patients(self):
        idx = build_index(self.data, FakeEmbedder().embed)
        self.assertEqual(rank_documents(idx, patient_id="DEMO-P999", query_vector=[1, 0, 0]), [])

    def test_stale_corpus_invalidates_index(self):
        idx = build_index(self.data, FakeEmbedder().embed)
        modified = deepcopy(self.data)
        modified["patients"][0]["notes"][0]["text"] += " changed"
        self.assertNotEqual(corpus_hash(note_corpus(self.data)), corpus_hash(note_corpus(modified)))
        with self.assertRaises(ValueError):
            validate_index(idx, modified)

    def test_model_and_patient_tampering_invalidates_index(self):
        idx = build_index(self.data, FakeEmbedder().embed)
        other = deepcopy(idx)
        other["model"] = "another-model"
        with self.assertRaises(ValueError):
            validate_index(other, self.data)
        other = deepcopy(idx)
        other["documents"][0]["patient_id"] = "DEMO-P999"
        with self.assertRaises(ValueError):
            validate_index(other, self.data)

    def test_duplicate_document_ids_fail_closed(self):
        other = deepcopy(self.data)
        other["patients"][1]["notes"][0]["document_id"] = "DEMO-D001"
        with self.assertRaises(ValueError):
            note_corpus(other)

    def test_index_json_round_trip(self):
        index = build_index(self.data, FakeEmbedder().embed)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "semantic_index.json"
            write_index(index, path)
            actual = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(actual, index)
            validate_index(actual, self.data)

    def test_semantic_search_with_two_notes_ranks_matching_topic(self):
        fixtures = deepcopy(self.data)
        person = fixtures["patients"][0]
        person["notes"].append({
            "document_id": "DEMO-D099", "date": "2026-09-01",
            "type": "Illustrative historical note",
            "text": "Invented cholesterol lipid panel review for software testing only",
        })
        index = build_index(fixtures, FakeEmbedder().embed)
        engine = SemanticRetriever(fixtures=fixtures, embedder=FakeEmbedder(),
                                   index=index, index_source="offline test")
        hits = engine.search("DEMO-P001", "Which note discusses a lipid panel?", 2)
        self.assertEqual(hits[0]["document_id"], "DEMO-D099")
        self.assertEqual({h["document_id"] for h in hits}, {"DEMO-D001", "DEMO-D099"})

    def test_semantic_integration_keeps_citation_ids(self):
        index = build_index(self.data, FakeEmbedder().embed)
        engine = SemanticRetriever(fixtures=self.data, embedder=FakeEmbedder(),
                                   index=index, index_source="offline test")
        ev = retrieve_evidence(self.conn, "DEMO-P001", "Summarize clinical history",
                               semantic_search=engine.search)
        self.assertEqual(ev["document_retrieval"]["method"], "semantic_vector_cosine")
        marker = "[DOC:DEMO-D001#chunk:0]"
        self.assertIn(marker, allowed_markers(ev))
        self.assertTrue(citation_check("The note describes a follow-up " + marker, ev)["valid"])
        self.assertTrue(negative_claim_check("The note mentions a follow-up " + marker, ev)["valid"])

    def test_untrusted_cross_patient_hit_ignored(self):
        def bad_search(_patient, _question, _top_k):
            return [{"document_id": "DEMO-D002", "score": 1.0}]
        ev = retrieve_evidence(self.conn, "DEMO-P001", "Clinical note", semantic_search=bad_search)
        self.assertEqual(ev["document_retrieval"]["method"], "lexical_keywords")
        self.assertNotIn("[DOC:DEMO-D002#chunk:0]", allowed_markers(ev))

    def test_embedding_failure_falls_back_to_lexical(self):
        def broken(*_):
            raise RuntimeError("model unreachable")
        ev = retrieve_evidence(self.conn, "DEMO-P001", "Clinical history", semantic_search=broken)
        self.assertEqual(ev["document_retrieval"]["method"], "lexical_keywords")
        self.assertEqual(ev["notes"][0]["document_id"], "DEMO-D001")

    def test_sql_only_query_never_calls_embedder(self):
        def broken(*_):
            raise AssertionError("not supposed to embed")
        ev = retrieve_evidence(self.conn, "DEMO-P001", "Latest vital signs", semantic_search=broken)
        self.assertEqual(ev["document_retrieval"]["method"], "not_queried")

    def test_newest_note_is_preserved_for_explicit_latest(self):
        fixtures = deepcopy(self.data)
        person = fixtures["patients"][0]
        person["notes"].append({"document_id":"DEMO-D099", "date":"2026-09-01",
                                "type":"Historical note", "text":"Invented cholesterol record"})
        conn = open_demo_database(fixtures)
        try:
            ev = retrieve_evidence(conn, "DEMO-P001", "Summarize the latest clinical note",
                                   semantic_search=lambda *args: [{"document_id":"DEMO-D099"}])
            self.assertEqual(ev["notes"][0]["document_id"], "DEMO-D001")
            self.assertEqual(ev["document_retrieval"]["method"], "semantic_vector_cosine")
        finally:
            conn.close()

    def test_ui_is_explicit_opt_in_with_lexical_fallback(self):
        app = (ROOT/"cloud_demo"/"streamlit_app.py").read_text(encoding="utf-8")
        self.assertIn("SEMANTIC_RAG_ENABLED", app)
        self.assertIn("semantic_engine", app)
        self.assertIn("using keyword search", app)


if __name__ == "__main__":
    unittest.main()
