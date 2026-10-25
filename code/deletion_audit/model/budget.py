"""BudgetGuard: per-run dollar and call caps, plus a project-wide ledger stop.

Every send reserves its worst-case cost before it goes out:
``input_upper_bound x worst input rate + max_tokens x output rate`` (see
:func:`input_token_upper_bound` and :func:`worst_case_cost`). The reservation is refused with
``ModelCallFailed("CALL_CAP")`` when the run has made ``call_cap`` sends, and with
``ModelCallFailed("BUDGET")`` when the run's settled spend plus open reservations plus this
worst case would pass ``dollar_cap``, or when every run's settled spend in the ledger plus
this run's open reservations plus this worst case would pass ``project_cap``.

**One paid run at a time.** A paid run holds an exclusive lock on ``<ledger>.lock`` for its
whole life (:meth:`BudgetGuard.acquire_run_lock`, taken by a non-replay
:class:`~.client.ModelClient` when it is built). A second paid run on the same ledger refuses to
start with :class:`~.errors.PaidRunLocked`, so two runs can never overshoot the project cap
together. Replay-only runs make no send and take no lock.

``settle`` prices the reply's actual ``usage`` (a usage with a negative count, or a cost that is
not a finite number >= 0, is charged at the reserved worst case instead), closes the reservation and appends one line
to the ledger (``{"key", "reserved_usd", "cost_usd", "usage", "written_at"}``). A ledger line
that cannot be read, or whose ``cost_usd`` is not a finite number >= 0 (NaN, infinity, a string, a
negative value), stops every later reservation with ``ModelCallFailed("BUDGET", "LedgerUnreadable")``.
"""
from __future__ import annotations

import fcntl
import itertools
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any

from .errors import ModelCallFailed, PaidRunLocked
from .prices import (
    MAX_IMAGE_TOKENS,
    PRICES,
    STRUCTURED_OUTPUT_MARGIN_TOKENS,
    TOOL_SYSTEM_PROMPT_TOKENS,
    ModelPrice,
)
from .request import ModelRequest, canonical_json

PER_MILLION = 1_000_000


@dataclass(frozen=True)
class Reservation:
    """An open reservation for one send."""

    reservation_id: int
    key: str
    model: str
    input_tokens_bound: int
    max_tokens: int
    worst_usd: float


def _strip_images(node: Any) -> tuple[Any, int]:
    """Copy ``node`` with base64 image data removed; also count the image blocks."""
    if isinstance(node, list):
        parts = [_strip_images(n) for n in node]
        return [p[0] for p in parts], sum(p[1] for p in parts)
    if isinstance(node, Mapping):
        if node.get("type") == "image":
            return {"type": "image"}, 1
        parts_by_key = {k: _strip_images(v) for k, v in node.items()}
        return {k: v[0] for k, v in parts_by_key.items()}, sum(v[1] for v in parts_by_key.values())
    return node, 0


def input_token_upper_bound(req: ModelRequest) -> int:
    """An upper bound on the request's input tokens, computed offline.

    The UTF-8 byte length of the canonical body (with image data removed) bounds its text
    tokens, since every token covers at least one byte. Each image block adds
    :data:`MAX_IMAGE_TOKENS`; tools add :data:`TOOL_SYSTEM_PROMPT_TOKENS`; the structured-output
    prompt adds :data:`STRUCTURED_OUTPUT_MARGIN_TOKENS`.
    """
    stripped, images = _strip_images(req.plain_body())
    tokens = len(canonical_json(stripped).encode("utf-8")) + images * MAX_IMAGE_TOKENS
    tokens += STRUCTURED_OUTPUT_MARGIN_TOKENS
    if req.body.get("tools"):
        tokens += TOOL_SYSTEM_PROMPT_TOKENS
    return tokens


def _worst_input_rate(req: ModelRequest, price: ModelPrice) -> float:
    """The highest per-token input rate the request can be billed at (cache writes when it caches)."""
    if '"cache_control"' not in canonical_json(req.plain_body()):
        return price.input
    return max(price.input, price.cache_write_5m, price.cache_write_1h)


def worst_case_cost(req: ModelRequest) -> float:
    """The most ``req`` can cost, in USD."""
    price = PRICES[str(req.body["model"])]
    return (input_token_upper_bound(req) * _worst_input_rate(req, price)
            + int(req.body["max_tokens"]) * price.output) / PER_MILLION


def usage_cost(model: str, usage: Mapping[str, int]) -> float:
    """The USD cost of a reply's flattened ``usage``.

    Cache writes use the 5-minute and 1-hour breakdown when the reply gives it; otherwise every
    cache-write token is priced at the 1-hour rate, the higher one.
    """
    price = PRICES[model]
    five = usage.get("cache_creation.ephemeral_5m_input_tokens")
    hour = usage.get("cache_creation.ephemeral_1h_input_tokens")
    if five is None and hour is None:
        writes = usage.get("cache_creation_input_tokens", 0) * price.cache_write_1h
    else:
        writes = (five or 0) * price.cache_write_5m + (hour or 0) * price.cache_write_1h
    total = (usage.get("input_tokens", 0) * price.input + writes
             + usage.get("cache_read_input_tokens", 0) * price.cache_read
             + usage.get("output_tokens", 0) * price.output)
    return total / PER_MILLION


def _finite_non_negative(value: Any) -> bool:
    """Whether ``value`` is an int or float (not bool) that is finite and at least 0."""
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value >= 0)


