"""Audit transformed Synthea FHIR tables without modifying source data.

Usage:
    python -m src.validate_fhir --input data/processed/fhir --output reports/data_quality

This educational audit checks referential integrity, duplicates, missing fields,
value types, dates, units, and safe document indexing eligibility. It is NOT a
clinical/FHIR conformance validator. Source data are synthetic.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


TABLES: dict[str, dict[str, Any]] = {
    "patients": {"key": ["patient_id"], "required": ["patient_id"]},
    "encounters": {"key": ["encounter_id"], "required": ["encounter_id", "patient_id"]},
    "observations": {
        "key": ["observation_id", "component_index"],
        "required": ["observation_id", "patient_id", "observation_code", "status"],
    },
    "conditions": {"key": ["condition_id"], "required": ["condition_id", "patient_id"]},
    "diagnostic_reports": {"key": ["report_id"], "required": ["report_id", "patient_id"]},
    "diagnostic_report_results": {"key": ["report_id", "observation_id"], "required": ["report_id", "observation_id"]},
    "medication_requests": {"key": ["medication_request_id"], "required": ["medication_request_id", "patient_id"]},
    "clinical_documents": {"key": ["document_id"], "required": ["document_id", "patient_id", "status"]},
}

DATE_FIELDS = {
    "patients": ["birth_date"],
    "encounters": ["start_time", "end_time"],
    "observations": ["effective_datetime", "issued_datetime"],
    "conditions": ["onset_datetime", "recorded_date"],
    "diagnostic_reports": ["effective_datetime", "issued_datetime"],
    "medication_requests": ["authored_on"],
    "clinical_documents": ["document_date"],
}


def _parse_date(value: str) -> datetime | None:
    """Parse common FHIR date/dateTime forms, preserving UTC-aware comparisons."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        # Partial FHIR dates (year or year-month) are valid but not precise
        # enough for chronological comparisons; they are separately left as-is.
        if len(value) == 4 and value.isdigit():
            return datetime(int(value), 1, 1, tzinfo=timezone.utc)
        if len(value) == 7 and value[4] == "-":
            try:
                return datetime(int(value[:4]), int(value[5:]), 1, tzinfo=timezone.utc)
            except ValueError:
                pass
        return None


def _examples(frame: pd.DataFrame, mask: pd.Series, columns: list[str], limit: int = 4) -> str:
    columns = [name for name in columns if name in frame.columns]
    if not columns:
        return ""
    return "; ".join("/".join(str(v) for v in row) for row in
                     frame.loc[mask, columns].head(limit).itertuples(index=False, name=None))


def _plot_counts(counts: dict[str, int], output: Path) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("Chart skipped: install matplotlib to generate record_counts.png")
        return
    selected = [(k, v) for k, v in counts.items() if v > 0]
    fig, ax = plt.subplots(figsize=(10, 5.5))
    ax.barh([name.replace("_", " ").title() for name, _ in reversed(selected)],
            [count for _, count in reversed(selected)])
    ax.set_title("DataHealth AI — Transformed Record Counts")
    ax.set_xlabel("Rows (not unique FHIR resources)")
    fig.tight_layout()
    fig.savefig(output / "record_counts.png", dpi=160)
    plt.close(fig)


