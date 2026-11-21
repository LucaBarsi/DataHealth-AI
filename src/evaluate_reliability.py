"""Phase 8.1: repeat Phase 8 evaluation with citation-controlled generation.

Same six question cases and retrieval settings as Phase 8.
Reports distinguish validated citation IDs, model fallbacks and failed calls.
No automatic factual-accuracy or hallucination-rate estimate is produced.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics
import sys
import time
from typing import Any

from . import evaluate_hybrid, hybrid_assistant, reliable_assistant

DEFAULT_OUT = Path("reports/llm_evaluation/reliability_run")
DEFAULT_BASELINE = Path("reports/llm_evaluation/full_run/evaluation_results.jsonl")


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def run_reliability_case(case, patient_id: str, args: argparse.Namespace) -> dict[str, Any]:
    started = time.perf_counter()
    evidence = hybrid_assistant.retrieve_hybrid(
        args.database, args.index_dir, patient_id, case.question, mode=case.mode,
        topic=case.topic, sql_limit=args.sql_limit, top_k=args.top_k,
        embed_model=args.embed_model, ollama_url=args.ollama_url
    )
    retrieval_seconds = round(time.perf_counter() - started, 4)
    if evidence["patient"]["patient_id"] != patient_id:
        raise RuntimeError("Evidence patient_id does not match the selected patient")
    gen_started = time.perf_counter()
    generated = reliable_assistant.generate_reliable_answer(
        evidence, args.chat_model, args.ollama_url, args.max_retries
    )
    generation_seconds = round(time.perf_counter() - gen_started, 4)
    cited = evaluate_hybrid.analyze_citations(
        generated["answer"], reliable_assistant.allowed_markers(evidence)
    ) if generated["status"] != "NO_ELIGIBLE_EVIDENCE" else None
    if generated["status"] in ("CITATION_IDS_VALID", "EVIDENCE_ONLY_FALLBACK"):
        if not cited or not cited["all_citations_refer_to_retrieved_sources"]:
            raise RuntimeError("Displayed output contains an unknown source identifier")
    return {
        "case_id": case.case_id,
        "patient_id": patient_id,
        "question": case.question,
        "requested_mode": case.mode,
        "actual_mode": evidence["route"]["mode"],
        "status": "GENERATED" if generated["status"] == "CITATION_IDS_VALID"
                  else generated["status"],
        "guard_status": generated["status"],
        "generation_attempts": generated["attempts"],
        "attempt_history": generated.get("attempt_history", []),
        "sql_record_count": evidence["sql_record_count"],
        "rag_passage_count": evidence["rag_passage_count"],
        "retrieval_seconds": retrieval_seconds,
        "generation_seconds": generation_seconds,
        "total_seconds": round(time.perf_counter() - started, 4),
        "retrieved_markers": reliable_assistant.allowed_markers(evidence),
        "citation_audit": cited,
        "answer": generated["answer"],
        "warning": generated["warning"],
        "evidence": {
            "sql_evidence": evidence["sql_evidence"],
            "rag_evidence": evidence["rag_evidence"],
        },
        "limitations": "Citation-ID checks are NOT factual or clinical validation."
    }


def summary_for(records: list[dict[str, Any]]) -> dict[str, Any]:
    generated = [r for r in records if r.get("guard_status") == "CITATION_IDS_VALID"]
    fallbacks = [r for r in records if r.get("guard_status") == "EVIDENCE_ONLY_FALLBACK"]
    times = [r["total_seconds"] for r in generated]
    return {
        "project": "DataHealth AI",
        "phase": "Phase 8.1 — Citation Reliability",
        "cases_total": len(records),
        "citation_ids_valid_responses": len(generated),
        "evidence_only_fallbacks": len(fallbacks),
        "without_eligible_evidence": sum(r.get("status") == "NO_ELIGIBLE_EVIDENCE" for r in records),
        "cases_failed": sum(r.get("status") == "ERROR" for r in records),
        "retry_attempts_total": sum(max(0, r.get("generation_attempts", 0) - 1) for r in records),
        "unknown_source_markers_in_displayed_answers": sum(
            len((r.get("citation_audit") or {}).get("unknown_cited_markers", []))
            for r in records
        ),
        "mean_total_seconds_for_validated_responses": round(statistics.mean(times), 3) if times else None,
        "automated_factual_accuracy": None,
        "automated_hallucination_rate": None,
        "note": "No fabricated citation IDs are displayed. Valid IDs do NOT prove that cited claims are accurate."
    }


def compare_baseline(records: list[dict[str, Any]], baseline: Path) -> dict[str, Any]:
    if not baseline.is_file():
        return {"status": "BASELINE_NOT_FOUND", "path": str(baseline)}
    base_rows = [json.loads(line) for line in baseline.read_text(encoding="utf-8").splitlines() if line.strip()]
    old_by_case = {r.get("case_id"): r for r in base_rows}
    pairs = [
        (old_by_case[r["case_id"]], r) for r in records
        if r["case_id"] in old_by_case and
        old_by_case[r["case_id"]].get("question") == r.get("question")
    ]
    old_unknown = sum(len((old.get("citation_audit") or {}).get("unknown_cited_markers", [])) for old, _ in pairs)
    new_unknown = sum(len((new.get("citation_audit") or {}).get("unknown_cited_markers", [])) for _, new in pairs)
    return {
        "status": "QUESTION_MATCHED_BASELINE",
        "baseline_path": str(baseline),
        "matched_cases": len(pairs),
        "baseline_unknown_source_markers": old_unknown,
        "new_unknown_source_markers_in_displayed_answers": new_unknown,
        "new_fallbacks_among_matched": sum(
            new.get("guard_status") == "EVIDENCE_ONLY_FALLBACK" for _, new in pairs
        ),
        "limitation": "Only citation IDs are compared automatically. No factual accuracy inference.",
    }


def run_suite(args: argparse.Namespace) -> int:
    if args.output.exists() and any(args.output.iterdir()):
        raise FileExistsError("Output directory is nonempty; choose a NEW --output folder")
    if not args.patient_id or len(args.patient_id) > 128:
        raise ValueError("Provide a valid synthetic patient ID")
    if not 1 <= args.max_cases <= len(evaluate_hybrid.CASES):
        raise ValueError("max-cases out of range")
    args.output.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    for case in evaluate_hybrid.CASES[:args.max_cases]:
        print(f"Evaluating {case.case_id}...", flush=True)
        try:
            record = run_reliability_case(case, args.patient_id, args)
        except Exception as exc:
            record = {
                "case_id": case.case_id, "question": case.question,
                "patient_id": args.patient_id, "status": "ERROR",
                "error_type": type(exc).__name__, "error_message": str(exc),
            }
        print(f"  {record['status']}", flush=True)
        records.append(record)
    with (args.output / "evaluation_results.jsonl").open("w", encoding="utf-8", newline="\n") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    summary = summary_for(records)
    summary.update({
        "patient_id": args.patient_id,
        "model": args.chat_model,
        "embedding_model": args.embed_model,
        "evaluated_at_utc": datetime.now(timezone.utc).isoformat(),
    })
    _write_json(args.output / "evaluation_summary.json", summary)
    _write_json(args.output / "comparison_to_baseline.json", compare_baseline(records, args.baseline))
    with (args.output / "manual_review.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=evaluate_hybrid.REVIEW_COLUMNS)
        writer.writeheader()
        for r in records:
            if r.get("guard_status") == "CITATION_IDS_VALID":
                writer.writerow({"case_id": r["case_id"]})
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if summary["cases_failed"] else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Repeat Phase 8 questions with citation guard")
    parser.add_argument("--patient-id", required=True)
    parser.add_argument("--database", type=Path, default=hybrid_assistant.DEFAULT_DATABASE)
    parser.add_argument("--index-dir", type=Path, default=hybrid_assistant.DEFAULT_INDEX)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--chat-model", default=hybrid_assistant.DEFAULT_CHAT_MODEL)
    parser.add_argument("--embed-model", default=hybrid_assistant.DEFAULT_EMBED_MODEL)
    parser.add_argument("--ollama-url", default=hybrid_assistant.DEFAULT_OLLAMA_URL)
    parser.add_argument("--sql-limit", type=int, default=5)
    parser.add_argument("--top-k", type=int, default=2)
    parser.add_argument("--max-cases", type=int, default=6)
    parser.add_argument("--max-retries", type=int, default=1)
    args = parser.parse_args(argv)
    try:
        return run_suite(args)
    except (ValueError, FileNotFoundError, RuntimeError, FileExistsError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
