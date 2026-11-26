"""Phase 17.2 — offline lexical + semantic Reciprocal Rank Fusion benchmark.

Runs ONLY on the separated, hand-authored fictional Phase 17.1 fixtures.
Does not modify the deployed Streamlit application, call the hosted Qwen API,
or read any real patient data. Uses one shared local FastEmbed instance (ONNX).

Equal-weight RRF is a preselected baseline rather than a tuned result.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path
from statistics import mean
from time import perf_counter

from .demo_backend import load_fixtures
from .retrieval_benchmark import (
    lexical_rank, method_summary, retrieval_metrics, validate_queries,
)
from .semantic_retrieval import MODEL_NAME, build_index, note_corpus, rank_documents

METHODS = ('lexical_keywords', 'semantic_vector_cosine', 'hybrid_rrf')


def rrf_fuse(lexical_ids: list[str], semantic_ids: list[str], *,
             rrf_k: int = 60, lexical_weight: float = 1.0,
             semantic_weight: float = 1.0) -> list[str]:
    """Fuse two complete *patient-scoped* rankings using weighted RRF.

    score(d) = lexical_weight/(rrf_k + lexical_rank(d))
             + semantic_weight/(rrf_k + semantic_rank(d)).

    The caller must scope source rankings to one patient before fusion.
    These scores are for ranking only, never probabilities or clinical evidence.
    """
    if type(rrf_k) is not int or rrf_k < 1:
        raise ValueError('rrf_k must be a positive integer')
    for weight in (lexical_weight, semantic_weight):
        if isinstance(weight, bool) or not isinstance(weight, (float, int)) or not math.isfinite(weight) or weight <= 0:
            raise ValueError('RRF weights must be finite and strictly positive')
    for ranking in (lexical_ids, semantic_ids):
        if not isinstance(ranking, list) or len(ranking) != len(set(ranking)):
            raise ValueError('Each ranking must be a list without duplicates')
        if not all(isinstance(doc, str) and doc for doc in ranking):
            raise ValueError('Document IDs must be nonempty strings')
    if not lexical_ids or not semantic_ids:
        raise ValueError('Both rankings must be nonempty')
    # In this benchmark both systems must rank the exact same patient notes.
    # Do not silently accept mismatched retrieval scopes.
    if set(lexical_ids) != set(semantic_ids):
        raise ValueError('Rankings must contain the same patient-scoped document IDs')

    score: dict[str, float] = defaultdict(float)
    best_rank: dict[str, int] = {}
    for ranking, weight in ((lexical_ids, lexical_weight),
                            (semantic_ids, semantic_weight)):
        for position, document_id in enumerate(ranking, 1):
            score[document_id] += weight / (rrf_k + position)
            best_rank[document_id] = min(best_rank.get(document_id, position), position)
    return sorted(score, key=lambda did: (-score[did], best_rank[did], did))


def _make_row(query: dict, method: str, ids: list[str], elapsed_ms: float) -> dict:
    top3 = ids[:3]
    return {
        'query_id': query['query_id'],
        'patient_id': query['patient_id'],
        'question': query['question'],
        'method': method,
        'relevant_document_ids': list(query['relevant_document_ids']),
        'retrieved_document_ids': top3,
        'latency_ms': round(elapsed_ms, 3),
        **retrieval_metrics(top3, query['relevant_document_ids']),
    }


def _pairwise_deltas(rows: list[dict]) -> dict:
    """Count top-1 improvements/regressions on identical queries, not people."""
    by_query: dict[str, dict[str, dict]] = defaultdict(dict)
    for row in rows:
        by_query[row['query_id']][row['method']] = row
    comparisons = {}
    for reference in ('lexical_keywords', 'semantic_vector_cosine'):
        wins = ties = losses = 0
        improvements = []
        regressions = []
        for query_id, group in sorted(by_query.items()):
            delta = (group['hybrid_rrf']['recall_at_1'] - group[reference]['recall_at_1'])
            if delta > 0:
                wins += 1
                improvements.append(query_id)
            elif delta < 0:
                losses += 1
                regressions.append(query_id)
            else:
                ties += 1
        comparisons[reference] = {
            'hybrid_top1_wins': wins,
            'hybrid_top1_ties': ties,
            'hybrid_top1_losses': losses,
            'improved_query_ids': improvements,
            'regressed_query_ids': regressions,
        }
    return comparisons


def run_hybrid_benchmark(fixture_path: Path, query_path: Path, *,
                         embedder=None, rrf_k: int = 60,
                         lexical_weight: float = 1.0,
                         semantic_weight: float = 1.0) -> tuple[dict, list[dict]]:
    """Benchmark three retrieval methods with the same queries, notes and labels."""
    fixtures = load_fixtures(Path(fixture_path))
    docs = note_corpus(fixtures)
    query_payload = json.loads(Path(query_path).read_text(encoding='utf-8'))
    queries = validate_queries(query_payload, docs)
    documents_by_patient: dict[str, list[dict]] = defaultdict(list)
    for doc in docs:
        documents_by_patient[doc['patient_id']].append(doc)
    if any(len(group) > 10 for group in documents_by_patient.values()):
        raise ValueError('Phase 17.2 benchmark is limited to 10 documents per patient')

    if embedder is None:
        try:
            from fastembed import TextEmbedding
        except ImportError as exc:
            raise RuntimeError('Install cloud_demo/requirements.txt to benchmark real FastEmbed embeddings') from exc
        embedder = TextEmbedding(model_name=MODEL_NAME)

    started = perf_counter()
    index = build_index(fixtures, embedder.embed)
    index_build_s = round(perf_counter() - started, 3)
    # Warmup is outside the per-query timing, as in Phase 17.1.
    if len(list(embedder.embed([queries[0]['question']]))) != 1:
        raise ValueError('Embedding warmup failed')

    rows = []
    for q in queries:
        patient = q['patient_id']
        k_all = len(documents_by_patient[patient])
        if not k_all:
            raise ValueError(f'No documents for patient {patient}')
        total_start = perf_counter()

        lexical_start = perf_counter()
        lexical_ids = lexical_rank(docs, patient, q['question'], top_k=k_all)
        lexical_ms = (perf_counter() - lexical_start) * 1000

        semantic_start = perf_counter()
        query_vectors = list(embedder.embed([q['question']]))
        if len(query_vectors) != 1:
            raise ValueError('Expected exactly one query vector')
        semantic_hits = rank_documents(index, patient_id=patient,
                                       query_vector=query_vectors[0], top_k=k_all)
        semantic_ids = [hit['document_id'] for hit in semantic_hits]
        semantic_ms = (perf_counter() - semantic_start) * 1000

        hybrid_ids = rrf_fuse(lexical_ids, semantic_ids, rrf_k=rrf_k,
                              lexical_weight=lexical_weight,
                              semantic_weight=semantic_weight)
        hybrid_ms = (perf_counter() - total_start) * 1000

        owner = {doc['document_id']: doc['patient_id'] for doc in docs}
        for rank in (lexical_ids, semantic_ids, hybrid_ids):
            if any(owner[did] != patient for did in rank):
                raise ValueError('Cross-patient retrieval blocked')

        rows.append(_make_row(q, METHODS[0], lexical_ids, lexical_ms))
        rows.append(_make_row(q, METHODS[1], semantic_ids, semantic_ms))
        rows.append(_make_row(q, METHODS[2], hybrid_ids, hybrid_ms))

    summaries = {method: method_summary([r for r in rows if r['method'] == method])
                 for method in METHODS}
    summary = {
        'project': 'DataHealth AI',
        'phase': '17.2 - Hybrid Retrieval (RRF)',
        'dataset_type': 'hand-authored fictional benchmark, not clinical data',
        'question_count': len(queries),
        'patient_count': len(documents_by_patient),
        'document_count': len(docs),
        'retrieval_top_k': 3,
        'embedding_model': MODEL_NAME,
        'semantic_index_build_seconds': index_build_s,
        'fusion': {'algorithm': 'weighted_reciprocal_rank_fusion',
                   'rrf_k': rrf_k, 'lexical_weight': lexical_weight,
                   'semantic_weight': semantic_weight,
                   'selection': 'preselected equal weights unless manually changed'},
        'methods': summaries,
        'hybrid_top1_comparisons': _pairwise_deltas(rows),
        'limitations': [
            'One hand-authored relevant fictional note per query; no clinical relevance adjudication.',
            'The benchmark is small (28 questions, 32 notes), purpose-built, and not representative of real workloads.',
            'Index build time and model download are excluded from per-query latency.',
            'No Qwen calls are made; these are retrieval metrics, not answer-level factual accuracy.',
            'RRF parameters are a priori defaults. Tuning on these same 28 queries would risk overfitting.',
            'The cloud app and its production demo data are unchanged by this benchmark.',
        ],
    }
    return summary, rows


def write_hybrid_reports(output: Path, summary: dict, rows: list[dict]) -> None:
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output / 'hybrid_summary.json').write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    with (output / 'hybrid_results.jsonl').open('w', encoding='utf-8') as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + '\n')
    columns = ('query_id', 'patient_id', 'method', 'relevant_document_ids',
               'retrieved_document_ids', 'recall_at_1', 'recall_at_3',
               'reciprocal_rank_at_3', 'latency_ms', 'question')
    with (output / 'hybrid_results.csv').open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: ';'.join(row[key]) if isinstance(row[key], list) else row[key]
                             for key in columns})
    per_query = defaultdict(dict)
    for row in rows:
        per_query[row['query_id']][row['method']] = row
    lines = [
        '# Phase 17.2 — Hybrid Retrieval Benchmark', '',
        'Synthetic benchmark only: 4 fictional patients, 32 notes, 28 queries.',
        'All three methods use the same input notes and hand-authored relevance labels.',
        'No hosted Qwen requests or clinical claims are evaluated.', '',
        '## Results', '',
        '| Method | Recall@1 | Recall@3 | MRR@3 | Mean latency (ms) |',
        '|---|---:|---:|---:|---:|',
    ]
    for method in METHODS:
        stat = summary['methods'][method]
        lines.append(f"| {method} | {stat['recall_at_1']:.4f} | {stat['recall_at_3']:.4f} | {stat['mrr_at_3']:.4f} | {stat['mean_query_latency_ms']:.3f} |")
    lines += ['', '## Individual query analysis', '',
              '| Query | Gold document | Lexical #1 | Semantic #1 | Hybrid #1 |',
              '|---|---|---|---|---|']
    for query_id, group in sorted(per_query.items()):
        gold = '; '.join(group[METHODS[0]]['relevant_document_ids'])
        tops = [(group[m]['retrieved_document_ids'] or ['—'])[0] for m in METHODS]
        lines.append(f'| {query_id} | {gold} | {tops[0]} | {tops[1]} | {tops[2]} |')
    lines += ['', '## Hybrid compared with baseline — top-1', '']
    for baseline, stats in summary['hybrid_top1_comparisons'].items():
        lines.append(f"- Versus `{baseline}`: wins **{stats['hybrid_top1_wins']}**, "
                     f"ties **{stats['hybrid_top1_ties']}**, losses **{stats['hybrid_top1_losses']}**; "
                     f"improved queries: {', '.join(stats['improved_query_ids']) or 'none'}; "
                     f"regressed queries: {', '.join(stats['regressed_query_ids']) or 'none'}.")
    lines += ['', '## Interpretation and caveats', '',
              'RRF combines rank positions without treating cosine scores and lexical overlap as directly comparable.',
              'A hybrid method is **not automatically better**; use the observed results to choose a retrieval method.',
              'With a single relevant note per query, Recall@1 is also the top-1 hit rate.',
              'Record evaluation data separately from public deployment; do not copy benchmark fixtures into `sample_records.json`.',
              '', '### Limitations', '']
    lines += [f'- {limit}' for limit in summary['limitations']]
    (output / 'hybrid_report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Offline RRF benchmark: lexical vs semantic vs hybrid on fictional notes')
    parser.add_argument('run', choices=['run'])
    parser.add_argument('--fixture', default='cloud_demo/benchmark_fixtures.json')
    parser.add_argument('--queries', default='cloud_demo/benchmark_queries.json')
    parser.add_argument('--output', default='reports/rag_benchmark/phase17_2')
    parser.add_argument('--rrf-k', type=int, default=60)
    parser.add_argument('--lexical-weight', type=float, default=1.0)
    parser.add_argument('--semantic-weight', type=float, default=1.0)
    args = parser.parse_args(argv)
    summary, rows = run_hybrid_benchmark(Path(args.fixture), Path(args.queries),
                                         rrf_k=args.rrf_k,
                                         lexical_weight=args.lexical_weight,
                                         semantic_weight=args.semantic_weight)
    write_hybrid_reports(Path(args.output), summary, rows)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