def audit(input_dir: Path, output_dir: Path, make_charts: bool = True) -> dict[str, Any]:
    if not input_dir.is_dir():
        raise FileNotFoundError(f"Input directory does not exist: {input_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    frames: dict[str, pd.DataFrame] = {}
    issues: list[dict[str, Any]] = []
    checked = Counter()
    counts: dict[str, int] = {}

    def add(severity: str, rule: str, table: str, count: int, samples: str = "", detail: str = "") -> None:
        if count:
            issues.append({
                "severity": severity, "rule": rule, "table": table,
                "affected_rows": int(count), "sample_record_ids": samples,
                "details": detail,
            })

    # Strictly load the schemas emitted by the preceding transform_fhir.py stage.
    for table, spec in TABLES.items():
        path = input_dir / f"{table}.csv"
        if not path.is_file():
            raise FileNotFoundError(f"Required table not found: {path}")
        frame = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8")
        needed = set(spec["key"] + spec["required"])
        missing_columns = sorted(needed - set(frame.columns))
        if missing_columns:
            raise ValueError(f"{table}.csv missing columns: {missing_columns}")
        frames[table] = frame
        counts[table] = len(frame)
        for field in spec["required"]:
            missing = frame[field].str.strip().eq("")
            checked[f"required_field_checks"] += 1
            add("ERROR", f"missing_required:{field}", table, int(missing.sum()),
                _examples(frame, missing, spec["key"]), "Blank required field")
        duplicate = frame.duplicated(subset=spec["key"], keep=False)
        add("ERROR", "duplicate_business_key", table, int(duplicate.sum()),
            _examples(frame, duplicate, spec["key"]),
            "For observations, the key is observation_id + component_index; one observation may have multiple components.")

        if "source_file" in frame.columns:
            empty_source = frame["source_file"].str.strip().eq("")
            add("WARNING", "missing_source_file", table, int(empty_source.sum()),
                _examples(frame, empty_source, spec["key"]), "Keep source provenance for traceability")

        for field in DATE_FIELDS.get(table, []):
            if field not in frame.columns:
                continue
            date_series = frame[field].str.strip()
            non_empty = date_series.ne("")
            invalid = non_empty & date_series.map(lambda x: _parse_date(x) is None)
            add("WARNING", f"invalid_datetime:{field}", table, int(invalid.sum()),
                _examples(frame, invalid, spec["key"]), "Unparseable FHIR date/dateTime")
            checked["date_fields_checked"] += 1

    patients = frames["patients"]
    patient_ids = set(patients.loc[patients.patient_id.ne(""), "patient_id"])
    encounter_frame = frames["encounters"]
    encounter_ids = set(encounter_frame.loc[encounter_frame.encounter_id.ne(""), "encounter_id"])
    report_frame = frames["diagnostic_reports"]
    report_ids = set(report_frame.loc[report_frame.report_id.ne(""), "report_id"])
    observation_frame = frames["observations"]
    observation_ids = set(observation_frame.loc[observation_frame.observation_id.ne(""), "observation_id"])

    # Verify non-empty references, without falsely treating absent optional links as broken.
    for table, frame in frames.items():
        if "patient_id" in frame.columns and table != "patients":
            mask = frame.patient_id.ne("") & ~frame.patient_id.isin(patient_ids)
            add("ERROR", "unresolved_patient_reference", table, int(mask.sum()),
                _examples(frame, mask, TABLES[table]["key"]), "Patient must exist in patients.csv")
        if "encounter_id" in frame.columns and table != "encounters":
            mask = frame.encounter_id.ne("") & ~frame.encounter_id.isin(encounter_ids)
            add("ERROR", "unresolved_encounter_reference", table, int(mask.sum()),
                _examples(frame, mask, TABLES[table]["key"]), "A populated encounter_id must resolve")

    # Verify the encounter belongs to the same patient as the linked record.
    owners = encounter_frame.drop_duplicates("encounter_id").set_index("encounter_id")["patient_id"]
    for table in ["observations", "conditions", "diagnostic_reports", "medication_requests"]:
        frame = frames[table]
        linked = frame.encounter_id.ne("") & frame.encounter_id.isin(owners.index) & frame.patient_id.ne("")
        owner = frame.encounter_id.map(owners).fillna("")
        mismatch = linked & owner.ne("") & frame.patient_id.ne(owner)
        add("ERROR", "encounter_patient_mismatch", table, int(mismatch.sum()),
            _examples(frame, mismatch, TABLES[table]["key"]), "Linked encounter and record have different patient IDs")

    links = frames["diagnostic_report_results"]
    for column, valid_ids in [("report_id", report_ids), ("observation_id", observation_ids)]:
        missing = links[column].ne("") & ~links[column].isin(valid_ids)
        add("ERROR", f"unresolved_{column}_reference", "diagnostic_report_results", int(missing.sum()),
            _examples(links, missing, ["report_id", "observation_id"]), "Diagnostic report result link must resolve")

    # Every observation is classified by explicit source value type, not guessed from text.
    obs = observation_frame
    if "value_type" in obs.columns:
        unknown = obs.value_type.eq("unsupported_or_missing") | obs.value_type.eq("")
        add("WARNING", "unsupported_or_missing_observation_value", "observations", int(unknown.sum()),
            _examples(obs, unknown, ["observation_id", "component_index"]),
            "Inspect source FHIR; do not fill missing clinical values automatically")
        quantity = obs.value_type.eq("quantity")
        numeric = pd.to_numeric(obs.get("value_numeric", pd.Series("", index=obs.index)), errors="coerce")
        bad_numeric = quantity & ~numeric.notna()
        add("ERROR", "invalid_numeric_quantity", "observations", int(bad_numeric.sum()),
            _examples(obs, bad_numeric, ["observation_id", "component_index"]), "Quantity must contain a numeric value")
        if "unit_code" in obs.columns:
            missing_unit = quantity & obs.unit_code.str.strip().eq("")
            add("WARNING", "missing_quantity_unit_code", "observations", int(missing_unit.sum()),
                _examples(obs, missing_unit, ["observation_id", "component_index"]),
                "Review whether the observation is unitless or missing units; never assume a unit")
            # Same clinically-coded measurement should not silently merge distinct UCUM units.
            code_cols = ["observation_code_system", "observation_code", "component_code_system", "component_code"]
            if all(col in obs for col in code_cols):
                q = obs.loc[quantity & obs.unit_code.ne("")].copy()
                if not q.empty:
                    groups = q.groupby(code_cols, dropna=False)["unit_code"].nunique()
                    mixed = groups[groups.gt(1)]
                    for code_tuple in mixed.index[:100]:
                        subset = q
                        for col, val in zip(code_cols, code_tuple):
                            subset = subset[subset[col].eq(val)]
                        unit_examples = ", ".join(sorted(subset.unit_code.unique())[:6])
                        add("WARNING", "mixed_unit_codes", "observations", len(subset),
                            _examples(subset, pd.Series(True, index=subset.index), ["observation_id", "component_index"]),
                            f"Measurement code={code_tuple}; units={unit_examples}. Validate semantics before normalization.")

    if "start_time" in encounter_frame and "end_time" in encounter_frame:
        start = encounter_frame.start_time.map(_parse_date)
        end = encounter_frame.end_time.map(_parse_date)
        invalid_order = pd.Series([(s is not None and e is not None and e < s)
                                   for s, e in zip(start, end)], index=encounter_frame.index)
        add("ERROR", "encounter_end_before_start", "encounters", int(invalid_order.sum()),
            _examples(encounter_frame, invalid_order, ["encounter_id"]))

    docs = frames["clinical_documents"]
    if "status" in docs.columns:
        non_current = docs.status.ne("current")
        add("INFO", "document_not_current", "clinical_documents", int(non_current.sum()),
            _examples(docs, non_current, ["document_id"]),
            "Do not automatically index superseded or entered-in-error documents into RAG")
        if "text_content" in docs.columns:
            not_indexable = docs.status.eq("current") & docs.text_content.str.strip().eq("")
            add("WARNING", "current_document_without_text", "clinical_documents", int(not_indexable.sum()),
                _examples(docs, not_indexable, ["document_id"]),
                "Text-based RAG cannot index missing text; inspect attachment format")

    # Compare output counts against the actual stage-1 transformation summary if present.
    source_summary = input_dir / "transformation_summary.json"
    if source_summary.exists():
        with source_summary.open("r", encoding="utf-8") as f:
            expected = json.load(f)
        for table, actual in counts.items():
            stage_count = expected.get(f"out_{table}")
            if stage_count is not None and int(stage_count) != actual:
                add("ERROR", "transformation_count_mismatch", table, abs(int(stage_count) - actual),
                    detail=f"Summary says {stage_count} but file contains {actual} rows")

    issues_frame = pd.DataFrame(issues, columns=[
        "severity", "rule", "table", "affected_rows", "sample_record_ids", "details"
    ])
    issues_frame.to_csv(output_dir / "quality_issues.csv", index=False, encoding="utf-8")

    rule_totals = Counter(row["severity"] for row in issues)
    result = {
        "project": "DataHealth AI",
        "phase": "Phase 2 — Data Cleaning & Validation (audit only)",
        "input_path": str(input_dir),
        "row_counts": counts,
        "unique_patient_ids": len(patient_ids),
        "unique_observation_ids": len(observation_ids),
        "observation_rows": counts["observations"],
        "issues_by_severity": dict(rule_totals),
        "checks_recorded": len(issues),
        "overall_status": "REVIEW_REQUIRED" if any(i["severity"] == "ERROR" for i in issues)
                           else "NO_CRITICAL_ISSUES_FOUND",
        "interpretation_note": "No clinical or full FHIR conformance validation was performed. No input files were modified.",
    }
    (output_dir / "quality_summary.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    def md_escape(s: Any) -> str:
        return str(s).replace("|", "\\|").replace("\n", " ")
    lines = [
        "# DataHealth AI — Data Quality Assessment",
        "", "## Scope", "", "Audit of CSV tables generated from synthetic FHIR R4 records.",
        "Inputs represent candidate **Silver-layer** tables; the original FHIR JSONs remain the **Bronze layer**.",
        "This phase reports potential issues; it does **not** automatically alter any clinical values.",
        "", "## Table inventory", "", "| Table | Rows |", "|---|---:|",
    ]
    lines.extend(f"| `{table}` | {n:,} |" for table, n in counts.items())
    lines.extend([
        "", "## Audit outcome", "", f"**Status:** `{result['overall_status']}`", "",
        "| Severity | Number of distinct checks with findings |", "|---|---:|",
    ])
    lines.extend(f"| {severity} | {rule_totals[severity]} |" for severity in ["ERROR", "WARNING", "INFO"])
    lines.extend(["", "## Findings", "", "| Severity | Table | Rule | Affected rows |", "|---|---|---|---:|"])
    if issues:
        lines.extend(f"| {r['severity']} | {md_escape(r['table'])} | {md_escape(r['rule'])} | {r['affected_rows']:,} |" for r in issues)
    else:
        lines.append("| — | — | No findings from implemented checks | 0 |")
    lines.extend([
        "", "## Interpretation and next actions", "",
        "1. Investigate any `ERROR` findings against the original JSON resources before approving Silver data.",
        "2. Review all missing or mixed UCUM units using LOINC definitions; avoid automatic clinical assumptions.",
        "3. Verify clinical-document status and permissions before any RAG indexing.",
        "4. Maintain patient, encounter, observation, and report lineage in downstream SQL tables.",
        "5. Record every accepted data-cleaning rule in `docs/transformation_log.md` and rerun the audit.",
        "", "## Important limitations", "",
        "- This script does not establish clinical correctness, FHIR specification conformance, or regulatory compliance.",
        "- A zero-error summary means only that the implemented checks found no critical issues.",
        "- Issue counts may overlap: the same record can appear in more than one check.",
        "- The data are synthetic, not suitable for clinical decision-making.",
    ])
    (output_dir / "quality_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    if make_charts:
        _plot_counts(counts, output_dir)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit DataHealth AI transformed FHIR CSV data.")
    parser.add_argument("--input", type=Path, required=True, help="Directory containing transformed FHIR CSV tables")
    parser.add_argument("--output", type=Path, required=True, help="Directory for audit reports")
    parser.add_argument("--no-charts", action="store_true", help="Skip optional matplotlib chart")
    args = parser.parse_args()
    result = audit(args.input, args.output, make_charts=not args.no_charts)
    print(f"Data quality audit completed: {args.output.resolve()}")
    print(f"Patient IDs: {result['unique_patient_ids']}")
    print(f"Observation rows: {result['observation_rows']}")
    print(f"Overall audit status: {result['overall_status']}")
    print(f"Findings by severity: {result['issues_by_severity']}")
    print("Review quality_report.md and quality_issues.csv before any data cleaning.")


if __name__ == "__main__":
    main()
