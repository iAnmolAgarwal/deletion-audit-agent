"""RetryPolicy: the one place that decides to retry, repair or give up.

Every failure the client meets is described as a :class:`Failure` and passed to
:meth:`RetryPolicy.decide`, which returns :class:`Retry`, :class:`Repair` or :class:`GiveUp`.
The client acts on the decision and never decides on its own.

* **Transport failures** (``kind="TRANSPORT"``): 408, 409, 429, 529 and every status of 500 or
  above (``InternalServerError``, which SDK 1.13.0 raises for 503 and 504 too), plus
  ``APIConnectionError`` and ``APITimeoutError`` with no status, are retried. An
  ``x-should-retry`` header from the server overrides that, as in the SDK. Any other status
  gives up as ``NON_RETRYABLE``. At most ``max_attempts`` sends per request; the wait is the
  server's ``retry-after-ms`` / ``retry-after`` when it is between 0 and ``max_retry_after_s``
  seconds, else 1, 2, 4, 8 seconds by attempt.
* **Reply failures** (``kind="STRUCTURE"``): ``max_tokens``, ``refusal``, an ``end_turn`` with
  no text, a reply that breaks the output schema, or another unexpected stop reason. Each is
  repaired at most ``max_repairs`` times; ``model_context_window_exceeded`` is never repaired,
  because a repair only makes the request longer.
* **Replay misses** (``kind="REPLAY_MISS"``) always give up as ``REPLAY_MISS``.
"""
from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Literal

from .errors import FailReason

FailureKind = Literal["TRANSPORT", "STRUCTURE", "REPLAY_MISS"]

RETRYABLE_STATUSES: frozenset[int] = frozenset({408, 409, 429, 529})
RETRYABLE_NO_STATUS: frozenset[str] = frozenset({"APIConnectionError", "APITimeoutError"})
NEVER_REPAIRED: frozenset[str] = frozenset({"model_context_window_exceeded"})


@dataclass(frozen=True)
class Failure:
    """One failed attempt.

    Attributes:
        kind: which stage failed.
        error_class: SDK exception class name, or the reply failure kind
            (``max_tokens``, ``refusal``, ``NoText``, ``SchemaMismatch``, a stop reason).
        status: HTTP status, or None (connection errors, timeouts, reply failures on HTTP 200
            are given as 200 by the client).
        retry_after_s: the server's requested wait in seconds, when it sent one.
        should_retry: the server's ``x-should-retry`` header value, when present.
        detail: a short description for the call log (no reply text).
        api_error_type: the API's error ``type`` from an HTTP error body, else None.
        api_error_message: the API's error ``message`` from an HTTP error body (at most 500
            characters, cut with a marker), else None. Untrusted API text, kept as data.
        request_id: the request ID of the failed HTTP response, when it had one.
    """

    kind: FailureKind
    error_class: str
    status: int | None = None
    retry_after_s: float | None = None
    should_retry: str | None = None
    detail: str = ""
    api_error_type: str | None = None
    api_error_message: str | None = None
    request_id: str | None = None


@dataclass(frozen=True)
class Retry:
    """Send the same request again after ``delay_s`` seconds."""

    delay_s: float


@dataclass(frozen=True)
class Repair:
    """Send a repaired request: the same body plus the instruction ``text`` (a new key)."""

    text: str


@dataclass(frozen=True)
class GiveUp:
    """Stop; the client raises ``ModelCallFailed(reason)``."""

    reason: FailReason


Decision = Retry | Repair | GiveUp

REPAIR_TEXT: dict[str, str] = {
    "max_tokens": "it ran out of tokens before the answer was complete. Keep the reasoning short",
    "refusal": "it was a refusal. The request asks only for a structured reading of the data above",
    "NoText": "it contained no answer text",
    "SchemaMismatch": "it did not match the required JSON schema",
}


def parse_retry_after(headers: Mapping[str, str], now: float) -> float | None:
    """Seconds to wait from ``retry-after-ms``, else ``retry-after`` (seconds or HTTP date)."""
    lower = {k.lower(): v for k, v in headers.items()}
    ms = lower.get("retry-after-ms")
    if ms is not None:
        try:
            return float(ms) / 1000.0
        except ValueError:
            pass
    value = lower.get("retry-after")
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(value).timestamp() - now
    except (TypeError, ValueError):
        return None


class RetryPolicy:
    """Decides retry, repair or give-up for every failure (see the module docstring)."""

    def __init__(self, *, max_attempts: int = 5, backoff_s: tuple[float, ...] = (1.0, 2.0, 4.0, 8.0),
                 max_repairs: int = 2, max_retry_after_s: float = 60.0,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        """Set the limits; ``sleep`` is what the client calls to wait before a retry."""
        if max_attempts < 1 or max_repairs < 0 or len(backoff_s) < max_attempts - 1:
            raise ValueError("need max_attempts >= 1, max_repairs >= 0, a backoff per retry")
        self.max_attempts = max_attempts
        self.backoff_s = backoff_s
        self.max_repairs = max_repairs
        self.max_retry_after_s = max_retry_after_s
        self.sleep = sleep

    def decide(self, failure: Failure, attempt: int) -> Decision:
        """Decide what follows ``failure``.

        ``attempt`` is 1-based: for a transport failure, the number of sends of this request so
        far; for a reply failure, the number of reply failures so far in this call.
        """
        if failure.kind == "REPLAY_MISS":
            return GiveUp("REPLAY_MISS")
        if failure.kind == "STRUCTURE":
            return self._decide_structure(failure, attempt)
        return self._decide_transport(failure, attempt)

    def _decide_structure(self, failure: Failure, attempt: int) -> Decision:
        """Repair a reply failure up to ``max_repairs`` times."""
        if failure.error_class in NEVER_REPAIRED or attempt > self.max_repairs:
            return GiveUp("STRUCTURE_GAVE_UP")
        reason = REPAIR_TEXT.get(failure.error_class, f"it stopped with {failure.error_class}")
        return Repair(f"Repair {attempt}: the previous reply to this request failed because {reason}. "
                      "Reply again with only the JSON object that matches the required schema.")

    def _retryable(self, failure: Failure) -> bool:
        """Whether a transport failure may be retried at all."""
        if failure.should_retry == "false":
            return False
        if failure.should_retry == "true":
            return True
        if failure.status is None:
            return failure.error_class in RETRYABLE_NO_STATUS
        return failure.status in RETRYABLE_STATUSES or failure.status >= 500

    def _decide_transport(self, failure: Failure, attempt: int) -> Decision:
        """Retry a retryable transport failure until ``max_attempts`` sends."""
        if not self._retryable(failure):
            return GiveUp("NON_RETRYABLE")
        if attempt >= self.max_attempts:
            return GiveUp("TRANSPORT_GAVE_UP")
        wait = failure.retry_after_s
        if wait is not None and 0 <= wait <= self.max_retry_after_s:
            return Retry(wait)
        return Retry(self.backoff_s[attempt - 1])
