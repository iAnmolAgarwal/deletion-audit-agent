"""Exceptions raised by the model client.

* :class:`ModelCallFailed` is the one failure a caller of :meth:`ModelClient.call` handles.
  Its ``reason`` says which stage gave up; ``error_class`` and ``status`` say what failed.
* :class:`RequestRejected` is raised while a :class:`ModelRequest` is built, for a body the
  client will never send (a forced ``tool_choice``, a sampling parameter, no output format).
* :class:`CacheCorruptError` is raised when a reply-cache file cannot be read back exactly.
  It is never treated as a cache miss, so a corrupt entry is never silently re-bought.
"""
from __future__ import annotations

from typing import Literal, get_args

FailReason = Literal[
    "TRANSPORT_GAVE_UP", "NON_RETRYABLE", "BUDGET", "CALL_CAP", "REPLAY_MISS", "STRUCTURE_GAVE_UP",
]
FAIL_REASONS: frozenset[str] = frozenset(get_args(FailReason))


class ModelCallFailed(Exception):
    """A model call that produced no usable reply.

    Attributes:
        reason: the stage that gave up (one of :data:`FailReason`).
        error_class: the exception class or reply failure kind behind it, e.g. ``RateLimitError``,
            ``APITimeoutError``, ``max_tokens``, ``refusal``, ``SchemaMismatch``.
        status: the HTTP status of the last failed attempt, or None when there was none.
        key: the request key of the last request tried, or None.
    """

    def __init__(self, reason: FailReason, error_class: str, status: int | None = None,
                 key: str | None = None) -> None:
        """Store the failure fields; ``reason`` must be one of :data:`FailReason`."""
        if reason not in FAIL_REASONS:
            raise ValueError(f"unknown ModelCallFailed reason: {reason!r}")
        super().__init__(f"{reason}: {error_class} (status={status})")
        self.reason: FailReason = reason
        self.error_class = error_class
        self.status = status
        self.key = key


class RequestRejected(ValueError):
    """A request body that breaks a client rule; raised when the request is built."""


class PaidRunLocked(RuntimeError):
    """Another paid run holds the ledger's run lock, so this paid run refuses to start."""


class CacheCorruptError(RuntimeError):
    """A reply-cache entry that is unreadable, or whose content does not match its key."""
