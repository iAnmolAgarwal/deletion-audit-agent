"""The call log: one entry per cache read, send attempt and reply check.

Each entry names the run, the request key, what happened, and for a failure its
``error_class`` and HTTP ``status``. Entries carry IDs, counts and costs, never reply text.
:class:`JsonlCallLog` appends entries to a JSON-lines file (``runs/<run_id>/calls.jsonl``);
:class:`MemoryCallLog` keeps them in a list.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal, Protocol

from .request import canonical_json

Event = Literal["cache_hit", "replay_miss", "send", "reply_check", "budget", "error"]
Outcome = Literal["ok", "retry", "repair", "give_up", "failed"]


@dataclass(frozen=True)
class CallLogEntry:
    """One logged event of a model call.

    Attributes:
        run_id: the run that made the call.
        key: the request key.
        event: ``cache_hit``, ``replay_miss``, ``send`` (one transport attempt),
            ``reply_check`` (a reply that failed its structure check), ``budget``, or ``error``
            (a run-lock refusal, a corrupt cache entry, or a request that failed its re-check).
        attempt: 1-based send attempt for ``send``; reply-failure count for ``reply_check``.
        outcome: ``ok``, ``retry``, ``repair``, ``give_up`` or ``failed`` (budget refusals,
            ``error`` events, and transport exceptions outside the retry policy).
        from_cache: whether the reply came from the cache.
        error_class: the failure's class or kind; None on success.
        status: the failure's HTTP status; None on success or with no status.
        stop_reason: the reply's stop reason, when there was a reply.
        usage: the reply's flattened usage, for a send that got a reply.
        cost_usd: the settled cost of a send (0.0 for a failed send or a cache read).
        request_id: the API request ID, when known.
        detail: a short note (decision, give-up reason); never reply text.
    """

    run_id: str
    key: str
    event: Event
    attempt: int
    outcome: Outcome
    from_cache: bool
    error_class: str | None = None
    status: int | None = None
    stop_reason: str | None = None
    usage: Mapping[str, int] = field(default_factory=dict)
    cost_usd: float = 0.0
    request_id: str | None = None
    detail: str = ""


class CallLog(Protocol):
    """Somewhere call-log entries go."""

    def record(self, entry: CallLogEntry) -> None:
        """Store one entry."""
        ...


class MemoryCallLog:
    """Keeps entries in ``entries``, in order."""

    def __init__(self) -> None:
        """Start with no entries."""
        self.entries: list[CallLogEntry] = []

    def record(self, entry: CallLogEntry) -> None:
        """Append ``entry``."""
        self.entries.append(entry)


class JsonlCallLog:
    """Appends each entry as one canonical JSON line to ``path``."""

    def __init__(self, path: Path) -> None:
        """Log to ``path``; its directory is created on first write."""
        self.path = Path(path)

    def record(self, entry: CallLogEntry) -> None:
        """Append ``entry`` and flush."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(entry)
        data["usage"] = dict(entry.usage)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(canonical_json(data) + "\n")
            handle.flush()
