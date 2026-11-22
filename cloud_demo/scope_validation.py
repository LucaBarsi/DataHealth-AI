"""Scope-aware review of negative claims in the fictional DataHealth AI demo.

A deterministic *safety filter*, not clinical fact checking or natural-language
entailment. Ambiguous negative statements trigger evidence-only fallback.
"""
from __future__ import annotations

import re
from typing import Any

CATEGORIES = ("observations", "conditions", "medications", "notes")
CATEGORY_PATTERNS = {
    "observations": re.compile(r"\b(?:observations?|measurements?|vital\s+signs?|laboratory\s+(?:tests?|results?)|lab\s+results?)\b", re.I),
    "conditions": re.compile(r"\b(?:conditions?|diagnos(?:es|is)|problem\s+list\s+entries?)\b", re.I),
    "medications": re.compile(r"\b(?:medications?|prescriptions?|medication\s+requests?|drug\s+(?:orders?|requests?))\b", re.I),
    "notes": re.compile(r"\b(?:clinical\s+notes?|notes?|documents?|document\s+excerpts?)\b", re.I),
}

_NEGATIVE_PREFIX = re.compile(
    r"\b(?:no|without|absence\s+of|lack\s+of|zero)\s+"
    r"(?:(?:other|additional|further|specific|active|new|documented|recorded|"
    r"structured|known|relevant|verified|eligible|clinical|patient)\s+){0,5}",
    re.I,
)
_NEGATIVE_PREDICATE = re.compile(
    r"\b(?:conditions?|diagnos(?:es|is)|observations?|measurements?|"
    r"medications?|prescriptions?|notes?|documents?)\b"
    r".{0,70}?\b(?:not|never)\s+(?:\w+\s+){0,3}"
    r"(?:found|recorded|documented|retrieved|available|present|listed|reported|mentioned)\b",
    re.I,
)
_NEGATIVE_EVIDENCE = re.compile(
    r"\bno\s+(?:further\s+|additional\s+)?evidence\s+"
    r"(?:exists|was\s+found|is\s+available|was\s+retrieved)\b.{0,100}", re.I,
)
_ALLOWED_SCOPE_DISCLOSURE = re.compile(
    r"\b(?:not\s+(?:queried|searched|checked|retrieved\s+from)|outside\s+the\s+retrieval\s+scope)\b",
    re.I,
)
_SAFE_RETRIEVED_ONLY = re.compile(
    r"\b(?:retrieved|returned|found\s+in\s+the\s+(?:selected|current)\s+(?:query|scope))\b",
    re.I,
)
_UNBOUNDED = re.compile(r"\b(?:other|additional|further|ever|never|anywhere|throughout|entire|all\s+history)\b", re.I)
_MARKERS = re.compile(r"\[(?:SQL|DOC):[^\]]*\]")


def retrieval_scope(evidence: dict[str, Any]) -> dict[str, Any]:
    """Precisely distinguish unchecked sections from sections queried with no rows.

    No absence-of-disease conclusion is supported by this inventory. A query
    result can be limited, so it is not an exhaustive record of a patient.
    """
    routing = evidence.get("routing", {})
    route_keys = {"observations": "measurements", "conditions": "conditions",
                  "medications": "medications", "notes": "notes"}
    return {
        "categories": {
            key: {
                "queried": bool(routing.get(route_keys[key], False)),
                "retrieved_rows": len(evidence.get(key, [])),
                "complete_history_verified": False,
            }
            for key in CATEGORIES
        },
        "interpretation": (
            "A category marked not queried was NOT searched; an empty result is not proof "
            "that the patient's record lacks that category. Retrieved rows are a limited "
            "view, not a verified complete history. Only describe the sources included."
        ),
    }


def negative_claim_check(answer: str, evidence: dict[str, Any]) -> dict[str, Any]:
    """Catch high-confidence negative-category claims that overstate retrieval.

    Heuristic, intentionally conservative. Does not verify all factual claims.
    A category may be mentioned in an ordinary positive statement without being
    flagged. Terms like 'no complaints' do not imply no notes or conditions.
    """
    scoped = retrieval_scope(evidence)["categories"]
    plain = _MARKERS.sub("", answer)
    violations: list[dict[str, str]] = []
    for sentence in re.split(r"(?<=[.!?])\s+|[\n;]+", plain):
        sentence = sentence.strip()
        if not sentence:
            continue
        if _ALLOWED_SCOPE_DISCLOSURE.search(sentence) and not re.search(r"\b(?:no|none|without)\b", sentence, re.I):
            continue
        # Locate the *object* of a negative claim, not any category mentioned
        # elsewhere in a sentence (e.g. 'Clinical note: no complaints').
        candidate_spans = []
        for prefix in _NEGATIVE_PREFIX.finditer(sentence):
            tail = sentence[prefix.end():]
            first = [(m.start(), name) for name, pat in CATEGORY_PATTERNS.items()
                     for m in pat.finditer(tail)]
            if not first:
                continue
            first_pos, first_cat = min(first)
            if first_pos > 5:  # no symptoms in the note != no note
                continue
            target_start = prefix.end() + first_pos
            # Include enumerations: 'no conditions, observations, medications or notes'
            tail_fragment = sentence[target_start:]
            stop = re.search(r"\b(?:was|were|is|are|has|have|found|recorded|documented|retrieved|listed)\b", tail_fragment, re.I)
            enumeration = tail_fragment[:stop.start()] if stop else tail_fragment[:90]
            cats = {c for c, pat in CATEGORY_PATTERNS.items() if pat.search(enumeration)}
            if cats:
                candidate_spans.append((cats, sentence[prefix.start():]))
        if _NEGATIVE_PREDICATE.search(sentence):
            cats = {c for c, pat in CATEGORY_PATTERNS.items() if pat.search(sentence)}
            if cats:
                candidate_spans.append((cats, sentence))
        evidence_absence = _NEGATIVE_EVIDENCE.search(sentence)
        if evidence_absence:
            cats = {c for c, pat in CATEGORY_PATTERNS.items()
                    if pat.search(sentence[evidence_absence.end():])}
            if cats:
                candidate_spans.append((cats, sentence))
        for categories, claim in candidate_spans:
            for category in sorted(categories):
                info = scoped[category]
                if not info["queried"]:
                    reason = "CATEGORY_NOT_QUERIED"
                elif info["retrieved_rows"]:
                    # Absolute or 'no other' negative claims exceed the evidence.
                    reason = "NEGATIVE_CLAIM_WITH_RETRIEVED_RECORDS"
                elif _UNBOUNDED.search(claim) or not _SAFE_RETRIEVED_ONLY.search(claim):
                    reason = "UNVERIFIED_ABSENCE"
                else:
                    continue
                record = {"category": category, "reason": reason}
                if record not in violations:
                    violations.append(record)
    return {"valid": not violations, "violations": violations, "guard_type": "heuristic_negative_claims_v1"}