def _reject_constant(name: str) -> Any:
    """``json.loads`` hook: refuse NaN, Infinity and -Infinity in a ledger line."""
    raise ValueError(f"non-finite number {name} in the ledger")


def _ledger_cost(line: str) -> float:
    """The ``cost_usd`` of one ledger line; ValueError unless it is a finite number >= 0."""
    entry = json.loads(line, parse_constant=_reject_constant)
    if not isinstance(entry, dict):
        raise ValueError("ledger line is not an object")
    cost = entry["cost_usd"]
    if not _finite_non_negative(cost):
        raise ValueError("ledger cost is not a finite, non-negative number")
    return float(cost)


class BudgetGuard:
    """Per-run caps and the project ledger stop (see the module docstring).

    ``dollar_cap`` and ``project_cap`` must be finite numbers >= 0 and ``call_cap`` an int >= 0
    (bool is refused); anything else raises ValueError at construction.
    """

    def __init__(self, dollar_cap: float, call_cap: int, ledger: Path, project_cap: float = 110.0) -> None:
        """Set the caps; ``ledger`` is the append-only project ledger file (JSON lines)."""
        if not (_finite_non_negative(dollar_cap) and _finite_non_negative(project_cap)):
            raise ValueError("dollar_cap and project_cap must be finite numbers >= 0")
        if not isinstance(call_cap, int) or isinstance(call_cap, bool) or call_cap < 0:
            raise ValueError("call_cap must be an int >= 0")
        self.dollar_cap = dollar_cap
        self.call_cap = call_cap
        self.ledger = Path(ledger)
        self.project_cap = project_cap
        self.calls = 0
        self.run_spent_usd = 0.0
        self._open: dict[int, Reservation] = {}
        self._ids = itertools.count(1)
        self._run_lock: IO[str] | None = None

    @property
    def lock_path(self) -> Path:
        """The file whose exclusive lock marks a paid run in progress on this ledger.

        Named from the resolved ledger path, so a symlink or another path to the same ledger
        names the same lock file.
        """
        resolved = self.ledger.resolve()
        return resolved.with_name(resolved.name + ".lock")

    @property
    def holds_run_lock(self) -> bool:
        """Whether this guard holds the paid-run lock."""
        return self._run_lock is not None

    def acquire_run_lock(self) -> None:
        """Take the paid-run lock, or raise :class:`PaidRunLocked` when another run holds it."""
        if self._run_lock is not None:
            return
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.lock_path.open("a", encoding="utf-8")
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            handle.close()
            raise PaidRunLocked(f"another paid run holds {self.lock_path}") from exc
        self._run_lock = handle

    def release_run_lock(self) -> None:
        """Release the paid-run lock if this guard holds it."""
        if self._run_lock is not None:
            fcntl.flock(self._run_lock, fcntl.LOCK_UN)
            self._run_lock.close()
            self._run_lock = None

    @property
    def outstanding_usd(self) -> float:
        """The worst-case total of this run's open reservations."""
        return sum(r.worst_usd for r in self._open.values())

    def ledger_total(self) -> float:
        """Settled spend of every run in the ledger; raises ``ModelCallFailed("BUDGET")`` if unreadable."""
        if not self.ledger.exists():
            return 0.0
        total = 0.0
        try:
            lines = self.ledger.read_text(encoding="utf-8").splitlines()
            for line in lines:
                if line.strip():
                    total += _ledger_cost(line)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ModelCallFailed("BUDGET", "LedgerUnreadable") from exc
        return total

    def reserve(self, req: ModelRequest) -> Reservation:
        """Reserve ``req``'s worst case, or raise ``ModelCallFailed(BUDGET | CALL_CAP)``."""
        key = req.key()
        if self.calls >= self.call_cap:
            raise ModelCallFailed("CALL_CAP", "RunCallCap", key=key)
        worst = worst_case_cost(req)
        if not _finite_non_negative(worst):
            raise ModelCallFailed("BUDGET", "WorstCaseNotFinite", key=key)
        if self.run_spent_usd + self.outstanding_usd + worst > self.dollar_cap:
            raise ModelCallFailed("BUDGET", "RunDollarCap", key=key)
        if self.ledger_total() + self.outstanding_usd + worst > self.project_cap:
            raise ModelCallFailed("BUDGET", "ProjectLedgerCap", key=key)
        self.calls += 1
        res = Reservation(next(self._ids), key, str(req.body["model"]), input_token_upper_bound(req),
                          int(req.body["max_tokens"]), worst)
        self._open[res.reservation_id] = res
        return res

    def settle(self, res: Reservation, usage: Mapping[str, int]) -> float:
        """Close ``res`` at the cost of ``usage``; append it to the ledger; return the cost."""
        if self._open.pop(res.reservation_id, None) is None:
            raise ValueError("reservation already settled or unknown")
        cost = usage_cost(res.model, usage)
        if not _finite_non_negative(cost) or any(v < 0 for v in usage.values()):
            cost = res.worst_usd
        self.run_spent_usd += cost
        line = canonical_json({
            "key": res.key, "reserved_usd": res.worst_usd, "cost_usd": cost, "usage": dict(usage),
            "written_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        })
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        with self.ledger.open("a", encoding="utf-8") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            handle.write(line + "\n")
            handle.flush()
            fcntl.flock(handle, fcntl.LOCK_UN)
        return cost
