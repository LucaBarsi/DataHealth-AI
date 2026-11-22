"""Optional, patient-scoped semantic vector retrieval for fictional cloud notes.

The ONNX embedding model (FastEmbed) is downloaded only when explicitly enabled
or when the owner builds an index. The small JSON index contains ONLY invented
note IDs, fictional patient IDs, fingerprints, and vector numbers. No secrets.

Public Streamlit Cloud storage may be ephemeral; commit a generated JSON index
if persistence across restarts is required. The embedding model's cache itself
is NOT committed. The demo still supports lexical search without this module.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import math
from pathlib import Path
import threading
from typing import Callable

MODEL_NAME = "BAAI/bge-small-en-v1.5"
INDEX_SCHEMA = "datahealth-demo-vector-v1"


def note_corpus(fixtures: dict) -> list[dict]:
    """Select one existing #chunk:0 per fictional note, deterministic ordering."""
    if fixtures.get("synthetic_only") is not True:
        raise ValueError("Semantic retrieval accepts fictional fixtures only")
    docs = []
    seen = set()
    for patient in fixtures["patients"]:
        pid = patient["patient_id"]
        if not pid.startswith("DEMO-P"):
            raise ValueError("Non-demo patient ID")
        for note in patient.get("notes", []):
            did = note["document_id"]
            if did in seen or not did.startswith("DEMO-D"):
                raise ValueError("Duplicate or non-demo document ID")
            seen.add(did)
            docs.append({
                "patient_id": pid, "document_id": did,
                "date": note["date"], "type": note["type"],
                "text": note["text"], "source_marker": f"[DOC:{did}#chunk:0]",
            })
    return sorted(docs, key=lambda d: (d["patient_id"], d["document_id"]))


def corpus_hash(docs: list[dict]) -> str:
    return sha256(json.dumps(docs, sort_keys=True, ensure_ascii=False,
                             separators=(",", ":")).encode("utf-8")).hexdigest()


def _normalize(values) -> list[float]:
    v = [float(x) for x in values]
    if not v or not all(math.isfinite(x) for x in v):
        raise ValueError("Empty or non-finite embedding")
    norm = math.sqrt(sum(x*x for x in v))
    if norm < 1e-12:
        raise ValueError("Zero embedding")
    return [x/norm for x in v]


def build_index(fixtures: dict, embed: Callable, *, model_name: str = MODEL_NAME) -> dict:
    """Build an index; embed is injected for offline tests."""
    docs = note_corpus(fixtures)
    if not docs:
        raise ValueError("No demo documents to index")
    vectors = list(embed([d["text"] for d in docs]))
    if len(vectors) != len(docs):
        raise ValueError("Unexpected number of embeddings")
    normalized = [_normalize(v) for v in vectors]
    dim = len(normalized[0])
    if not all(len(v) == dim for v in normalized):
        raise ValueError("Inconsistent embedding dimensions")
    return {
        "schema": INDEX_SCHEMA,
        "model": model_name,
        "corpus_sha256": corpus_hash(docs),
        "dimension": dim,
        "documents": [
            {"document_id": doc["document_id"], "patient_id": doc["patient_id"],
             "source_marker": doc["source_marker"], "vector": vec}
            for doc, vec in zip(docs, normalized)
        ],
    }


def validate_index(index: dict, fixtures: dict, *, model_name: str = MODEL_NAME) -> dict:
    """Reject stale/mixed patient indexes, model mismatches, malformed vectors."""
    docs = note_corpus(fixtures)
    if (index.get("schema") != INDEX_SCHEMA or index.get("model") != model_name
        or index.get("corpus_sha256") != corpus_hash(docs)):
        raise ValueError("Stale or incompatible semantic index")
    rows = index.get("documents")
    dim = index.get("dimension")
    if not isinstance(rows, list) or not isinstance(dim, int) or dim < 1 or len(rows) != len(docs):
        raise ValueError("Invalid vector index dimensions")
    for row, doc in zip(rows, docs):
        if (row.get("document_id") != doc["document_id"]
            or row.get("patient_id") != doc["patient_id"]
            or row.get("source_marker") != doc["source_marker"]):
            raise ValueError("Wrong patient or document in vector index")
        vector = row.get("vector")
        if not isinstance(vector, list) or len(vector) != dim:
            raise ValueError("Invalid embedding vector")
        normalized = _normalize(vector)
        if abs(sum(x*y for x, y in zip(vector, normalized)) - 1.0) > .002:
            raise ValueError("Embedding is not normalized")
    return index


