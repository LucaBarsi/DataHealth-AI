"""Defensive checks for displaying patient-scoped synthetic assistant responses.

These are UI integrity checks, not clinical validation. The retrieval layer
already enforces patient_id filters; this module additionally catches known
patient names appearing in a model response for a different selected patient.
"""
from __future__ import annotations

from typing import Any, Iterable


def mentions_other_patient(
    answer: str,
    selected_patient_id: str,
    patients: Iterable[dict[str, Any]],
) -> bool:
    """Detect another listed synthetic patient's complete name in an answer.

    Ignore short/ambiguous names. This is an additional, deliberately limited
    safeguard, not a guarantee against every hallucinated identity.
    """
    if not isinstance(answer, str) or not isinstance(selected_patient_id, str):
        return True
    normalized = " ".join(answer.casefold().split())
    for patient in patients:
        patient_id = str(patient.get("patient_id") or "")
        full_name = " ".join(str(patient.get("full_name") or "").casefold().split())
        if patient_id != selected_patient_id and len(full_name) >= 12 and full_name in normalized:
            return True
    return False


def visible_messages_for_patient(
    messages: Iterable[dict[str, Any]],
    selected_patient_id: str,
) -> list[dict[str, Any]]:
    """Do not display messages from an earlier patient or unscoped chat."""
    return [
        message
        for message in messages
        if message.get("patient_id") == selected_patient_id
    ]
