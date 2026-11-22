"""Reproducible DataHealth AI cloud-demo evaluation (illustrative data only).

DEFAULT: offline, ZERO API calls. Live mode requires --confirm-live and
QWEN_API_BASE_URL, QWEN_MODEL_ID, QWEN_API_KEY in local environment variables.
Do not commit these environment variables or put real secrets in reports.

From project root:
  python -m cloud_demo.evaluate_cloud --output reports/cloud_eval/offline
  python -m cloud_demo.evaluate_cloud --mode live --confirm-live \\
      --patient-id DEMO-P001 --max-cases 2 --output reports/cloud_eval/live_smoke
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from time import perf_counter

from .demo_backend import (
    allowed_markers, citation_check, evidence_only_answer, list_patients,
    load_fixtures, open_demo_database, retrieve_evidence,
)
from .remote_inference import RemoteInferenceError, remote_qwen_answer
from .suggested_questions import SUGGESTED_QUESTIONS
from .scope_validation import negative_claim_check, retrieval_scope

HERE = Path(__file__).resolve().parent
MANUAL_COLUMNS = [
    'case_id', 'factual_accuracy', 'citation_support', 'patient_isolation',
    'unsafe_clinical_advice', 'factual_claims', 'unsupported_claims', 'reviewer_notes',
]


def owner_index(fixtures: dict) -> dict[str, str]:
    """Map every synthetic source reference to ONE patient. Fail on duplicates."""
    result: dict[str, str] = {}
    for person in fixtures['patients']:
        patient_id = person['patient_id']
        for category, id_key, prefix in (
            ('observations', 'observation_id', 'SQL'),
            ('conditions', 'condition_id', 'SQL'),
            ('medications', 'request_id', 'SQL'),
            ('notes', 'document_id', 'DOC'),
        ):
            for item in person.get(category, []):
                suffix = '#chunk:0' if prefix == 'DOC' else ''
                marker = f'[{prefix}:{item[id_key]}{suffix}]'
                if marker in result:
                    raise ValueError(f'Duplicate source marker in demo fixtures: {marker}')
                result[marker] = patient_id
    return result


def sample_cases(fixtures: dict, *, patient_id: str | None = None, max_cases: int | None = None) -> list[dict]:
    all_patients = fixtures['patients']
    if patient_id:
        all_patients = [p for p in all_patients if p['patient_id'] == patient_id]
        if not all_patients:
            raise ValueError('Unknown fictional patient')
    cases = [
        {'case_id': f'{p["patient_id"]}:{i+1:02d}', 'patient_id': p['patient_id'],
         'prompt_label': label, 'question': question}
        for p in all_patients for i, (label, question) in enumerate(SUGGESTED_QUESTIONS)
    ]
    if max_cases is not None:
        if max_cases < 1:
            raise ValueError('max_cases must be positive')
        cases = cases[:max_cases]
    return cases


def run_evaluation(
    *, fixtures_path: Path, mode: str = 'offline',
    patient_id: str | None = None, max_cases: int | None = None,
    live_settings: dict | None = None,
    clock=perf_counter,
) -> tuple[dict, list[dict]]:
    """Evaluate retrieval (offline), or run a small explicitly opted-in live check.

    Citation exactness is automatable; factual accuracy, claim support,
    diagnosis safety and prompt injection resistance require human review.
    """
    if mode not in {'offline', 'live'}:
        raise ValueError('Unsupported evaluation mode')
    data = load_fixtures(fixtures_path)
    owners = owner_index(data)
    conn = open_demo_database(data)
    results: list[dict] = []
    try:
        for case in sample_cases(data, patient_id=patient_id, max_cases=max_cases):
            started = clock()
            evidence = retrieve_evidence(conn, case['patient_id'], case['question'], mode='auto')
            markers = allowed_markers(evidence)
            isolation_ok = evidence['patient']['patient_id'] == case['patient_id'] and all(
                owners.get(marker) == case['patient_id'] for marker in markers
            )
            if not isolation_ok:
                raise ValueError('Patient isolation invariant failed')
            answer = evidence_only_answer(evidence)
            status = 'EVIDENCE_ONLY'
            error_code = None
            # In offline mode the deterministic answer is NOT an LLM sample.
            if mode == 'live' and markers:
                if not live_settings:
                    raise ValueError('Live mode requires explicit credentials/configuration')
                try:
                    generated = remote_qwen_answer(
                        evidence=evidence, question=case['question'], **live_settings,
                    )
                    checked = citation_check(generated, evidence)
                    if checked['valid']:
                        scoped = negative_claim_check(generated, evidence)
                        if scoped['valid']:
                            answer = generated
                            status = 'CITATION_IDS_VALID'
                        else:
                            status = 'EVIDENCE_ONLY_FALLBACK'
                            error_code = 'EVIDENCE_SCOPE_VIOLATION'
                    else:
                        status = 'EVIDENCE_ONLY_FALLBACK'
                        error_code = 'CITATION_CHECK_FAILED'
                except RemoteInferenceError as error:
                    status = 'EVIDENCE_ONLY_FALLBACK'
                    error_code = error.code
            elif mode == 'live':
                status = 'NO_ELIGIBLE_EVIDENCE'
            check = citation_check(answer, evidence)
            results.append({
                **case, 'mode': mode, 'retrieval_mode': evidence['routing']['mode'],
                'status': status, 'patient_isolation_pass': isolation_ok,
                'evidence_count': len(markers), 'exact_citations_pass': check['valid'] if markers else None,
                'unknown_source_marker_count': len(check['unknown']),
                'retrieval_scope': retrieval_scope(evidence),
                'retrieval_counts': {
                    k: len(evidence[k]) for k in ('observations', 'conditions', 'medications', 'notes')
                },
                'latency_seconds': round(clock() - started, 4),
                'safe_failure_code': error_code,
                'evidence': evidence, 'displayed_answer': answer,
            })
    finally:
        conn.close()

    valid_answers = sum(r['status'] == 'CITATION_IDS_VALID' for r in results)
    fallback_count = sum(r['status'] == 'EVIDENCE_ONLY_FALLBACK' for r in results)
    summary = {
        'project': 'DataHealth AI', 'phase': 'Phase 16 — Cloud Evaluation & Security',
        'data': 'Handcrafted fictional demo fixtures only', 'mode': mode,
        'evaluated_at_utc': datetime.now(timezone.utc).isoformat(),
        'cases_total': len(results), 'patients_included': len(set(r['patient_id'] for r in results)),
        'patient_isolation_passed': sum(r['patient_isolation_pass'] for r in results),
        'citations_with_unknown_markers': sum(r['unknown_source_marker_count'] for r in results),
        'hosted_answers_validated': valid_answers, 'hosted_fallbacks': fallback_count,
        'total_evidence_records_retrieved': sum(sum(r['retrieval_counts'].values()) for r in results),
        'mean_end_to_end_seconds': round(sum(r['latency_seconds'] for r in results)/len(results), 4) if results else None,
        'automated_factual_accuracy': None, 'automated_hallucination_rate': None,
        'interpretation': 'Citation marker validity does not verify claim-level factual support. Review the answer and its evidence manually.',
    }
    return summary, results


def write_reports(output: Path, summary: dict, cases: list[dict]) -> None:
    output.mkdir(parents=True, exist_ok=True)
    (output / 'evaluation_summary.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding='utf-8')
    with (output / 'evaluation_results.jsonl').open('w', encoding='utf-8') as file:
        for row in cases:
            file.write(json.dumps(row, ensure_ascii=False) + '\n')
    with (output / 'manual_review.csv').open('w', encoding='utf-8', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=MANUAL_COLUMNS)
        writer.writeheader()
        # Review only generated LLM responses; not deterministic fallback text.
        for row in cases:
            if row['status'] == 'CITATION_IDS_VALID':
                writer.writerow({'case_id': row['case_id']})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='DataHealth AI fictional cloud evaluation (offline by default)')
    parser.add_argument('--mode', choices=['offline', 'live'], default='offline')
    parser.add_argument('--patient-id', help='One fictional ID, e.g. DEMO-P001')
    parser.add_argument('--max-cases', type=int, help='Limit number of prompt cases')
    parser.add_argument('--output', default='reports/cloud_evaluation/phase16_offline')
    parser.add_argument('--confirm-live', action='store_true', help='Explicitly authorize remote API requests')
    args = parser.parse_args(argv)
    cfg = None
    if args.mode == 'live':
        if not args.confirm_live:
            parser.error('Live mode requires --confirm-live (possible provider usage)')
        if args.max_cases is None or not 1 <= args.max_cases <= 6:
            parser.error('Live mode requires --max-cases between 1 and 6')
        cfg = {
            'api_base': os.getenv('QWEN_API_BASE_URL', ''),
            'model_id': os.getenv('QWEN_MODEL_ID', ''),
            'api_key': os.getenv('QWEN_API_KEY', ''),
        }
        if not all(cfg.values()):
            parser.error('Live mode requires QWEN_API_BASE_URL, QWEN_MODEL_ID and QWEN_API_KEY in environment')
    summary, results = run_evaluation(
        fixtures_path=HERE / 'sample_records.json', mode=args.mode,
        patient_id=args.patient_id, max_cases=args.max_cases, live_settings=cfg,
    )
    write_reports(Path(args.output), summary, results)
    print(json.dumps({k: v for k, v in summary.items() if k not in ('interpretation',)}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
