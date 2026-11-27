"""Guarded hosted Qwen inference for DataHealth AI deployment experiments.

Only synthetic, patient-scoped evidence may be submitted. This module does not
provide embeddings or replace the local Ollama implementation. No token is
stored in source code. Never treat citation-ID checks as clinical validation.
"""
from __future__ import annotations

import ipaddress
import json
from dataclasses import dataclass
from typing import Any, MutableMapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from cloud_demo.usage_controls import SharedProcessBudget, UsagePolicy, reserve_hosted_call
from . import reliable_assistant

DEFAULT_MIXLAYER_BASE = "https://mixlayer.ai/v1"
DEFAULT_MODEL = "qwen/qwen3.5-4b-free"
MAX_REPLY_BYTES = 250_000
DEFAULT_POLICY = UsagePolicy(
    session_max_calls=6,
    session_cooldown_seconds=15,
    process_max_calls=24,
    process_window_seconds=3600,
)


@dataclass(frozen=True)
class HostedQwenSettings:
    api_key: str
    api_base: str = DEFAULT_MIXLAYER_BASE
    model_id: str = DEFAULT_MODEL


class HostedQwenError(RuntimeError):
    """Stable non-sensitive error code for safe user-facing diagnostics."""

    def __init__(self, code: str):
        self.code = code
        super().__init__("Hosted inference unavailable: " + code)


def _completion_url(base_url: str) -> str:
    """Allow only a pinned Mixlayer HTTPS API endpoint."""
    parsed = urlsplit(base_url.strip())
    allowed = {"mixlayer.ai", "models.mixlayer.ai"}
    if (
        parsed.scheme != "https"
        or parsed.hostname not in allowed
        or parsed.port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path.rstrip("/") != "/v1"
    ):
        raise HostedQwenError("INVALID_API_BASE")
    try:
        if not ipaddress.ip_address(parsed.hostname).is_global:
            raise HostedQwenError("INVALID_API_BASE")
    except ValueError:
        pass
    return f"https://{parsed.hostname}/v1/chat/completions"


def call_hosted_qwen(settings: HostedQwenSettings, evidence: dict[str, Any]) -> str:
    """Call an HTTPS hosted model; never expose auth or raw upstream errors."""
    if not settings.api_key.strip():
        raise HostedQwenError("MISSING_API_KEY")
    if settings.model_id != DEFAULT_MODEL:
        raise HostedQwenError("UNSUPPORTED_MODEL")
    url = _completion_url(settings.api_base)
    prompt = reliable_assistant._llm_prompt(evidence)
    payload = {
        "model": settings.model_id,
        "reasoning_effort": "none",
        "temperature": 0,
        "stream": False,
        "max_tokens": 900,
        "messages": [
            {"role": "system", "content": reliable_assistant.RELIABILITY_PROMPT},
            {"role": "user", "content": prompt},
        ],
    }
    req = Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + settings.api_key,
        },
        method="POST",
    )
    try:
        with urlopen(req, timeout=35) as response:
            body = response.read(MAX_REPLY_BYTES + 1)
        if len(body) > MAX_REPLY_BYTES:
            raise HostedQwenError("RESPONSE_TOO_LARGE")
        document = json.loads(body.decode("utf-8"))
    except HTTPError as exc:
        status = exc.code
        codes = {401: "AUTH_FAILED", 403: "ACCESS_DENIED",
                 404: "MODEL_NOT_FOUND", 429: "RATE_LIMITED"}
        raise HostedQwenError(codes.get(status, "UPSTREAM_HTTP_ERROR")) from None
    except (URLError, TimeoutError, OSError):
        raise HostedQwenError("NETWORK_OR_TIMEOUT") from None
    except (ValueError, UnicodeError):
        raise HostedQwenError("INVALID_JSON_RESPONSE") from None
    try:
        answer = document["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise HostedQwenError("INVALID_RESPONSE_FORMAT") from None
    if not isinstance(answer, str) or not answer.strip():
        raise HostedQwenError("EMPTY_MODEL_RESPONSE")
    return answer.strip()


def _fallback(evidence: dict[str, Any], reason: str) -> dict[str, Any]:
    result = {
        "status": "EVIDENCE_ONLY_FALLBACK",
        "answer": reliable_assistant.evidence_only_fallback(evidence),
        "attempts": 0,
        "audit": None,
        "reason": reason,
        "warning": "Hosted model output unavailable or discarded; this is not a clinical assessment.",
    }
    return result


def generate_guarded_hosted_answer(
    evidence: dict[str, Any],
    *,
    settings: HostedQwenSettings,
    session_state: MutableMapping[str, Any],
    shared_budget: SharedProcessBudget,
    policy: UsagePolicy = DEFAULT_POLICY,
) -> dict[str, Any]:
    """Reserve a limited hosted call and fail closed on invalid source markers.

    This validates identifier provenance only, not factual support, chronology,
    or patient safety. Public deployment needs independent claim-level testing.
    """
    if not reliable_assistant.allowed_markers(evidence):
        return {
            "status": "NO_ELIGIBLE_EVIDENCE",
            "answer": "No eligible evidence was retrieved for this synthetic patient. The model was not called.",
            "attempts": 0,
            "audit": None,
            "reason": "NO_ELIGIBLE_EVIDENCE",
            "warning": "Absent query results do not establish absence of records.",
        }
    if not settings.api_key.strip():
        return _fallback(evidence, "HOSTED_QWEN_NOT_CONFIGURED")

    # Reject unsupported configuration before consuming per-session call budget.
    try:
        _completion_url(settings.api_base)
        if settings.model_id != DEFAULT_MODEL:
            raise HostedQwenError("UNSUPPORTED_MODEL")
    except HostedQwenError as exc:
        return _fallback(evidence, exc.code)

    allowed, usage_reason = reserve_hosted_call(
        session_state, shared_budget, policy=policy
    )
    if not allowed:
        return _fallback(evidence, usage_reason)

    try:
        generated = call_hosted_qwen(settings, evidence)
    except HostedQwenError as exc:
        return _fallback(evidence, exc.code)

    audit = reliable_assistant.audit_citations(generated, evidence)
    if not audit["valid"]:
        return _fallback(evidence, "CITATION_CHECK_FAILED")
    return {
        "status": "CITATION_IDS_VALID",
        "answer": generated,
        "attempts": 1,
        "audit": audit,
        "reason": "HOSTED_QWEN",
        "warning": "Source identifiers matched, but factual and clinical accuracy are not established.",
    }
