"""Flatten selected Synthea FHIR R4 resources into traceable CSV tables.

This is an educational ETL prototype for synthetic records, not a FHIR validator
or a clinically validated data pipeline. Original JSONs remain the source of truth.

Usage:
    python -m src.transform_fhir --input data/raw/synthea_sample_data_fhir_latest \
        --output data/processed/fhir
"""
from __future__ import annotations

import argparse
import base64
from collections import Counter
import csv
import json
from pathlib import Path
from typing import Any, Iterator


SCHEMAS: dict[str, list[str]] = {
    "patients": ["patient_id", "first_name", "last_name", "full_name", "gender", "birth_date", "source_file", "fhir_profiles"],
    "encounters": [
        "encounter_id", "patient_id", "status", "class_code", "type_code",
        "type_display", "start_time", "end_time", "source_file", "fhir_profiles",
    ],
    "observations": [
        "observation_id", "patient_id", "encounter_id", "status", "category",
        "observation_code_system", "observation_code", "observation_display",
        "component_index", "component_code_system", "component_code", "component_display",
        "value_type", "value_numeric", "value_unit", "unit_code", "unit_system",
        "value_text", "value_code_system", "value_code", "effective_datetime",
        "issued_datetime", "source_file", "fhir_profiles",
    ],
    "conditions": [
        "condition_id", "patient_id", "encounter_id", "code_system", "code",
        "display", "clinical_status", "verification_status", "onset_datetime",
        "recorded_date", "source_file", "fhir_profiles",
    ],
    "diagnostic_reports": [
        "report_id", "patient_id", "encounter_id", "status", "code_system",
        "code", "display", "effective_datetime", "issued_datetime", "source_file", "fhir_profiles",
    ],
    "diagnostic_report_results": [
        "report_id", "observation_id", "raw_reference", "source_file",
    ],
    "medication_requests": [
        "medication_request_id", "patient_id", "encounter_id", "status", "intent",
        "medication_system", "medication_code", "medication_display", "medication_reference",
        "authored_on", "source_file", "fhir_profiles",
    ],
    "clinical_documents": [
        "document_id", "patient_id", "status", "document_type_code", "document_type",
        "document_date", "content_type", "text_content", "source_file", "fhir_profiles",
    ],
}


def extract_patient_name(resource: dict[str, Any]) -> dict[str, str]:
    """Read a synthetic FHIR HumanName without guessing missing names.

    Prefer the official name. A Patient can contain multiple HumanName objects.
    Given names may contain middle names; retain them in full_name.
    """
    names = [item for item in resource.get("name", []) or [] if isinstance(item, dict)]
    if not names:
        return {"first_name": "", "last_name": "", "full_name": ""}
    name = next((item for item in names if item.get("use") == "official"), names[0])
    given = name.get("given") or []
    if isinstance(given, str):
        given = [given]
    given = [part.strip() for part in given if isinstance(part, str) and part.strip()]
    family = name.get("family", "")
    last_name = family.strip() if isinstance(family, str) else ""
    preferred_text = name.get("text", "")
    preferred_text = preferred_text.strip() if isinstance(preferred_text, str) else ""
    full_name = preferred_text or " ".join([*given, last_name]).strip()
    return {
        "first_name": given[0] if given else "",
        "last_name": last_name,
        "full_name": full_name,
    }


def ref_id(reference: Any) -> str:
    """Normalize known ID-based FHIR references without guessing conditional IDs."""
    raw = reference.get("reference", "") if isinstance(reference, dict) else str(reference or "")
    if raw.startswith("urn:uuid:"):
        return raw[len("urn:uuid:"):]
    if "?" in raw or "|" in raw or "#" in raw:
        return ""  # Conditional or contained references need a proper resolver.
    if "/" in raw:
        return raw.rsplit("/", 1)[-1]
    return raw


def coding(concept: Any) -> tuple[str, str, str]:
    if not isinstance(concept, dict):
        return "", "", ""
    values = concept.get("coding") or []
    first = values[0] if values and isinstance(values[0], dict) else {}
    return (
        first.get("system", ""),
        str(first.get("code", "")),
        first.get("display") or concept.get("text", ""),
    )


def profiles(resource: dict[str, Any]) -> str:
    return ";".join(resource.get("meta", {}).get("profile", []) or [])


