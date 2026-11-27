"""CPU query embeddings for the hosted synthetic-patient RAG preview.

The index was created with Ollama nomic-embed-text. FastEmbed quantized Nomic
is an experimental compatibility alternative, not identical vector generation.
No automatic reindexing and no external patient data transfers occur here.
"""
from __future__ import annotations

import math

MODEL_NAME = "nomic-ai/nomic-embed-text-v1.5-Q"


def embed_query(question: str, model) -> list[float]:
    """Return one validated 768-dimensional vector, using no query prefix.

    The no-prefix variant produced higher top-1 agreement in the 112-patient
    offline diagnostic. It is not a clinical or relevance guarantee.
    """
    if not isinstance(question, str) or not question.strip() or len(question) > 1500:
        raise ValueError("A nonempty query of at most 1500 characters is required")
    results = list(model.embed([question], batch_size=1))
    if len(results) != 1:
        raise RuntimeError("Expected one CPU query embedding")
    vector = [float(value) for value in results[0]]
    if len(vector) != 768 or any(not math.isfinite(value) for value in vector):
        raise RuntimeError("Invalid 768-dimensional FastEmbed vector")
    return vector


def load_cpu_model():
    """Lazily import/download FastEmbed model; never load at module import."""
    from fastembed import TextEmbedding

    return TextEmbedding(model_name=MODEL_NAME, threads=2)
