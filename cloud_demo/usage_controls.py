"""Best-effort safety controls for the fictional public Streamlit demo.

This module is intentionally dependency-free. It provides per-session limits,
a cooldown, and a thread-safe per-process shared sliding window. It is NOT a
multi-instance or provider-side hard quota. Paid-provider limits must be set
in the upstream account/dashboard before broad public use.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from threading import Lock
from time import monotonic
from typing import MutableMapping, Any


@dataclass(frozen=True)
class UsagePolicy:
    session_max_calls: int = 6
    session_cooldown_seconds: float = 15.0
    process_max_calls: int = 24
    process_window_seconds: float = 3600.0

    def __post_init__(self) -> None:
        if self.session_max_calls < 1 or self.process_max_calls < 1:
            raise ValueError('Limits must be positive')
        if self.session_cooldown_seconds < 0 or self.process_window_seconds <= 0:
            raise ValueError('Invalid time windows')


class SharedProcessBudget:
    """Atomic sliding-window budget for ONE Python process (not durable)."""

    def __init__(self, *, max_calls: int = 24, window_seconds: float = 3600.0):
        if max_calls <= 0 or window_seconds <= 0:
            raise ValueError('Invalid budget configuration')
        self.max_calls = max_calls
        self.window_seconds = window_seconds
        self._calls: deque[float] = deque()
        self._lock = Lock()

    def try_reserve(self, now: float | None = None) -> bool:
        current = monotonic() if now is None else now
        with self._lock:
            while self._calls and current - self._calls[0] >= self.window_seconds:
                self._calls.popleft()
            if len(self._calls) >= self.max_calls:
                return False
            self._calls.append(current)
            return True

    def used(self, now: float | None = None) -> int:
        current = monotonic() if now is None else now
        with self._lock:
            while self._calls and current - self._calls[0] >= self.window_seconds:
                self._calls.popleft()
            return len(self._calls)


def reserve_hosted_call(
    session_state: MutableMapping[str, Any],
    process_budget: SharedProcessBudget,
    *,
    policy: UsagePolicy = UsagePolicy(),
    now: float | None = None,
) -> tuple[bool, str]:
    """Reserve BEFORE an API call. Count attempts, including upstream failures.

    Returns (allowed, stable public-safe reason). Tokens/answers are never logged.
    Session state must be provided by Streamlit; no browser IDs are collected.
    """
    current = monotonic() if now is None else now
    attempts = int(session_state.get('hosted_calls', 0))
    if attempts >= policy.session_max_calls:
        return False, 'SESSION_CALL_LIMIT'
    last = session_state.get('last_hosted_attempt_at')
    if last is not None and current - float(last) < policy.session_cooldown_seconds:
        return False, 'SESSION_COOLDOWN'
    if not process_budget.try_reserve(current):
        return False, 'PROCESS_BUDGET_REACHED'
    session_state['hosted_calls'] = attempts + 1
    session_state['last_hosted_attempt_at'] = current
    return True, 'REQUEST_RESERVED'
