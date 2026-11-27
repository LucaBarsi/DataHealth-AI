"""Offline hosted FastEmbed retrieval adapter tests. No network or Ollama required."""
from pathlib import Path
import unittest
from unittest.mock import patch

from src import hosted_embeddings, rag_assistant, hybrid_assistant, ui_backend


def evidence_for(patient_id="synthetic-001"):
    return {
        "patient": {"patient_id": patient_id},
        "sql_evidence": [],
        "rag_evidence": [{"source_marker": "[DOC:note-001#chunk:0]", "document_id": "note-001"}],
        "route": {"mode": "rag", "use_rag": True},
    }


class HostedRAGTests(unittest.TestCase):
    def test_cpu_embedding_returns_finite_768_vector(self):
        class Model:
            def embed(self, texts, batch_size):
                self.last_texts = texts
                return [[0.01] * 768]
        model = Model()
        vector = hosted_embeddings.embed_query("latest clinical note", model)
        self.assertEqual(len(vector), 768)
        self.assertEqual(model.last_texts, ["latest clinical note"])

    def test_cpu_embedding_rejects_wrong_vector_length(self):
        class Model:
            def embed(self, texts, batch_size):
                return [[0.1] * 16]
        with self.assertRaisesRegex(RuntimeError, "768-dimensional"):
            hosted_embeddings.embed_query("latest clinical note", Model())

    @patch("src.rag_assistant.embed_texts")
    @patch("src.rag_assistant._collection")
    @patch("src.rag_assistant.valid_patient")
    def test_rag_uses_injected_embedder_and_scopes_chroma(
        self, valid_patient, get_collection, local_embed
    ):
        valid_patient.return_value = {"patient_id": "synthetic-001"}
        class Collection:
            metadata = {"embedding_model": "nomic-embed-text"}
            def count(self):
                return 198
            def query(self, **kwargs):
                self.kwargs = kwargs
                return {
                    "documents": [["Synthetic note text"]],
                    "metadatas": [[{
                        "patient_id": "synthetic-001", "status": "current",
                        "document_id": "note-001", "chunk_index": 0,
                        "document_date": "2026-01-01", "document_type": "note",
                    }]],
                    "distances": [[0.2]],
                }
        collection = Collection()
        get_collection.return_value = (object(), collection)
        result = rag_assistant.retrieve(
            Path("not-used.db"), Path("not-used-index"), "synthetic-001",
            "latest clinical note", "nomic-embed-text", "http://127.0.0.1:11434", 2,
            query_embedder=lambda query: [0.1] * 768,
        )
        self.assertEqual(
            collection.kwargs["where"], {"patient_id": "synthetic-001"}
        )
        self.assertEqual(result["passages"][0]["source_marker"], "[DOC:note-001#chunk:0]")
        local_embed.assert_not_called()

    @patch("src.rag_assistant.embed_texts")
    @patch("src.rag_assistant._collection")
    @patch("src.rag_assistant.valid_patient")
    def test_cross_patient_result_is_blocked(self, valid_patient, get_collection, local_embed):
        valid_patient.return_value = {"patient_id": "synthetic-001"}
        class Collection:
            metadata = {"embedding_model": "nomic-embed-text"}
            def count(self):
                return 198
            def query(self, **kwargs):
                return {
                    "documents": [["Other synthetic note"]],
                    "metadatas": [[{
                        "patient_id": "synthetic-other", "status": "current",
                        "document_id": "note-other", "chunk_index": 0,
                    }]],
                    "distances": [[0.2]],
                }
        get_collection.return_value = (object(), Collection())
        with self.assertRaisesRegex(RuntimeError, "improperly scoped"):
            rag_assistant.retrieve(
                Path("not-used.db"), Path("not-used-index"), "synthetic-001",
                "clinical history", "nomic-embed-text", "http://127.0.0.1:11434", 2,
                query_embedder=lambda _: [0.1] * 768,
            )
        local_embed.assert_not_called()

    @patch("src.ui_backend.Path.is_file", return_value=True)
    @patch("src.ui_backend.hybrid_assistant.retrieve_hybrid")
    @patch("src.ui_backend.hybrid_assistant.route_question")
    def test_ui_backend_passes_cpu_encoder(self, route, retrieve, exists):
        route.return_value = {"use_rag": True, "mode": "rag"}
        retrieve.return_value = evidence_for()
        encoder = lambda query: [0.1] * 768
        reply = {"answer": "Synthetic note [DOC:note-001#chunk:0].",
                 "status": "CITATION_IDS_VALID"}
        result = ui_backend.ask_synthetic_patient(
            database=Path("fixture.db"), index_dir=Path("."),
            patient_id="synthetic-001", question="clinical history",
            mode="rag", allow_rag=True, query_embedder=encoder,
            answer_generator=lambda evidence: reply,
        )
        self.assertIs(retrieve.call_args.kwargs["query_embedder"], encoder)
        self.assertEqual(result["response"]["status"], "CITATION_IDS_VALID")


if __name__ == "__main__":
    unittest.main()
