"""Build an auditable, conservative Silver Layer from transformed synthetic FHIR CSVs.

No clinical code/unit conversions are performed. All observation rows are retained,
with explicit review flags. Source CSV and JSON files are never modified.

Usage:
    python -m src.build_silver --input data/processed/fhir --output data/silver/fhir \
        --reports reports/silver
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime
import json
from pathlib import Path

SOURCE_TABLES = (
    "patients", "encounters", "observations", "conditions",
    "diagnostic_reports", "diagnostic_report_results",
    "medication_requests", "clinical_documents",
)


def load_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.is_file():
        raise FileNotFoundError(f"Required transformed table not found: {path}")
    with path.open("r", newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames:
            raise ValueError(f"CSV has no header: {path}")
        return list(reader.fieldnames), list(reader)


def write_csv(path: Path, columns: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def parse_iso(value: str) -> bool:
    if not value.strip():
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def key_for_measurement(row: dict[str, str]) -> tuple[str, str, str, str]:
    return tuple(row.get(k, "") for k in (
        "observation_code_system", "observation_code",
        "component_code_system", "component_code",
    ))


def validate_links(tables: dict[str, list[dict[str, str]]]) -> dict[str, int]:
    patient_ids = {r["patient_id"] for r in tables["patients"] if r["patient_id"]}
    encounter_ids = {r["encounter_id"] for r in tables["encounters"] if r["encounter_id"]}
    observation_ids = {r["observation_id"] for r in tables["observations"] if r["observation_id"]}
    report_ids = {r["report_id"] for r in tables["diagnostic_reports"] if r["report_id"]}
    results = {}
    for table_name in ("encounters", "observations", "conditions", "diagnostic_reports", "medication_requests", "clinical_documents"):
        rows = tables[table_name]
        results[f"{table_name}_unknown_patient_refs"] = sum(
            bool(r.get("patient_id")) and r["patient_id"] not in patient_ids for r in rows
        )
    for table_name in ("observations", "conditions", "diagnostic_reports", "medication_requests"):
        results[f"{table_name}_unknown_encounter_refs"] = sum(
            bool(r.get("encounter_id")) and r["encounter_id"] not in encounter_ids for r in tables[table_name]
        )
    results["result_links_unknown_observation"] = sum(
        bool(r.get("observation_id")) and r["observation_id"] not in observation_ids
        for r in tables["diagnostic_report_results"]
    )
    results["result_links_unknown_report"] = sum(
        bool(r.get("report_id")) and r["report_id"] not in report_ids
        for r in tables["diagnostic_report_results"]
    )
    return results


def build_silver(source: Path, output: Path, reports: Path) -> dict:
    if not source.is_dir():
        raise NotADirectoryError(f"Source directory does not exist: {source}")
    if source.resolve() == output.resolve():
        raise ValueError("Output must not overwrite the transformed input tables.")

    headers = {}
    tables = {}
    for table_name in SOURCE_TABLES:
        headers[table_name], tables[table_name] = load_csv(source / f"{table_name}.csv")

    patient_ids = {r["patient_id"] for r in tables["patients"] if r["patient_id"]}
    encounter_ids = {r["encounter_id"] for r in tables["encounters"] if r["encounter_id"]}
    unit_sets = defaultdict(set)
    for r in tables["observations"]:
        if r.get("value_type") == "quantity" and r.get("unit_code"):
            unit_sets[key_for_measurement(r)].add(r["unit_code"])
    mixed_keys = {key for key, units in unit_sets.items() if len(units) > 1}
    issues = Counter()
    output_observations = []
    flagged = []
    observation_keys = set()
    for original in tables["observations"]:
        r = dict(original)
        flags = []
        if not r.get("observation_id"):
            flags.append("MISSING_OBSERVATION_ID")
        if not r.get("patient_id"):
            flags.append("MISSING_PATIENT_ID")
        elif r["patient_id"] not in patient_ids:
            flags.append("UNKNOWN_PATIENT_REFERENCE")
        if r.get("encounter_id") and r["encounter_id"] not in encounter_ids:
            flags.append("UNKNOWN_ENCOUNTER_REFERENCE")
        if not r.get("observation_code"):
            flags.append("MISSING_OBSERVATION_CODE")
        if not parse_iso(r.get("effective_datetime", "")):
            flags.append("MISSING_OR_INVALID_EFFECTIVE_DATETIME")
        if r.get("value_type") == "quantity":
            if not r.get("unit_code"):
                flags.append("MISSING_UNIT_CODE")
            if key_for_measurement(r) in mixed_keys:
                flags.append("MIXED_UNIT_CODING")
            try:
                float(r.get("value_numeric", ""))
            except (TypeError, ValueError):
                flags.append("INVALID_NUMERIC_VALUE")
        if r.get("value_type") == "unsupported_or_missing":
            flags.append("UNSUPPORTED_OR_MISSING_VALUE_TYPE")
        row_key = (r.get("observation_id", ""), r.get("component_index", ""))
        if row_key in observation_keys:
            flags.append("DUPLICATE_OBSERVATION_COMPONENT")
        observation_keys.add(row_key)
        for flag in flags:
            issues[flag] += 1
        r["quality_status"] = "REVIEW_REQUIRED" if flags else "PASS_STRUCTURAL_CHECKS"
        r["quality_flags"] = "|".join(flags)
        output_observations.append(r)
        if flags:
            flagged.append(r)

    write_csv(output / "observations.csv", headers["observations"] + ["quality_status", "quality_flags"], output_observations)
    write_csv(reports / "observations_for_review.csv", headers["observations"] + ["quality_status", "quality_flags"], flagged)

    candidates = []
    docs = []
    status_counts = Counter()
    for original in tables["clinical_documents"]:
        r = dict(original)
        status_counts[r.get("status") or "<missing>"] += 1
        flags = []
        if r.get("status") != "current":
            flags.append("NON_CURRENT_DOCUMENT")
        if not r.get("text_content", "").strip():
            flags.append("EMPTY_TEXT")
        if not r.get("patient_id") or r["patient_id"] not in patient_ids:
            flags.append("UNKNOWN_OR_MISSING_PATIENT_REFERENCE")
        r["rag_candidate_status"] = "PRELIMINARY_ONLY_NOT_AUTHORIZED" if not flags else "EXCLUDED_PENDING_REVIEW"
        r["rag_review_flags"] = "|".join(flags)
        docs.append(r)
        if not flags:
            candidates.append(r)
    doc_columns = headers["clinical_documents"] + ["rag_candidate_status", "rag_review_flags"]
    write_csv(output / "clinical_documents.csv", doc_columns, docs)
    write_csv(reports / "rag_preliminary_candidates.csv", doc_columns, candidates)

    for table_name in SOURCE_TABLES:
        if table_name not in ("observations", "clinical_documents"):
            write_csv(output / f"{table_name}.csv", headers[table_name], tables[table_name])

    links = validate_links(tables)
    summary = {
        "project": "DataHealth AI",
        "phase": "Phase 3 — Conservative Silver Layer (structural only)",
        "source_input": str(source),
        "silver_output": str(output),
        "input_counts": {name: len(tables[name]) for name in SOURCE_TABLES},
        "silver_observation_rows": len(output_observations),
        "observations_flagged_for_review": len(flagged),
        "observation_flag_counts": dict(sorted(issues.items())),
        "mixed_measurement_groups": len(mixed_keys),
        "document_status_counts": dict(sorted(status_counts.items())),
        "rag_preliminary_candidates": len(candidates),
        "reference_integrity_findings": links,
        "policy": "No medical unit conversions or recoding. No rows removed. No input files modified. Preliminary RAG candidates are not authorized for clinical use.",
    }
    reports.mkdir(parents=True, exist_ok=True)
    with (reports / "silver_summary.json").open("w", encoding="utf-8") as stream:
        json.dump(summary, stream, indent=2, ensure_ascii=False)
    lines = [
        "# Silver Layer — Structural Validation Report", "",
        "## Scope", "",
        "Conservative structural checks of synthetic FHIR-derived CSVs. This is not clinical or full FHIR validation.", "",
        "## Record counts", "",
        "| Table | Rows |", "|---|---:|",
        *[f"| {name} | {len(tables[name])} |" for name in SOURCE_TABLES],
        "", "## Observations", "",
        f"- Flagged rows: **{len(flagged)}** of **{len(output_observations)}**.",
        f"- Measurement groups with mixed unit codes: **{len(mixed_keys)}**.",
        *[f"- `{name}`: {count}" for name, count in sorted(issues.items())],
        "", "## Documents", "",
        f"- Preliminary RAG candidate documents: **{len(candidates)}**.",
        "- Candidate status alone does not imply permission to index or disclose a document.",
        *[f"- Status `{status}`: {count}" for status, count in sorted(status_counts.items())],
        "", "## Referential integrity", "",
        *[f"- `{name}`: {count}" for name, count in sorted(links.items())],
        "", "## Guardrails", "",
        "- Original source files and numeric clinical values remain unchanged.",
        "- Mixed units and missing unit codes remain flagged for manual semantic review.",
        "- Non-current documents are preserved but excluded from preliminary RAG candidates.",
        "- Identity matching, access control, terminology validation, and clinical safety checks remain future work.",
    ]
    (reports / "silver_validation_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Build conservative Silver Layer from transformed FHIR CSVs.")
    parser.add_argument("--input", type=Path, required=True, help="Directory of transformed FHIR CSVs")
    parser.add_argument("--output", type=Path, required=True, help="Output Silver directory")
    parser.add_argument("--reports", type=Path, required=True, help="Quality report directory")
    args = parser.parse_args()
    summary = build_silver(args.input, args.output, args.reports)
    print("Silver Layer build completed (structural checks only).")
    print(f"Observations: {summary['silver_observation_rows']}")
    print(f"Flagged observations: {summary['observations_flagged_for_review']}")
    print(f"Preliminary RAG document candidates: {summary['rag_preliminary_candidates']}")
    print(f"Review report: {args.reports / 'silver_summary.json'}")


if __name__ == "__main__":
    main()
