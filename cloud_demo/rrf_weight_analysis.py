"""Phase 17.3 — patient-held-out RRF weight analysis on fictional notes.

Offline-only: does not call Qwen, access secrets, or alter Streamlit.
Each of four fictional patients is held out once; RRF weights are selected
using ONLY the other patients' questions. Predeclared weights: [1, 1.5, 2, 3, 4]
(lexical weight = 1). Small, topic-overlapping folds are NOT external validation.
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
from .hybrid_benchmark import rrf_fuse
from .retrieval_benchmark import lexical_rank, retrieval_metrics, validate_queries
from .semantic_retrieval import MODEL_NAME, build_index, note_corpus, rank_documents

SEMANTIC_WEIGHTS = (1.0, 1.5, 2.0, 3.0, 4.0)
RRF_K = 60


def _metric(retrieved: list[str], gold: list[str]) -> dict:
    return retrieval_metrics(retrieved, gold)


def _score(cases: list[dict], weight: float) -> dict:
    """Compute unrounded retrieval scores for weight selection."""
    if not cases:
        raise ValueError('Cannot score an empty evaluation partition')
    values = [_metric(rrf_fuse(c['lexical_ids'], c['semantic_ids'],
                               rrf_k=RRF_K, lexical_weight=1.0,
                               semantic_weight=weight)[:3], c['gold_ids']) for c in cases]
    return {
        'recall_at_1': mean(x['recall_at_1'] for x in values),
        'recall_at_3': mean(x['recall_at_3'] for x in values),
        'mrr_at_3': mean(x['reciprocal_rank_at_3'] for x in values),
    }


def select_weight(training_cases: list[dict], weights=SEMANTIC_WEIGHTS) -> float:
    """Tune on training cases only; ties select the *smaller* weight.

    MRR@3 is primary; Recall@1 and Recall@3 are tie breakers.
    Ties across all metrics favor the smallest semantic weight.
    """
    candidates = []
    for w in weights:
        if isinstance(w, bool) or not isinstance(w, (int, float)) or not math.isfinite(w) or w <= 0:
            raise ValueError('Weights must be finite and positive')
        s = _score(training_cases, float(w))
        candidates.append((s['mrr_at_3'], s['recall_at_1'], s['recall_at_3'], -float(w), float(w)))
    return max(candidates)[-1]


def analyze_rankings(cases: list[dict], weights=SEMANTIC_WEIGHTS) -> tuple[dict, list[dict]]:
    """Cross-validate RRF by patient; input rankings must include ALL patient notes.

    Cases can be produced with a real FastEmbed model or deterministic test fake;
    only runs with the real model should be interpreted as empirical scores.
    """
    if not cases:
        raise ValueError('No cases supplied')
    known = set()
    by_patient: dict[str, list[dict]] = defaultdict(list)
    for case in cases:
        qid, pid = case['query_id'], case['patient_id']
        if qid in known:
            raise ValueError('Duplicate query ID')
        known.add(qid)
        lex, sem = case['lexical_ids'], case['semantic_ids']
        if not lex or len(lex) != len(set(lex)) or set(lex) != set(sem):
            raise ValueError('Lexical and semantic rankings must contain identical unique patient-scoped documents')
        if not set(case['gold_ids']).issubset(lex):
            raise ValueError('Relevant document not present in patient-scoped ranking')
        if len(case['gold_ids']) != len(set(case['gold_ids'])):
            raise ValueError('Duplicate gold relevance label')
        by_patient[pid].append(case)
    if len(by_patient) < 2:
        raise ValueError('At least two patient groups needed for held-out analysis')

    folds = []
    query_rows = []
    for held_out_patient in sorted(by_patient):
        train = [c for pid, records in by_patient.items() if pid != held_out_patient for c in records]
        holdout = by_patient[held_out_patient]
        chosen = select_weight(train, weights)
        folds.append({'held_out_patient': held_out_patient,
                      'training_questions': len(train),
                      'test_questions': len(holdout),
                      'chosen_semantic_weight': chosen,
                      'train_metrics': {str(w): _rounded(_score(train, float(w))) for w in weights}})
        for c in holdout:
            ranked = {
                'lexical': c['lexical_ids'],
                'semantic': c['semantic_ids'],
                'rrf_equal': rrf_fuse(c['lexical_ids'], c['semantic_ids'], rrf_k=RRF_K),
                'rrf_heldout': rrf_fuse(c['lexical_ids'], c['semantic_ids'],
                                        rrf_k=RRF_K, semantic_weight=chosen),
            }
            metrics = {name: _metric(ids[:3], c['gold_ids']) for name, ids in ranked.items()}
            query_rows.append({
                'query_id': c['query_id'], 'patient_id': c['patient_id'],
                'question': c['question'], 'gold_ids': c['gold_ids'],
                'selected_semantic_weight': chosen,
                'top1': {name: ids[0] for name, ids in ranked.items()},
                'top3': {name: ids[:3] for name, ids in ranked.items()},
                'metrics': metrics,
                'rrf_equal_vs_semantic_top1': metrics['rrf_equal']['recall_at_1'] - metrics['semantic']['recall_at_1'],
                'rrf_heldout_vs_semantic_top1': metrics['rrf_heldout']['recall_at_1'] - metrics['semantic']['recall_at_1'],
            })

    methods = ('lexical', 'semantic', 'rrf_equal', 'rrf_heldout')
    aggregates = {}
    for m in methods:
        aggregates[m] = _rounded({
            'recall_at_1': mean(r['metrics'][m]['recall_at_1'] for r in query_rows),
            'recall_at_3': mean(r['metrics'][m]['recall_at_3'] for r in query_rows),
            'mrr_at_3': mean(r['metrics'][m]['reciprocal_rank_at_3'] for r in query_rows),
        })
    changes = {
        ref: {
            'wins': sum(r[f'{ref}_vs_semantic_top1'] > 0 for r in query_rows),
            'ties': sum(r[f'{ref}_vs_semantic_top1'] == 0 for r in query_rows),
            'losses': sum(r[f'{ref}_vs_semantic_top1'] < 0 for r in query_rows),
            'improved_query_ids': [r['query_id'] for r in query_rows if r[f'{ref}_vs_semantic_top1'] > 0],
            'regressed_query_ids': [r['query_id'] for r in query_rows if r[f'{ref}_vs_semantic_top1'] < 0],
        } for ref in ('rrf_equal', 'rrf_heldout')
    }
    summary = {
        'project': 'DataHealth AI',
        'phase': '17.3 - Held-Out RRF Weight Analysis',
        'dataset_type': 'hand-authored fictional notes and queries only',
        'question_count': len(cases),
        'patient_count': len(by_patient),
        'retrieval_top_k': 3,
        'rrf_k': RRF_K,
        'candidate_semantic_weights': list(weights),
        'lexical_weight': 1.0,
        'selection': 'leave-one-fictional-patient-out; select weight from training patients by MRR@3, then Recall@1, Recall@3; ties favor lower weight',
        'folds': folds,
        'methods': aggregates,
        'top1_vs_semantic': changes,
        'decision': 'Do not change public Streamlit retrieval based on this small fictional benchmark alone; keep semantic as current default pending external testing.',
        'limitations': [
            'Only 4 fictional patients, with repeated topical patterns; patient-held-out folds are not an independent clinical dataset.',
            'Each query has a manually assigned relevant note; labels have not been adjudicated for clinical relevance.',
            'The candidate weight grid was selected before evaluation; changing it after seeing results requires a new held-out test set.',
            'Fold-level chosen weights are evaluated only on their respective held-out patients.',
            'No Qwen calls or clinical outcome predictions are evaluated.',
            'Real model download/build/warmup and hardware costs are not included in these retrieval ranking metrics.',
        ],
    }
    return summary, query_rows


def _rounded(scores: dict) -> dict:
    return {key: round(float(value), 4) for key, value in scores.items()}


def build_rankings(fixture_path: Path, query_path: Path, *, embedder=None) -> tuple[list[dict], dict]:
    """Calculate all full patient-scoped ranks just ONCE for all RRF candidates."""
    fixtures = load_fixtures(Path(fixture_path))
    docs = note_corpus(fixtures)
    questions = validate_queries(json.loads(Path(query_path).read_text(encoding='utf-8')), docs)
    if embedder is None:
        try:
            from fastembed import TextEmbedding
        except ImportError as exc:
            raise RuntimeError('FastEmbed is required; install cloud_demo/requirements.txt') from exc
        embedder = TextEmbedding(model_name=MODEL_NAME)
    index_start = perf_counter()
    index = build_index(fixtures, embedder.embed)
    index_sec = perf_counter() - index_start
    if len(list(embedder.embed([questions[0]['question']]))) != 1:
        raise ValueError('Model warmup failed')

    by_patient: dict[str, list[dict]] = defaultdict(list)
    for doc in docs:
        by_patient[doc['patient_id']].append(doc)
    cases = []
    latency = []
    for q in questions:
        patient = q['patient_id']
        count = len(by_patient[patient])
        if not (1 <= count <= 10):
            raise ValueError('Expected 1 to 10 fictional documents per patient')
        lexical_start = perf_counter()
        lex_ids = lexical_rank(docs, patient, q['question'], top_k=count)
        lexical_ms = (perf_counter() - lexical_start) * 1000
        vector_start = perf_counter()
        vector = list(embedder.embed([q['question']]))
        if len(vector) != 1:
            raise ValueError('Expected exactly one query embedding')
        sem_hits = rank_documents(index, patient_id=patient, query_vector=vector[0], top_k=count)
        sem_ids = [x['document_id'] for x in sem_hits]
        vector_ms = (perf_counter() - vector_start) * 1000
        owned = {x['document_id'] for x in by_patient[patient]}
        if set(lex_ids) != owned or set(sem_ids) != owned:
            raise ValueError('Patient isolation or ranking completeness violation')
        latency.append({'lexical_ms': lexical_ms, 'semantic_ms': vector_ms})
        cases.append({'query_id': q['query_id'], 'patient_id': patient,
                      'question': q['question'], 'gold_ids': q['relevant_document_ids'],
                      'lexical_ids': lex_ids, 'semantic_ids': sem_ids})
    return cases, {'embedding_model': MODEL_NAME,
                   'semantic_index_build_seconds': round(index_sec, 3),
                   'mean_lexical_query_latency_ms': round(mean(x['lexical_ms'] for x in latency), 3),
                   'mean_semantic_query_latency_ms': round(mean(x['semantic_ms'] for x in latency), 3),
                   'measurement_note': 'Model warmup/download and index building excluded from per-query latencies; weights re-rank cached lists.'}


def write_reports(output: Path, summary: dict, rows: list[dict]) -> None:
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output / 'weight_analysis_summary.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    with (output / 'weight_analysis_results.jsonl').open('w', encoding='utf-8') as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + '\n')
    cols = ('query_id','patient_id','question','gold_ids','selected_semantic_weight',
            'lexical_top1','semantic_top1','equal_top1','heldout_top1',
            'lexical_recall_at_1','semantic_recall_at_1','equal_recall_at_1',
            'heldout_recall_at_1','semantic_recall_at_3','heldout_recall_at_3')
    with (output / 'weight_analysis_results.csv').open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=cols)
        writer.writeheader()
        for r in rows:
            writer.writerow({
                'query_id': r['query_id'], 'patient_id': r['patient_id'],
                'question': r['question'], 'gold_ids': ';'.join(r['gold_ids']),
                'selected_semantic_weight': r['selected_semantic_weight'],
                'lexical_top1': r['top1']['lexical'],
                'semantic_top1': r['top1']['semantic'],
                'equal_top1': r['top1']['rrf_equal'],
                'heldout_top1': r['top1']['rrf_heldout'],
                'lexical_recall_at_1': r['metrics']['lexical']['recall_at_1'],
                'semantic_recall_at_1': r['metrics']['semantic']['recall_at_1'],
                'equal_recall_at_1': r['metrics']['rrf_equal']['recall_at_1'],
                'heldout_recall_at_1': r['metrics']['rrf_heldout']['recall_at_1'],
                'semantic_recall_at_3': r['metrics']['semantic']['recall_at_3'],
                'heldout_recall_at_3': r['metrics']['rrf_heldout']['recall_at_3'],
            })
    lines = [
        '# DataHealth AI — Phase 17.3 Retrieval Analysis', '',
        'Offline, fictional benchmark. **No hosted Qwen API calls.**',
        'The public Streamlit application is unchanged.', '',
        '## Patient-held-out procedure', '',
        'For each patient group, select the best semantic-to-lexical RRF weight using only the other three patients.',
        'Evaluate that selected weight on the held-out patient. Aggregate all held-out queries.',
        'Do not interpret this as an external validation because document topics are repeated across patients.', '',
        '## Metrics', '',
        '| Strategy | Recall@1 | Recall@3 | MRR@3 |',
        '|---|---:|---:|---:|',
    ]
    for method, s in summary['methods'].items():
        lines.append(f"| {method} | {s['recall_at_1']:.4f} | {s['recall_at_3']:.4f} | {s['mrr_at_3']:.4f} |")
    lines += ['', '## Held-out folds', '',
              '| Test patient | Train questions | Test questions | Selected semantic weight |',
              '|---|---:|---:|---:|']
    for fold in summary['folds']:
        lines.append(f"| {fold['held_out_patient']} | {fold['training_questions']} | {fold['test_questions']} | {fold['chosen_semantic_weight']} |")
    lines += ['', '## Top-1 differences versus semantic', '']
    for method, s in summary['top1_vs_semantic'].items():
        lines.append(f"- `{method}`: wins={s['wins']}, ties={s['ties']}, losses={s['losses']}; "
                     f"improved: {', '.join(s['improved_query_ids']) or 'none'}; "
                     f"regressed: {', '.join(s['regressed_query_ids']) or 'none'}.")
    lines += ['', '## Query-level error analysis', '',
              '| Query | Gold | Lexical #1 | Semantic #1 | Equal RRF #1 | Held-out RRF #1 |',
              '|---|---|---|---|---|---|']
    for r in sorted(rows, key=lambda x: x['query_id']):
        tops = r['top1']
        lines.append(f"| {r['query_id']} | {', '.join(r['gold_ids'])} | {tops['lexical']} | {tops['semantic']} | {tops['rrf_equal']} | {tops['rrf_heldout']} |")
    lines += ['', '## Decision', '', summary['decision'], '', '## Limitations', '']
    lines += [f'- {x}' for x in summary['limitations']]
    lines += ['', '## Next phase', '',
              'Phase 18 starts independently of whether weighted RRF beats semantic retrieval. '
              'Plan a separate patient-level and time-aware ML experiment with purely synthetic data; '
              'do not claim clinical predictive validity.', '']
    (output / 'weight_analysis_report.md').write_text('\n'.join(lines), encoding='utf-8')


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Offline, patient-held-out RRF weight comparison (fictional benchmark)')
    parser.add_argument('run', choices=['run'])
    parser.add_argument('--fixture', default='cloud_demo/benchmark_fixtures.json')
    parser.add_argument('--queries', default='cloud_demo/benchmark_queries.json')
    parser.add_argument('--output', default='reports/rag_benchmark/phase17_3')
    args = parser.parse_args(argv)
    cases, performance = build_rankings(Path(args.fixture), Path(args.queries))
    summary, rows = analyze_rankings(cases)
    summary['retrieval_performance'] = performance
    write_reports(Path(args.output), summary, rows)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
