"""Phase 17.1: offline, reproducible, fictional-only retrieval benchmark.

Compares the lexical logic used by cloud_demo.demo_backend against the same
FastEmbed cosine retriever from Phase 17. No Streamlit app or hosted Qwen API
is modified or called. Gold relevance labels are hand-authored and not medical
truth. Metrics are computed only on the supplied benchmark questions.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from statistics import mean, median
from time import perf_counter

from .demo_backend import _tokens, load_fixtures
from .semantic_retrieval import MODEL_NAME, build_index, note_corpus, rank_documents


def validate_queries(payload: dict, docs: list[dict]) -> list[dict]:
    """Fail closed if relevance labels are incomplete or cross patients."""
    if payload.get('synthetic_only') is not True:
        raise ValueError('Only explicitly fictional query sets are allowed')
    queries = payload.get('queries')
    if not isinstance(queries, list) or not queries:
        raise ValueError('Expected non-empty queries list')
    owned = {(d['patient_id'], d['document_id']) for d in docs}
    ids = set()
    for q in queries:
        qid = q.get('query_id')
        pid = q.get('patient_id')
        question = q.get('question')
        relevant = q.get('relevant_document_ids')
        if not isinstance(qid, str) or not qid or qid in ids:
            raise ValueError('Missing or duplicate query ID')
        ids.add(qid)
        if not isinstance(pid, str) or not pid.startswith('DEMO-P'):
            raise ValueError('Non-demo patient ID in query')
        if not isinstance(question, str) or not question.strip() or len(question) > 1000:
            raise ValueError('Invalid question')
        if not isinstance(relevant, list) or not relevant or len(relevant) != len(set(relevant)):
            raise ValueError('Invalid gold relevance labels')
        if any((pid, doc_id) not in owned for doc_id in relevant):
            raise ValueError(f'Query {qid} references missing or another patient document')
    return queries


def lexical_rank(docs: list[dict], patient_id: str, question: str, top_k: int = 3) -> list[str]:
    """Match Phase 17 lexical fallback: token overlap, then newest date.

    No forced 'most recent' override: benchmark queries do not request latest
    notes; it measures retrieval relevance, not chronology handling.
    """
    if top_k < 1 or top_k > 10:
        raise ValueError('top_k must be between 1 and 10')
    candidates = sorted((d for d in docs if d['patient_id'] == patient_id),
                        key=lambda d: d['date'], reverse=True)
    qterms = _tokens(question)
    ranked = sorted(candidates,
                    key=lambda d: (len(qterms & _tokens(d['text'])), d['date']),
                    reverse=True)
    return [d['document_id'] for d in ranked[:top_k]]


def retrieval_metrics(retrieved: list[str], relevant: list[str], at_k: int = 3) -> dict:
    """Recall@1, Recall@k, reciprocal rank truncated to k.

    Multiple relevance IDs are supported, though curated cases use one each.
    """
    if at_k < 1 or at_k > 10 or not relevant:
        raise ValueError('Invalid metric inputs')
    gold = set(relevant)
    if len(retrieved) != len(set(retrieved)):
        raise ValueError('Duplicate retrieved document IDs')
    first_k = retrieved[:at_k]
    rr = next((1.0 / position for position, doc in enumerate(first_k, 1)
               if doc in gold), 0.0)
    return {
        'recall_at_1': float(len(gold.intersection(retrieved[:1])) / len(gold)),
        'recall_at_3': float(len(gold.intersection(first_k)) / len(gold)),
        'reciprocal_rank_at_3': rr,
    }


def evaluate_method(queries: list[dict], rank_fn, method: str) -> list[dict]:
    rows = []
    for q in queries:
        started = perf_counter()
        retrieved = rank_fn(q['patient_id'], q['question'], 3)
        elapsed_ms = (perf_counter() - started) * 1000
        if any(not isinstance(x, str) for x in retrieved):
            raise ValueError('Retriever returned invalid IDs')
        metrics = retrieval_metrics(retrieved, q['relevant_document_ids'])
        rows.append({
            'query_id': q['query_id'], 'patient_id': q['patient_id'],
            'question': q['question'], 'method': method,
            'relevant_document_ids': q['relevant_document_ids'],
            'retrieved_document_ids': retrieved,
            'latency_ms': round(elapsed_ms, 3), **metrics,
        })
    return rows


def method_summary(rows: list[dict]) -> dict:
    if not rows:
        raise ValueError('Empty method results')
    latency = [float(r['latency_ms']) for r in rows]
    values = lambda key: round(mean(float(r[key]) for r in rows), 4)
    return {
        'queries': len(rows), 'recall_at_1': values('recall_at_1'),
        'recall_at_3': values('recall_at_3'),
        'mrr_at_3': values('reciprocal_rank_at_3'),
        'mean_query_latency_ms': round(mean(latency), 3),
        'median_query_latency_ms': round(median(latency), 3),
        'max_query_latency_ms': round(max(latency), 3),
    }


def run_benchmark(fixture_path: Path, query_path: Path, *,
                  mode: str = 'both', semantic_embedder=None) -> tuple[dict, list[dict]]:
    """Inject an embedder for tests; otherwise FastEmbed is loaded lazily.

    The production app's semantic_index.json is never read or replaced.
    """
    if mode not in {'lexical', 'semantic', 'both'}:
        raise ValueError('Unknown benchmark mode')
    fixtures = load_fixtures(fixture_path)
    docs = note_corpus(fixtures)
    queries = validate_queries(json.loads(query_path.read_text(encoding='utf-8')), docs)
    rows = []
    summaries = {}
    index_build_s = None
    if mode in ('lexical', 'both'):
        lexical_rows = evaluate_method(queries,
                lambda patient, question, k: lexical_rank(docs, patient, question, k),
                'lexical_keywords')
        rows += lexical_rows
        summaries['lexical_keywords'] = method_summary(lexical_rows)
    if mode in ('semantic', 'both'):
        if semantic_embedder is None:
            try:
                from fastembed import TextEmbedding
            except ImportError as exc:
                raise RuntimeError('FastEmbed is required for semantic benchmarking. Install cloud_demo/requirements.txt.') from exc
            semantic_embedder = TextEmbedding(model_name=MODEL_NAME)
        started = perf_counter()
        index = build_index(fixtures, semantic_embedder.embed)
        index_build_s = round(perf_counter() - started, 3)
        # Warm model once so first-query initialization is not counted as usual query latency.
        list(semantic_embedder.embed([queries[0]['question']]))
        def vector_search(patient, question, k):
            embedding = list(semantic_embedder.embed([question]))
            if len(embedding) != 1:
                raise ValueError('Expected exactly one query embedding')
            hits = rank_documents(index, patient_id=patient, query_vector=embedding[0], top_k=k)
            return [hit['document_id'] for hit in hits]
        semantic_rows = evaluate_method(queries, vector_search, 'semantic_vector_cosine')
        rows += semantic_rows
        summaries['semantic_vector_cosine'] = method_summary(semantic_rows)
    result = {
        'project': 'DataHealth AI', 'phase': '17.1 — RAG Retrieval Benchmarking',
        'dataset_type': 'hand-authored fictional benchmark, not Synthea or clinical data',
        'question_count': len(queries), 'patient_count': len({d['patient_id'] for d in docs}),
        'document_count': len(docs), 'retrieval_top_k': 3,
        'semantic_model': MODEL_NAME if mode != 'lexical' else None,
        'semantic_index_build_seconds': index_build_s,
        'methods': summaries,
        'limitations': [
          'Gold labels were manually authored for the constructed notes.',
          'One relevant note is assigned per query; no real clinical relevance annotation.',
          'CPU timing is machine-dependent and excludes model download and Qwen generation.',
          'Semantic metrics require a real local ONNX embedding execution; offline lexical mode does not estimate them.',
          'The isolated benchmark dataset does not replace the public demonstration dataset.',
        ],
    }
    return result, rows


def write_reports(output: Path, summary: dict, rows: list[dict]) -> None:
    output.mkdir(parents=True, exist_ok=True)
    (output / 'benchmark_summary.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
    with (output / 'benchmark_results.jsonl').open('w', encoding='utf-8') as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    with (output / 'benchmark_results.csv').open('w', encoding='utf-8', newline='') as f:
        names = ('query_id','patient_id','method','relevant_document_ids','retrieved_document_ids',
                 'recall_at_1','recall_at_3','reciprocal_rank_at_3','latency_ms','question')
        writer = csv.DictWriter(f, fieldnames=names)
        writer.writeheader()
        for r in rows:
            writer.writerow({name: ';'.join(r[name]) if isinstance(r[name], list) else r[name]
                             for name in names})
    report = [
        '# DataHealth AI — Phase 17.1 Retrieval Benchmark', '',
        f"- Dataset: **{summary['dataset_type']}**",
        f"- Patients: **{summary['patient_count']}**; notes: **{summary['document_count']}**; questions: **{summary['question_count']}**",
        '- Ground truth: hand-authored document IDs, not clinical adjudication.',
        '- Run type: offline retrieval only; **no hosted Qwen API requests**.', '',
        '| Method | Recall@1 | Recall@3 | MRR@3 | Median latency (ms) |',
        '|---|---:|---:|---:|---:|',
    ]
    for method, stats in summary['methods'].items():
        report.append(f"| {method} | {stats['recall_at_1']:.3f} | {stats['recall_at_3']:.3f} | {stats['mrr_at_3']:.3f} | {stats['median_query_latency_ms']:.3f} |")
    report += ['', '## Interpretation', '',
               'Scores describe retrieval against a small purpose-built fictional benchmark. '
               'They do not establish general model superiority or factual/clinical accuracy.', '',
               'Query latency excludes index construction and model download. Small samples and CPU warmup '
               'can strongly affect timings.', '', '## Limitations', '']
    report += [f'- {s}' for s in summary['limitations']]
    (output / 'benchmark_report.md').write_text('\n'.join(report)+'\n', encoding='utf-8')


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Offline lexical-vs-ONNX retrieval benchmark on fictional notes')
    parser.add_argument('run', choices=['run'])
    parser.add_argument('--fixture', default='cloud_demo/benchmark_fixtures.json')
    parser.add_argument('--queries', default='cloud_demo/benchmark_queries.json')
    parser.add_argument('--output', default='reports/rag_benchmark/phase17_1')
    parser.add_argument('--mode', choices=['lexical','semantic','both'], default='both')
    args = parser.parse_args(argv)
    summary, rows = run_benchmark(Path(args.fixture), Path(args.queries), mode=args.mode)
    write_reports(Path(args.output), summary, rows)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