def write_index(index: dict, destination: Path) -> None:
    """Only write explicitly requested files (local developer CLI)."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def rank_documents(index: dict, *, patient_id: str, query_vector,
                   top_k: int = 2) -> list[dict]:
    """Cosine search after STRICT patient filtering; no cross-patient fallback."""
    if top_k < 1 or top_k > 10:
        raise ValueError("Invalid top_k")
    q = _normalize(query_vector)
    if len(q) != index["dimension"]:
        raise ValueError("Query/index dimensions differ")
    results = []
    for doc in index["documents"]:
        if doc["patient_id"] != patient_id:
            continue
        sim = sum(a*b for a, b in zip(q, doc["vector"]))
        results.append({"document_id": doc["document_id"],
                        "source_marker": doc["source_marker"],
                        "score": round(sim, 6)})
    return sorted(results, key=lambda x: (-x["score"], x["document_id"]))[:top_k]


class SemanticRetriever:
    """Thread-safe shared embedding model + already fingerprint-checked index."""
    def __init__(self, *, fixtures: dict, embedder, index: dict, index_source: str):
        self.index = validate_index(index, fixtures)
        self.embedder = embedder
        self.index_source = index_source
        self._lock = threading.Lock()

    def search(self, patient_id: str, question: str, top_k: int = 2) -> list[dict]:
        if len(question) > 1000:
            raise ValueError("Question exceeds 1000 characters")
        if not patient_id.startswith("DEMO-P"):
            raise ValueError("Non-demo patient ID")
        with self._lock:
            vectors = list(self.embedder.embed([question]))
        if len(vectors) != 1:
            raise ValueError("Embedding provider returned unexpected results")
        return rank_documents(self.index, patient_id=patient_id,
                              query_vector=vectors[0], top_k=top_k)


def load_retriever(fixtures: dict, *, index_path: Path | None = None) -> SemanticRetriever:
    """Load fixed ONNX model only upon opt-in. Never calls hosted Qwen.

    A committed index is preferred. If missing, build transiently in memory;
    no persistence across Cloud restarts is then promised.
    """
    from fastembed import TextEmbedding  # lazy import; lexical mode stays lightweight
    embedder = TextEmbedding(model_name=MODEL_NAME)
    index_source = "runtime-built (ephemeral)"
    if index_path is not None and index_path.is_file():
        index = json.loads(index_path.read_text(encoding="utf-8"))
        validate_index(index, fixtures)
        index_source = "committed JSON index"
    else:
        index = build_index(fixtures, embedder.embed)
    return SemanticRetriever(fixtures=fixtures, embedder=embedder,
                             index=index, index_source=index_source)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Build a fictional note vector index (offline Qwen, local embedding download)")
    parser.add_argument("build", choices=["build"])
    parser.add_argument("--fixture", default="cloud_demo/sample_records.json")
    parser.add_argument("--output", default="cloud_demo/semantic_index.json")
    args = parser.parse_args(argv)
    from .demo_backend import load_fixtures
    data = load_fixtures(Path(args.fixture))
    from fastembed import TextEmbedding
    embedding_model = TextEmbedding(model_name=MODEL_NAME)
    index = build_index(data, embedding_model.embed)
    write_index(index, Path(args.output))
    print(json.dumps({"index_path": str(args.output), "model": MODEL_NAME,
                      "documents": len(index["documents"]), "dimension": index["dimension"],
                      "mode": "fictional_only", "hosted_api_calls": 0}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
