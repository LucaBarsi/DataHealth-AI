"""Read-only Nomic retrieval agreement test for every synthetic patient.

Compares Ollama nomic-embed-text with two FastEmbed Nomic v1.5-Q variants
over all synthetic patients in the Gold SQLite database. Reports ranking
agreement only for patients with at least two indexed passages; for patients
with one passage, checks retrieval scope without inflating ranking agreement.

This does NOT assess clinical validity or document relevance and does not
write to the SQLite database, ChromaDB, or the original local application.

Run from the deployment worktree:
    python -m scripts.check_nomic_retrieval_agreement
"""
from __future__ import annotations

from collections import Counter
from contextlib import closing
from pathlib import Path
import sqlite3

import chromadb
from fastembed import TextEmbedding

from src import rag_assistant

DATABASE = Path("data/gold/datahealth.db")
INDEX_DIR = Path("data/vectorstore/chroma")
MODEL_NAME = "nomic-ai/nomic-embed-text-v1.5-Q"
QUESTIONS = (
    "What does the most recent clinical note document?",
    "Summarize the clinical history in the record.",
    "Are medication requests mentioned in the clinical notes?",
    "What was documented about measurements in the last encounter?",
    "Summarize the historical notes for the selected patient.",
)


def database_patient_ids(database: Path) -> set[str]:
    """Read only the synthetic patient identifiers for coverage checking."""
    if not database.is_file():
        raise FileNotFoundError("Gold SQLite database not found")
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
        conn.execute("PRAGMA query_only=ON")
        return {row[0] for row in conn.execute("SELECT patient_id FROM patients")}


def index_patient_counts(collection) -> Counter:
    """Reject missing or noncurrent vector metadata before searching."""
    metadata = collection.get(include=["metadatas"])["metadatas"]
    if metadata is None or len(metadata) != collection.count():
        raise RuntimeError("ChromaDB metadata count does not match index size")
    counts = Counter()
    for item in metadata:
        if not isinstance(item, dict) or not item.get("patient_id"):
            raise RuntimeError("Indexed passage is missing a patient identifier")
        if item.get("status") != "current":
            raise RuntimeError("An indexed passage is not marked current")
        counts[item["patient_id"]] += 1
    return counts


def scoped_first_hits(collection, patient_id: str, vectors) -> list[str]:
    """Batch the five queries, checking the patient filter for every result."""
    query_vectors = [list(map(float, vector)) for vector in vectors]
    result = collection.query(
        query_embeddings=query_vectors,
        n_results=1,
        where={"patient_id": patient_id},
        include=["metadatas"],
    )
    ids = result["ids"]
    metas = result["metadatas"]
    if len(ids) != len(query_vectors) or len(metas) != len(query_vectors):
        raise RuntimeError("Unexpected patient-scoped result shape")
    first_hits = []
    for hit_ids, hit_metas in zip(ids, metas):
        if len(hit_ids) != 1 or len(hit_metas) != 1:
            raise RuntimeError("Expected exactly one passage for each scoped query")
        metadata = hit_metas[0]
        if metadata.get("patient_id") != patient_id or metadata.get("status") != "current":
            raise RuntimeError("Patient isolation or current-status check failed")
        first_hits.append(hit_ids[0])
    return first_hits


def main() -> None:
    db_patients = database_patient_ids(DATABASE)
    if len(db_patients) != 112:
        raise RuntimeError("Unexpected synthetic patient count in Gold SQLite database")

    client = chromadb.PersistentClient(path=str(INDEX_DIR.resolve()))
    collection = client.get_collection(rag_assistant.COLLECTION_NAME)
    if (collection.metadata or {}).get("embedding_model") != rag_assistant.DEFAULT_EMBED_MODEL:
        raise RuntimeError("Index was not created with the expected Ollama embedding model")
    counts = index_patient_counts(collection)
    indexed_patients = set(counts)
    missing = db_patients - indexed_patients
    unknown = indexed_patients - db_patients

    print("Synthetic patients in SQLite:", len(db_patients))
    print("Indexed passages:", collection.count())
    print("Patients represented in ChromaDB:", len(indexed_patients))
    print("Patients without indexed passages:", len(missing))
    print("Unknown indexed patient IDs:", len(unknown))
    if missing or unknown:
        raise RuntimeError("Patient coverage or index scope mismatch; no ranking test was performed")

    single = sorted(identity for identity in db_patients if counts[identity] == 1)
    multiple = sorted(identity for identity in db_patients if counts[identity] >= 2)
    print("Patients with exactly one passage (scope check only):", len(single))
    print("Patients with at least two passages (ranking evaluation):", len(multiple))
    print("Questions per patient:", len(QUESTIONS))

    print("Loading CPU model:", MODEL_NAME)
    model = TextEmbedding(model_name=MODEL_NAME, threads=2)
    ollama_vectors = rag_assistant.embed_texts(
        list(QUESTIONS),
        rag_assistant.DEFAULT_EMBED_MODEL,
        rag_assistant.DEFAULT_OLLAMA,
    )
    cpu_plain = list(model.embed(list(QUESTIONS), batch_size=len(QUESTIONS)))
    cpu_prefixed = list(model.embed(
        ["search_query: " + question for question in QUESTIONS],
        batch_size=len(QUESTIONS),
    ))
    if (
        len(ollama_vectors) != len(QUESTIONS)
        or len(cpu_plain) != len(QUESTIONS)
        or len(cpu_prefixed) != len(QUESTIONS)
        or any(
            len(a) != 768 or len(b) != 768 or len(c) != 768
            for a, b, c in zip(ollama_vectors, cpu_plain, cpu_prefixed)
        )
    ):
        raise RuntimeError("Embedding dimensions or batch sizes do not match")

    matches_plain = 0
    matches_prefixed = 0
    ranked_cases = 0
    single_scoped_queries = 0
    for patient_id in sorted(db_patients):
        reference = scoped_first_hits(collection, patient_id, ollama_vectors)
        plain = scoped_first_hits(collection, patient_id, cpu_plain)
        prefixed = scoped_first_hits(collection, patient_id, cpu_prefixed)
        if counts[patient_id] == 1:
            single_scoped_queries += len(QUESTIONS)
            continue  # A single available passage cannot test relative ranking.
        ranked_cases += len(QUESTIONS)
        matches_plain += sum(a == b for a, b in zip(reference, plain))
        matches_prefixed += sum(a == b for a, b in zip(reference, prefixed))

    print("Patients evaluated for patient isolation:", len(db_patients))
    print("Single-passage scoped queries (excluded from ranking):", single_scoped_queries)
    print("Multi-passage ranking comparisons:", ranked_cases)
    if ranked_cases:
        print("Top-1 agreement without prefix:", f"{matches_plain / ranked_cases:.1%}")
        print("Top-1 agreement with search_query prefix:",
              f"{matches_prefixed / ranked_cases:.1%}")
    else:
        print("Top-1 agreement: NOT MEASURABLE (no multi-passage patients)")
    print("All queries completed without modifying the original data.")
    print("Agreement with Ollama alone does not establish retrieval relevance.")


if __name__ == "__main__":
    main()
