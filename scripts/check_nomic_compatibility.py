"""Compare FastEmbed CPU embeddings with the existing local Ollama RAG index.

Diagnostic only: does not add, update, delete or rebuild ChromaDB records.
It downloads public model weights on the first run. No patient text is printed.
Run from the project root: python -m scripts.check_nomic_compatibility
"""
from __future__ import annotations

import math
from pathlib import Path
import statistics

import chromadb
import numpy as np
from fastembed import TextEmbedding

from src import rag_assistant

INDEX_DIR = Path("data/vectorstore/chroma")
MODEL_NAME = "nomic-ai/nomic-embed-text-v1.5-Q"
QUESTIONS = (
    "What does the most recent clinical note document?",
    "Summarize the selected patient's clinical history.",
    "What medications are mentioned in the notes?",
)


def cosine(left, right) -> float:
    first = np.asarray(left, dtype=np.float64)
    second = np.asarray(right, dtype=np.float64)
    if first.ndim != 1 or first.shape != second.shape:
        raise ValueError(f"Vector dimensions differ: {first.shape} / {second.shape}")
    denominator = float(np.linalg.norm(first) * np.linalg.norm(second))
    if denominator <= 0 or not math.isfinite(denominator):
        raise ValueError("Invalid embedding magnitude")
    return float(np.dot(first, second) / denominator)


def mean_similarity(reference, candidates) -> float:
    if len(reference) != len(candidates):
        raise ValueError("Different numbers of vectors")
    return statistics.mean(cosine(a, b) for a, b in zip(reference, candidates))


def main() -> None:
    if not INDEX_DIR.is_dir():
        raise SystemExit("Missing ChromaDB index. Run from the deployment worktree.")

    client = chromadb.PersistentClient(path=str(INDEX_DIR.resolve()))
    collection = client.get_collection(rag_assistant.COLLECTION_NAME)
    if (collection.metadata or {}).get("embedding_model") != rag_assistant.DEFAULT_EMBED_MODEL:
        raise SystemExit("Unexpected collection embedding model; stopping.")
    sample = collection.get(limit=6, include=["documents", "embeddings", "metadatas"])
    documents = sample["documents"]
    original = sample["embeddings"]
    if not documents or original is None or len(original) != len(documents):
        raise SystemExit("Indexed documents/embeddings are not available.")

    print("Existing ChromaDB records:", collection.count())
    print("Comparing", len(documents), "indexed documents (contents not printed).")
    print("Initializing CPU FastEmbed:", MODEL_NAME)
    print("First run will download public model files; allow time for setup.")
    model = TextEmbedding(model_name=MODEL_NAME, threads=2)
    plain = list(model.embed(documents, batch_size=3))
    prefixed = list(model.embed(["search_document: " + text for text in documents], batch_size=3))
    print("Ollama index dimensions:", len(original[0]))
    print("FastEmbed dimensions:", len(plain[0]))
    print("Document similarity (no prefix):", round(mean_similarity(original, plain), 4))
    print("Document similarity (search_document prefix):",
          round(mean_similarity(original, prefixed), 4))

    try:
        ollama_queries = rag_assistant.embed_texts(
            list(QUESTIONS),
            rag_assistant.DEFAULT_EMBED_MODEL,
            rag_assistant.DEFAULT_OLLAMA,
        )
    except (RuntimeError, OSError, ValueError) as exc:
        print("Ollama query comparison: UNAVAILABLE")
        print("Reason:", type(exc).__name__, "(check if Ollama is running).")
        print("Index-only diagnostic finished; compatibility NOT confirmed.")
        return

    cpu_query_plain = list(model.embed(list(QUESTIONS), batch_size=3))
    cpu_query_prefixed = list(model.embed(
        ["search_query: " + question for question in QUESTIONS], batch_size=3
    ))
    print("Query similarity (no prefix):",
          round(mean_similarity(ollama_queries, cpu_query_plain), 4))
    print("Query similarity (search_query prefix):",
          round(mean_similarity(ollama_queries, cpu_query_prefixed), 4))

    # Compare ranked results for a patient with multiple indexed chunks, if one exists.
    patient = None
    counts = {}
    for metadata in collection.get(include=["metadatas"])["metadatas"] or []:
        if metadata and metadata.get("patient_id"):
            identity = metadata["patient_id"]
            counts[identity] = counts.get(identity, 0) + 1
    for identity, count in counts.items():
        if count >= 2:
            patient = identity
            break
    if patient:
        where = {"patient_id": patient}
        for label, queries in (("plain", cpu_query_plain), ("prefixed", cpu_query_prefixed)):
            overlaps = []
            for baseline, candidate in zip(ollama_queries, queries):
                original_hits = collection.query(
                    query_embeddings=[baseline], n_results=2, where=where
                )["ids"][0]
                candidate_hits = collection.query(
                    query_embeddings=[candidate], n_results=2, where=where
                )["ids"][0]
                overlaps.append(len(set(original_hits) & set(candidate_hits)) / 2)
            print(f"Top-2 overlap for one synthetic patient ({label}):",
                  round(statistics.mean(overlaps), 4))
    else:
        print("Top-2 overlap: SKIPPED (no patient has two indexed chunks).")

    print("Diagnostic completed. Similarity alone does not prove retrieval quality.")
    print("Do not enable hosted RAG or rebuild the original index yet.")


if __name__ == "__main__":
    main()