def first_category(resource: dict[str, Any]) -> str:
    cats = resource.get("category") or []
    return coding(cats[0])[1] if cats else ""


def value_fields(value_object: dict[str, Any]) -> dict[str, Any]:
    if "valueQuantity" in value_object:
        value = value_object["valueQuantity"] or {}
        return {
            "value_type": "quantity", "value_numeric": value.get("value", ""),
            "value_unit": value.get("unit", ""), "unit_code": value.get("code", ""),
            "unit_system": value.get("system", ""), "value_text": "",
            "value_code_system": "", "value_code": "",
        }
    if "valueCodeableConcept" in value_object:
        concept = value_object["valueCodeableConcept"] or {}
        system, code, label = coding(concept)
        return {
            "value_type": "coded", "value_numeric": "", "value_unit": "",
            "unit_code": "", "unit_system": "", "value_text": label,
            "value_code_system": system, "value_code": code,
        }
    if "valueString" in value_object:
        return {
            "value_type": "string", "value_numeric": "", "value_unit": "",
            "unit_code": "", "unit_system": "", "value_text": value_object["valueString"],
            "value_code_system": "", "value_code": "",
        }
    return {
        "value_type": "unsupported_or_missing", "value_numeric": "", "value_unit": "",
        "unit_code": "", "unit_system": "", "value_text": "",
        "value_code_system": "", "value_code": "",
    }


def extract_text(document: dict[str, Any]) -> tuple[str, str]:
    """Decode only embedded text/plain attachments; do not interpret binary files."""
    for part in document.get("content", []):
        attachment = part.get("attachment") or {}
        content_type = attachment.get("contentType", "")
        data = attachment.get("data")
        if isinstance(data, str) and content_type.lower().startswith("text/plain"):
            try:
                return content_type, base64.b64decode(data, validate=True).decode("utf-8")
            except (ValueError, UnicodeDecodeError):
                return content_type, ""
    return "", ""


def iter_resources(source: Path) -> Iterator[tuple[dict[str, Any], str]]:
    files = sorted(source.rglob("*.json")) if source.is_dir() else [source]
    if not files:
        raise ValueError(f"No JSON files found under: {source}")
    for path in files:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if data.get("resourceType") == "Bundle":
            resources = [entry.get("resource") for entry in data.get("entry", [])]
        elif isinstance(data, dict) and data.get("resourceType"):
            resources = [data]
        else:
            raise ValueError(f"Not a FHIR resource or Bundle: {path}")
        for resource in resources:
            if isinstance(resource, dict) and resource.get("resourceType"):
                yield resource, str(path)


