"""Investigate FHIR data-quality warnings without changing clinical data.

Usage:
    python -m src.review_quality_findings --input data/processed/fhir --output reports/quality_review

The input data are synthetic. Outputs contain metadata for human review; this
module never modifies the source tables or assigns missing clinical units.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

IDENTITY_FIELDS = (
    "observation_code_system", "observation_code",
    "component_code_system", "component_code",
)
REQUIRED_OBSERVATION_FIELDS = (
    "observation_id", "patient_id", "value_type", "unit_code",
    *IDENTITY_FIELDS,
)
SELECTED_OBSERVATION_FIELDS = (
    "patient_id", "observation_id", "component_index", "encounter_id",
    "observation_display", "observation_code_system", "observation_code",
    "component_display", "component_code_system", "component_code",
    "value_type", "value_numeric", "value_unit", "unit_code", "unit_system",
    "effective_datetime", "source_file",
)


def load_csv(path: Path, required_fields: tuple[str, ...]) -> list[dict[str, str]]:
    if not path.is_file():
        raise FileNotFoundError(f"Required input file not found: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"Missing header in CSV: {path}")
        missing = sorted(set(required_fields) - set(reader.fieldnames))
        if missing:
            raise ValueError(f"{path.name} is missing required columns: {missing}")
        return [dict(row) for row in reader]


def write_csv(path: Path, rows: list[dict[str, str]], fields: tuple[str, ...]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def review(input_dir: Path, output_dir: Path) -> dict:
    obs = load_csv(input_dir / "observations.csv", REQUIRED_OBSERVATION_FIELDS)
    docs = load_csv(input_dir / "clinical_documents.csv", ("document_id", "patient_id", "status", "text_content"))
    output_dir.mkdir(parents=True, exist_ok=True)

    quantities = [r for r in obs if r["value_type"].strip().lower() == "quantity"]
    missing_units = [r for r in quantities if not r["unit_code"].strip()]
    write_csv(output_dir / "missing_units_for_review.csv", missing_units, SELECTED_OBSERVATION_FIELDS)

    grouped: dict[tuple[str, ...], list[dict[str, str]]] = defaultdict(list)
    for row in quantities:
        if row["unit_code"].strip():
            key = tuple(row.get(k, "") for k in IDENTITY_FIELDS)
            grouped[key].append(row)

    unit_summary = []
    flagged = []
    for key, rows in sorted(grouped.items()):
        units = Counter(row["unit_code"] for row in rows)
        if len(units) < 2:
            continue
        unit_summary.append({
            **dict(zip(IDENTITY_FIELDS, key)),
            "affected_rows": str(len(rows)),
            "unit_codes": " | ".join(sorted(units)),
            "counts_by_unit": json.dumps(dict(sorted(units.items())), ensure_ascii=False),
            "review_status": "REQUIRES_SEMANTIC_REVIEW",
        })
        flagged.extend(rows)
    write_csv(output_dir / "mixed_unit_groups.csv", unit_summary,
              (*IDENTITY_FIELDS, "affected_rows", "unit_codes", "counts_by_unit", "review_status"))
    write_csv(output_dir / "mixed_unit_records_for_review.csv", flagged, SELECTED_OBSERVATION_FIELDS)

    statuses = Counter((row["status"] or "").strip() or "<blank>" for row in docs)
    status_rows = [{"status": key, "records": str(count)} for key, count in sorted(statuses.items())]
    write_csv(output_dir / "document_status_counts.csv", status_rows, ("status", "records"))

    # Eligibility is a preliminary metadata check, not permission to access or index.
    current_with_text = [row for row in docs if row["status"] == "current" and row["text_content"].strip()]
    candidate_rows = [{
        "document_id": row["document_id"],
        "patient_id": row["patient_id"],
        "status": row["status"],
        "source_file": row.get("source_file", ""),
        "review_status": "CANDIDATE_ONLY_ACCESS_CONTROL_PENDING",
    } for row in current_with_text]
    write_csv(output_dir / "rag_document_candidates_metadata.csv", candidate_rows,
              ("document_id", "patient_id", "status", "source_file", "review_status"))

    result = {
        "project": "DataHealth AI",
        "phase": "Phase 2 — Targeted Data Quality Investigation",
        "source_observation_rows": len(obs),
        "source_clinical_document_rows": len(docs),
        "quantity_rows_missing_unit_code": len(missing_units),
        "mixed_unit_groups": len(unit_summary),
        "mixed_unit_affected_rows": len(flagged),
        "document_status_counts": dict(sorted(statuses.items())),
        "rag_document_candidates_by_status_and_text_only": len(candidate_rows),
        "status": "REVIEW_REQUIRED_NO_DATA_MODIFIED",
        "limitations": (
            "No clinical validity, terminology equivalence, permissions, or FHIR conformance "
            "is established by this report. No clinical values or source files were modified."
        ),
    }
    (output_dir / "quality_review_summary.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect DataHealth AI data-quality findings.")
    parser.add_argument("--input", type=Path, required=True, help="Directory of transformed FHIR CSV tables")
    parser.add_argument("--output", type=Path, required=True, help="Directory for targeted investigation reports")
    args = parser.parse_args()
    result = review(args.input, args.output)
    print(f"Quality review generated at: {args.output.resolve()}")
    print(f"Missing units: {result['quantity_rows_missing_unit_code']}")
    print(f"Mixed-unit measurement groups: {result['mixed_unit_groups']}")
    print(f"Document status distribution: {result['document_status_counts']}")
    print("No clinical records were modified.")


if __name__ == "__main__":
    main()
