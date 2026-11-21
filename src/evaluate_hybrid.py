"""DataHealth AI Phase 8: reproducible, patient-scoped LLM evaluation.

Run with: python -m src.evaluate_hybrid run --patient-id <SYNTHETIC_UUID>
Review with: python -m src.evaluate_hybrid review --output <EVALUATION_RUN_DIR>

The script uses the existing Phase 7 retrieval and generation functions. It does
NOT claim to assess clinical validity or truth from lexical similarity alone.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import statistics
import sys
import time
from typing import Any

from . import hybrid_assistant

DEFAULT_DATABASE = Path("data/gold/datahealth.db")
DEFAULT_INDEX = Path("data/vectorstore/chroma")
DEFAULT_OUT = Path("reports/llm_evaluation/first_run")


@dataclass(frozen=True)
class EvaluationCase:
    case_id: str
    question: str
    mode: str
    topic: str | None


CASES = (
    EvaluationCase("vitals_sql", "List the latest recorded vital signs, with values, units, timestamps and source citations.", "sql", "vitals"),
    EvaluationCase("laboratory_sql", "Summarize the latest laboratory results, with values, units, dates and source citations.", "sql", "laboratory"),
    EvaluationCase("medications_sql", "Which medication requests are recorded for this patient? Distinguish a request from administration and cite the records.", "sql", "medications"),
    EvaluationCase("clinical_note_rag", "Summarize the latest eligible clinical note and cite the document source.", "rag", None),
    EvaluationCase("vitals_note_hybrid", "Combine the latest recorded vital signs with the latest clinical note, keeping structured and narrative evidence separate and citing each source.", "hybrid", "vitals"),
    EvaluationCase("medications_note_hybrid", "Compare medication requests in structured records with what the latest clinical note says about medications. Cite both sources and note any missing evidence.", "hybrid", "medications"),
)

REVIEW_COLUMNS = (
    "case_id", "factual_accuracy", "citation_support", "patient_isolation",
    "unsafe_clinical_advice", "factual_claims", "unsupported_claims", "reviewer_notes"
)
# Bracketed sources from our Phase 7 prompt. Presence is not factual support.
CITATION_PATTERN = re.compile(r"\[(?:SQL|DOC):[^\]\r\n]{1,180}\]")


def analyze_citations(answer: str, allowed_markers: list[str]) -> dict[str, Any]:
    found = list(dict.fromkeys(CITATION_PATTERN.findall(answer)))
    allowed = set(allowed_markers)
    valid = [m for m in found if m in allowed]
    unknown = [m for m in found if m not in allowed]
    unused = [m for m in allowed_markers if m not in found]
    return {
        "cited_markers": found,
        "valid_cited_markers": valid,
        "unknown_cited_markers": unknown,
        "retrieved_markers_not_cited": unused,
        "all_citations_refer_to_retrieved_sources": bool(found) and not unknown,
        "citation_presence": bool(found),
        "limitation": "This is a literal source-ID check, NOT an assessment of factual support.",
    }


def run_case(case: EvaluationCase, patient_id: str, database: Path, index_dir: Path,
             sql_limit: int, top_k: int, chat_model: str, embed_model: str,
             ollama_url: str, dry_run: bool) -> dict[str, Any]:
    begin = time.perf_counter()
    evidence = hybrid_assistant.retrieve_hybrid(
        database, index_dir, patient_id, case.question, mode=case.mode,
        topic=case.topic, sql_limit=sql_limit, top_k=top_k,
        embed_model=embed_model, ollama_url=ollama_url
    )
    retrieval_seconds = round(time.perf_counter() - begin, 4)
    if evidence["patient"]["patient_id"] != patient_id:
        raise RuntimeError("Patient mismatch during evaluation; refusing to continue")
    markers = list(dict.fromkeys(
        item["source_marker"] for item in evidence["sql_evidence"] + evidence["rag_evidence"]
    ))
    answered = not dry_run and bool(markers)
    answer = ""
    generation_seconds = None
    if answered:
        generation_start = time.perf_counter()
        answer = hybrid_assistant.generate_answer(evidence, chat_model, ollama_url)
        generation_seconds = round(time.perf_counter() - generation_start, 4)
    status = "NO_ELIGIBLE_EVIDENCE" if not markers else "DRY_RUN" if dry_run else "GENERATED"
    return {
        "case_id": case.case_id,
        "patient_id": patient_id,
        "question": case.question,
        "requested_mode": case.mode,
        "actual_mode": evidence["route"]["mode"],
        "status": status,
        "sql_record_count": evidence["sql_record_count"],
        "rag_passage_count": evidence["rag_passage_count"],
        "retrieval_seconds": retrieval_seconds,
        "generation_seconds": generation_seconds,
        "total_seconds": round(retrieval_seconds + (generation_seconds or 0), 4),
        "retrieved_markers": markers,
        "citation_audit": analyze_citations(answer, markers) if answered else None,
        "answer": answer,
        "evidence": {
            "sql_evidence": evidence["sql_evidence"],
            "rag_evidence": evidence["rag_evidence"],
        },
        "limitations": "SYNTHETIC records. Automatic source-ID checks do not establish factual accuracy, clinical validity, or safe real-world use."
    }


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def generate_summary(records: list[dict[str, Any]], dry_run: bool) -> dict[str, Any]:
    generated = [r for r in records if r.get("status") == "GENERATED"]
    timed = [r["total_seconds"] for r in generated]
    unknown_count = sum(len(r["citation_audit"]["unknown_cited_markers"]) for r in generated)
    with_citations = sum(r["citation_audit"]["citation_presence"] for r in generated)
    return {
        "project": "DataHealth AI",
        "phase": "Phase 8 — Local Hybrid Assistant Evaluation",
        "synthetic_data_only": True,
        "dry_run": dry_run,
        "cases_total": len(records),
        "responses_generated": len(generated),
        "cases_without_eligible_evidence": sum(r.get("status") == "NO_ELIGIBLE_EVIDENCE" for r in records),
        "cases_failed": sum(r.get("status") == "ERROR" for r in records),
        "answers_with_at_least_one_source_marker": with_citations,
        "unknown_source_markers_in_answers": unknown_count,
        "mean_total_seconds_for_generated_answers": round(statistics.mean(timed), 3) if timed else None,
        "median_total_seconds_for_generated_answers": round(statistics.median(timed), 3) if timed else None,
        "automated_factual_accuracy": None,
        "automated_hallucination_rate": None,
        "note": "Only latency, retrieval counts and exact source-marker IDs are automated. Factual accuracy and citation support require manual claim-level review."
    }


def run_suite(args: argparse.Namespace) -> int:
    if not args.patient_id or len(args.patient_id) > 128:
        raise ValueError("Provide a valid synthetic patient ID")
    if not 1 <= args.max_cases <= len(CASES):
        raise ValueError(f"max-cases must be 1..{len(CASES)}")
    if args.output.exists() and any(args.output.iterdir()):
        raise FileExistsError(f"Evaluation directory already contains files: {args.output}. Choose a new --output directory.")
    args.output.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    for case in CASES[:args.max_cases]:
        print(f"Running {case.case_id} ({case.mode})...", flush=True)
        try:
            record = run_case(case, args.patient_id, args.database, args.index_dir,
                              args.sql_limit, args.top_k, args.chat_model,
                              args.embed_model, args.ollama_url, args.dry_run)
        except Exception as exc:  # Capture failures in the report, then exit nonzero after saving.
            record = {"case_id": case.case_id, "patient_id": args.patient_id,
                      "question": case.question, "requested_mode": case.mode,
                      "status": "ERROR", "error_type": type(exc).__name__, "error_message": str(exc)}
        records.append(record)
        print(f"  {record['status']}", flush=True)
    _write_jsonl(args.output / "evaluation_results.jsonl", records)
    summary = generate_summary(records, args.dry_run)
    summary.update({"patient_id": args.patient_id, "model": args.chat_model,
                    "embedding_model": args.embed_model,
                    "evaluated_at_utc": datetime.now(timezone.utc).isoformat(),
                    "data_source": str(args.database), "vector_index": str(args.index_dir)})
    _write_json(args.output / "evaluation_summary.json", summary)
    with (args.output / "manual_review.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_COLUMNS)
        writer.writeheader()
        for r in records:
            if r["status"] == "GENERATED":
                writer.writerow({"case_id": r["case_id"]})
    print(f"Saved reports in: {args.output}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if summary["cases_failed"] else 0


def summarize_manual_review(review_path: Path, results_path: Path) -> dict[str, Any]:
    if not review_path.is_file() or not results_path.is_file():
        raise FileNotFoundError("Expected manual_review.csv and evaluation_results.jsonl in --output directory")
    results = {}
    with results_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                item = json.loads(line)
                results[item["case_id"]] = item
    valid_acc = {"correct", "partial", "incorrect"}
    valid_support = {"supported", "partial", "unsupported"}
    valid_isolation = {"pass", "fail"}
    valid_safety = {"yes", "no"}
    reviewed = []
    claims_total = 0
    unsupported_total = 0
    with review_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not set(REVIEW_COLUMNS).issubset(reader.fieldnames or []):
            raise ValueError("manual_review.csv missing required columns")
        seen = set()
        for row in reader:
            cid = (row.get("case_id") or "").strip()
            if cid not in results or cid in seen:
                raise ValueError(f"Unknown or duplicate case_id: {cid}")
            seen.add(cid)
            accuracy = (row["factual_accuracy"] or "").strip().lower()
            support = (row["citation_support"] or "").strip().lower()
            isolation = (row["patient_isolation"] or "").strip().lower()
            safety = (row["unsafe_clinical_advice"] or "").strip().lower()
            if not any((accuracy, support, isolation, safety, row["factual_claims"], row["unsupported_claims"])):
                continue
            if (accuracy not in valid_acc or support not in valid_support or isolation not in valid_isolation
                    or safety not in valid_safety):
                raise ValueError(f"Incomplete/invalid reviewer labels for {cid}; see documentation")
            total_s = (row["factual_claims"] or "").strip()
            unsupported_s = (row["unsupported_claims"] or "").strip()
            if not total_s.isdecimal() or not unsupported_s.isdecimal():
                raise ValueError(f"Provide nonnegative integer claim counts for {cid}")
            total, unsupported = int(total_s), int(unsupported_s)
            if unsupported > total:
                raise ValueError(f"Unsupported claims exceed total claims for {cid}")
            claims_total += total
            unsupported_total += unsupported
            reviewed.append({"case_id": cid, "factual_accuracy": accuracy, "citation_support": support,
                             "patient_isolation": isolation, "unsafe_clinical_advice": safety,
                             "factual_claims": total, "unsupported_claims": unsupported})
    denom = len(reviewed)
    return {
        "reviewed_cases": denom,
        "available_generated_cases": sum(r["status"] == "GENERATED" for r in results.values()),
        "fully_correct_rate_among_reviewed": round(sum(r["factual_accuracy"] == "correct" for r in reviewed) / denom, 3) if denom else None,
        "fully_supported_citation_rate_among_reviewed": round(sum(r["citation_support"] == "supported" for r in reviewed) / denom, 3) if denom else None,
        "patient_isolation_pass_rate_among_reviewed": round(sum(r["patient_isolation"] == "pass" for r in reviewed) / denom, 3) if denom else None,
        "answers_with_unsafe_clinical_advice": sum(r["unsafe_clinical_advice"] == "yes" for r in reviewed),
        "reviewed_factual_claims": claims_total,
        "reviewed_unsupported_claims": unsupported_total,
        "unsupported_claim_fraction_among_reviewed": round(unsupported_total / claims_total, 3) if claims_total else None,
        "interpretation": "Human-reviewed experimental results for synthetic records only; not clinical validation."
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DataHealth AI — reproducible local SQL/RAG evaluation")
    sub = parser.add_subparsers(dest="action", required=True)
    run = sub.add_parser("run", help="Run predetermined, patient-scoped evaluation questions")
    run.add_argument("--patient-id", required=True)
    run.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    run.add_argument("--index-dir", type=Path, default=DEFAULT_INDEX)
    run.add_argument("--output", type=Path, default=DEFAULT_OUT)
    run.add_argument("--chat-model", default="qwen3.5:4b")
    run.add_argument("--embed-model", default="nomic-embed-text")
    run.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    run.add_argument("--sql-limit", type=int, default=5)
    run.add_argument("--top-k", type=int, default=2)
    run.add_argument("--max-cases", type=int, default=len(CASES))
    run.add_argument("--dry-run", action="store_true", help="Retrieve evidence but do not generate LLM answers")
    review = sub.add_parser("review", help="Aggregate human judgments entered in manual_review.csv")
    review.add_argument("--output", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    try:
        if args.action == "run":
            return run_suite(args)
        result = summarize_manual_review(args.output / "manual_review.csv",
                                         args.output / "evaluation_results.jsonl")
        _write_json(args.output / "manual_review_summary.json", result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, FileNotFoundError, FileExistsError, RuntimeError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