def write_resource(
    resource: dict[str, Any], source_file: str, writers: dict[str, csv.DictWriter], counts: Counter
) -> None:
    kind = resource["resourceType"]
    counts[f"fhir_{kind}"] += 1
    common = {"source_file": source_file, "fhir_profiles": profiles(resource)}
    rid = resource.get("id", "")
    patient_id = ref_id(resource.get("subject") or resource.get("patient"))
    encounter_id = ref_id(resource.get("encounter"))

    def emit(table: str, row: dict[str, Any]) -> None:
        # Fail fast if the schema is accidentally changed without being declared.
        writers[table].writerow(row)
        counts[f"out_{table}"] += 1

    if kind == "Patient":
        emit("patients", {
            "patient_id": rid, **extract_patient_name(resource),
            "gender": resource.get("gender", ""),
            "birth_date": resource.get("birthDate", ""), **common,
        })
    elif kind == "Encounter":
        system, type_code, type_display = coding((resource.get("type") or [{}])[0])
        period = resource.get("period") or {}
        emit("encounters", {
            "encounter_id": rid, "patient_id": patient_id,
            "status": resource.get("status", ""), "class_code": (resource.get("class") or {}).get("code", ""),
            "type_code": type_code, "type_display": type_display,
            "start_time": period.get("start", ""), "end_time": period.get("end", ""), **common,
        })
    elif kind == "Observation":
        system, code, display = coding(resource.get("code"))
        base = {
            "observation_id": rid, "patient_id": patient_id, "encounter_id": encounter_id,
            "status": resource.get("status", ""), "category": first_category(resource),
            "observation_code_system": system, "observation_code": code,
            "observation_display": display,
            "effective_datetime": resource.get("effectiveDateTime", ""),
            "issued_datetime": resource.get("issued", ""), **common,
        }
        components = resource.get("component") or []
        if components:
            for index, component in enumerate(components, start=1):
                c_system, c_code, c_display = coding(component.get("code"))
                emit("observations", {
                    **base, "component_index": index, "component_code_system": c_system,
                    "component_code": c_code, "component_display": c_display,
                    **value_fields(component),
                })
        else:
            emit("observations", {
                **base, "component_index": "", "component_code_system": "",
                "component_code": "", "component_display": "", **value_fields(resource),
            })
    elif kind == "Condition":
        system, code, display = coding(resource.get("code"))
        clinical = coding(resource.get("clinicalStatus"))[1]
        verification = coding(resource.get("verificationStatus"))[1]
        emit("conditions", {
            "condition_id": rid, "patient_id": patient_id, "encounter_id": encounter_id,
            "code_system": system, "code": code, "display": display,
            "clinical_status": clinical, "verification_status": verification,
            "onset_datetime": resource.get("onsetDateTime", ""),
            "recorded_date": resource.get("recordedDate", ""), **common,
        })
    elif kind == "DiagnosticReport":
        system, code, display = coding(resource.get("code"))
        emit("diagnostic_reports", {
            "report_id": rid, "patient_id": patient_id, "encounter_id": encounter_id,
            "status": resource.get("status", ""), "code_system": system,
            "code": code, "display": display,
            "effective_datetime": resource.get("effectiveDateTime", ""),
            "issued_datetime": resource.get("issued", ""), **common,
        })
        for result in resource.get("result", []):
            emit("diagnostic_report_results", {
                "report_id": rid, "observation_id": ref_id(result),
                "raw_reference": result.get("reference", ""), "source_file": source_file,
            })
    elif kind == "MedicationRequest":
        system, code, display = coding(resource.get("medicationCodeableConcept"))
        emit("medication_requests", {
            "medication_request_id": rid, "patient_id": patient_id,
            "encounter_id": encounter_id, "status": resource.get("status", ""),
            "intent": resource.get("intent", ""), "medication_system": system,
            "medication_code": code, "medication_display": display,
            "medication_reference": (resource.get("medicationReference") or {}).get("reference", ""),
            "authored_on": resource.get("authoredOn", ""), **common,
        })
    elif kind == "DocumentReference":
        system, type_code, document_type = coding(resource.get("type"))
        content_type, text_content = extract_text(resource)
        emit("clinical_documents", {
            "document_id": rid, "patient_id": patient_id,
            "status": resource.get("status", ""), "document_type_code": type_code,
            "document_type": document_type, "document_date": resource.get("date", ""),
            "content_type": content_type, "text_content": text_content, **common,
        })


def transform(source: Path, output: Path) -> Counter:
    if not source.exists():
        raise FileNotFoundError(f"Input path not found: {source}")
    if not (source.is_dir() or source.suffix.lower() == ".json"):
        raise ValueError("Input must be a JSON file or a directory of JSON files.")
    output.mkdir(parents=True, exist_ok=True)
    counts: Counter = Counter()
    handles = {}
    writers = {}
    try:
        for table, fields in SCHEMAS.items():
            handle = (output / f"{table}.csv").open("w", encoding="utf-8", newline="")
            handles[table] = handle
            writers[table] = csv.DictWriter(handle, fieldnames=fields)
            writers[table].writeheader()
        for resource, source_file in iter_resources(source):
            write_resource(resource, source_file, writers, counts)
    finally:
        for handle in handles.values():
            handle.close()
    with (output / "transformation_summary.json").open("w", encoding="utf-8") as handle:
        json.dump(dict(sorted(counts.items())), handle, indent=2, ensure_ascii=False)
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Transform selected FHIR R4 resources into CSV tables.")
    parser.add_argument("--input", required=True, type=Path, help="A FHIR JSON file or directory")
    parser.add_argument("--output", required=True, type=Path, help="Output directory for CSV tables")
    args = parser.parse_args()
    counts = transform(args.input, args.output)
    print(f"Transformation completed. Output: {args.output.resolve()}")
    print(f"FHIR resources processed: {sum(n for k, n in counts.items() if k.startswith('fhir_'))}")
    for table in SCHEMAS:
        print(f"  {table}: {counts[f'out_{table}']}")
    print("Note: only selected resource types are exported in this first iteration.")


if __name__ == "__main__":
    main()
