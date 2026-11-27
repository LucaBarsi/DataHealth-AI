"""Non-destructive retrieval agreement check for the hosted RAG experiment.

Compares first-ranked synthetic-document results from Ollama's nomic-embed-text
and FastEmbed's quantized Nomic v1.5 with and without task prefixes.

This is a diagnostic, NOT a relevance benchmark or clinical validation.
It does not mutate the ChromaDB index and does not print patient information.
Run from the deployment worktree: python -m scripts.check_nomic_retrieval_agreement
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

import chromadb
from fastembed import TextEmbedding

from src import rag_assistant

INDEX_DIR = Path("data/vectorstore/chroma")
MODEL_NAME = "nomic-ai/nomic-embed-text-v1.5-Q"
MAX_PATIENTS = 25
QUESTIONS = (
    "What does the most recent clinical note document?",
    "Summarize the clinical history in the record.",
    "Are medication requests mentioned in the clinical notes?",
    "What was documented about measurements in the last encounter?",
    "Summarize the historical notes for the selected patient.",
)


def top_id(collection, query_vector, patient_id: str) -> str:
    response = collection.query(
        query_embeddings=[query_vector],
        n_results=1,
        where={"patient_id": patient_id},
        include=["metadatas"],
    )
    ids = response["ids"][0]
    if len(ids) != 1:
        raise RuntimeError("Patient-scoped retrieval returned no top-ranked passage")
    metadata = response["metadatas"][0][0]
    if metadata.get("patient_id") != patient_id or metadata.get("status") != "current":
        raise RuntimeError("Patient scope or document status mismatch")
    return ids[0]


def main() -> None:
    if not INDEX_DIR.is_dir():
        raise SystemExit("ChromaDB index not found. Run from the deployment worktree.")

    client = chromadb.PersistentClient(path=str(INDEX_DIR.resolve()))
    collection = client.get_collection(rag_assistant.COLLECTION_NAME)
    metadata = collection.metadata or {}
    if metadata.get("embedding_model") != rag_assistant.DEFAULT_EMBED_MODEL:
        raise SystemExit("Unexpected embedding model in the source index")

    all_metadata = collection.get(include=["metadatas"])["metadatas"] or []
    counts = Counter(
        item["patient_id"]
        for item in all_metadata
        if item is not None and item.get("patient_id")
    )
    eligible = sorted(patient_id for patient_id, count in counts.items() if count >= 2)
    selected = eligible[:MAX_PATIENTS]
    if not selected:
        raise SystemExit("No patients have multiple indexed passages: cannot compare ranking.")

    print("Total indexed passages:", collection.count())
    print("Patients with at least two passages:", len(eligible))
    print("Patients evaluated:", len(selected))
    print("Questions per patient:", len(QUESTIONS))
    print("Loading FastEmbed model:", MODEL_NAME)
    model = TextEmbedding(model_name=MODEL_NAME, threads=2)

    baseline = rag_assistant.embed_texts(
        list(QUESTIONS),
        rag_assistant.DEFAULT_EMBED_MODEL,
        rag_assistant.DEFAULT_OLLAMA,
    )
    plain = list(model.embed(list(QUESTIONS), batch_size=len(QUESTIONS)))
    prefixed = list(model.embed(
        ["search_query: " + item for item in QUESTIONS],
        batch_size=len(QUESTIONS),
    ))
    if not (
        len(baseline) == len(plain) == len(prefixed) == len(QUESTIONS)
        and len(baseline[0]) == len(plain[0]) == len(prefixed[0])
    ):
        raise RuntimeError("Embedding dimensions or counts are incompatible")

    match_plain = 0
    match_prefixed = 0
    cases = 0
    for patient_id in selected:
        for original, candidate_plain, candidate_prefixed in zip(
            baseline, plain, prefixed
        ):
            expected = top_id(collection, original, patient_id)
            match_plain += top_id(collection, candidate_plain, patient_id) == expected
            match_prefixed += top_id(collection, candidate_prefixed, patient_id) == expected
            cases += 1

    print("Comparisons performed:", cases)
    print("Top-1 agreement (unprefixed):", f"{match_plain / cases:.1%}")
    print("Top-1 agreement (search_query prefix):", f"{match_prefixed / cases:.1%}")
    print("Numerical agreement is not proof of relevant or medically correct retrieval.")
    print("The source index and clinical data were not modified.")


if __name__ == "__main__":
    main()
