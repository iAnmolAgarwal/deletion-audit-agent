"""ModelClient: cache, then budget, then send with the retry ladder, then cache.put, then log.

``call(req)`` returns a reply that passed its structure check (:mod:`.structure`) or raises
:class:`~.errors.ModelCallFailed`. The order for each request is:

1. **Cache.** A hit returns the stored reply and makes no send and no reservation.
2. **Replay-only.** With ``replay_only=True`` a miss gives up as ``REPLAY_MISS``; nothing is sent.
3. **Budget.** Each send reserves its worst case first; a refusal raises ``BUDGET`` or ``CALL_CAP``.
4. **Send.** The request rules are re-applied to the body just before each send
   (:meth:`ModelRequest.recheck`). A :class:`~.transport.TransportFailure` goes to
   ``RetryPolicy.decide``, which retries (after its wait) or gives up. A failure with an HTTP
   error status (400 and above) is settled at $0; one whose outcome is unknown (a timeout, a
   dropped connection, an unreadable 200 body, any other exception from the transport) is
   settled at the reserved worst case. A reply missing ``content``, ``stop_reason``, ``model``
   or ``usage`` is settled at the reserved worst case and handled as a non-retryable
   ``MalformedReply`` transport failure.
5. **cache.put.** Every well-formed reply is stored, including ones that fail step 6, so a
   replay meets the same failure and the same repair.
6. **Reply check.** A failed check goes to ``RetryPolicy.decide``; a repair builds a new
   request (:func:`~.repair.build_repair`) that runs through steps 1-6 again.

Every cache read, send attempt, reply failure, budget refusal, run-lock refusal, corrupt cache
entry and failed re-check is logged with its ``error_class`` and ``status`` (None when there is
no status), including exceptions that are re-raised as they are. Every give-up comes from a
:class:`~.policy.GiveUp` decision.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, NoReturn, TypeIs

from .budget import BudgetGuard, Reservation
from .cache import ReplyCache
from .calllog import CallLog, CallLogEntry, Event, Outcome
from .errors import CacheCorruptError, ModelCallFailed, PaidRunLocked, RequestRejected
from .policy import Failure, GiveUp, Repair, Retry, RetryPolicy
from .repair import build_repair
from .reply import ModelReply, flatten_usage
from .request import ModelRequest
from .structure import check_structure
from .transport import Transport, TransportFailure


def _well_formed(reply: Any) -> TypeIs[Mapping[str, Any]]:
    """Whether a reply has the fields the cache and the reply check need."""
    return (isinstance(reply, Mapping) and isinstance(reply.get("content"), list)
            and isinstance(reply.get("stop_reason"), str) and isinstance(reply.get("model"), str)
            and isinstance(reply.get("usage"), Mapping))


class ModelClient:
    """Makes model calls through the cache, budget, transport and retry policy."""

    def __init__(self, transport: Transport, cache: ReplyCache, budget: BudgetGuard, policy: RetryPolicy,
                 log: CallLog, *, replay_only: bool, run_id: str) -> None:
        """Wire the parts; ``run_id`` is recorded on every reply this client buys."""
        self.transport = transport
        self.cache = cache
        self.budget = budget
        self.policy = policy
        self.log = log
        self.replay_only = replay_only
        self.run_id = run_id
        if not replay_only:
            try:
                budget.acquire_run_lock()
            except PaidRunLocked:
                self._entry("", "error", 1, "failed", False, error_class="PaidRunLocked",
                            detail="another paid run holds the ledger lock")
                raise

    def close(self) -> None:
        """Release the paid-run lock (a replay-only client holds none)."""
        self.budget.release_run_lock()

    def __enter__(self) -> ModelClient:
        """Use the client as a context manager that releases the run lock on exit."""
        return self

    def __exit__(self, *exc: object) -> None:
        """Release the run lock."""
        self.close()

    def call(self, req: ModelRequest) -> ModelReply:
        """Return a structurally valid reply for ``req``, repairing as the policy allows."""
        current = req
        reply_failures = 0
        while True:
            reply = self._fetch(current)
            failure = check_structure(current, reply.raw)
            if failure is None:
                return reply
            reply_failures += 1
            decision = self.policy.decide(failure, reply_failures)
            self._log(current.key(), "reply_check", reply_failures, decision, reply.from_cache,
                      failure=failure, stop_reason=reply.stop_reason, request_id=reply.request_id)
            if isinstance(decision, Repair):
                current = build_repair(current, decision.text)
                continue
            self._give_up(decision, failure, current.key())

    def _fetch(self, req: ModelRequest) -> ModelReply:
        """Return the reply for ``req`` from the cache, or buy it through the ladder."""
        key = req.key()
        cached = self._cache_get(key)
        if cached is not None:
            self._entry(key, "cache_hit", 1, "ok", True, stop_reason=cached.stop_reason,
                        request_id=cached.request_id)
            return cached
        if self.replay_only:
            failure = Failure(kind="REPLAY_MISS", error_class="CacheMiss")
            decision = self.policy.decide(failure, 1)
            self._log(key, "replay_miss", 1, decision, False, failure=failure)
            self._give_up(decision, failure, key)
        return self._send_ladder(req)

    def _cache_get(self, key: str) -> ModelReply | None:
        """Read the cache; log and re-raise a corrupt entry."""
        try:
            return self.cache.get(key)
        except CacheCorruptError:
            self._entry(key, "error", 1, "failed", False, error_class="CacheCorruptError",
                        detail="cache entry unreadable or not matching its key")
            raise

    def _recheck(self, req: ModelRequest, attempt: int) -> dict[str, Any]:
        """Re-apply the request rules just before a send; log and re-raise a rejection."""
        try:
            return req.recheck()
        except RequestRejected:
            self._entry(req.key(), "error", attempt, "failed", False, error_class="RequestRejected",
                        detail="request failed its re-check before send")
            raise

    def _reserve(self, req: ModelRequest, attempt: int) -> Reservation:
        """Reserve the budget for one send; log and re-raise a refusal."""
        if not self.budget.holds_run_lock:
            self._entry(req.key(), "error", attempt, "failed", False, error_class="PaidRunLocked",
                        detail="a paid send needs the run lock")
            raise PaidRunLocked("a paid send needs the run lock; build the client with replay_only=False")
        try:
            return self.budget.reserve(req)
        except ModelCallFailed as exc:
            self._entry(req.key(), "budget", attempt, "failed", False, error_class=exc.error_class,
                        detail=exc.reason)
            raise

    def _send_ladder(self, req: ModelRequest) -> ModelReply:
        """Send ``req`` until it gets a well-formed reply or the policy gives up."""
        key = req.key()
        attempt = 0
        while True:
            attempt += 1
            plain = self._recheck(req, attempt)
            res = self._reserve(req, attempt)
            try:
                envelope = self.transport.send(plain)
            except TransportFailure as exc:
                self._settle_failure(res, exc.failure)
                decision = self.policy.decide(exc.failure, attempt)
                self._log(key, "send", attempt, decision, False, failure=exc.failure)
                if isinstance(decision, Retry):
                    self.policy.sleep(decision.delay_s)
                    continue
                self._give_up(decision, exc.failure, key)
            except BaseException as exc:
                self._settle_worst(res)
                self._entry(key, "send", attempt, "failed", False, error_class=type(exc).__name__,
                            detail="exception outside the retry policy; re-raised")
                raise
            raw = envelope.get("reply")
            request_id = envelope.get("request_id")
            request_id = request_id if isinstance(request_id, str) else None
            if not _well_formed(raw):
                self._settle_worst(res)
                failure = Failure(kind="TRANSPORT", error_class="MalformedReply", status=200)
                decision = self.policy.decide(failure, attempt)
                self._log(key, "send", attempt, decision, False, failure=failure, request_id=request_id)
                if isinstance(decision, Retry):
                    self.policy.sleep(decision.delay_s)
                    continue
                self._give_up(decision, failure, key)
            usage = flatten_usage(raw["usage"])
            cost = self.budget.settle(res, usage)
            self.cache.put(req, raw, self.run_id, request_id=request_id)
            self._entry(key, "send", attempt, "ok", False, stop_reason=str(raw["stop_reason"]), usage=usage,
                        cost_usd=cost, request_id=request_id)
            stored = self._cache_get(key)
            if stored is None:
                self._entry(key, "error", attempt, "failed", False, error_class="CacheCorruptError",
                            detail="reply written but not readable")
                raise CacheCorruptError(f"reply for {key} was written but cannot be read back")
            if stored.bought_by_run == self.run_id and stored.raw == raw:
                return ModelReply(stored.key, stored.raw, stored.model, stored.usage, stored.stop_reason,
                                  stored.request_id, False, stored.bought_by_run, stored.request)
            return stored

    def _settle_worst(self, res: Reservation) -> float:
        """Settle ``res`` at its reserved worst case (outcome unknown, so assume it was billed)."""
        return self.budget.settle(res, {"input_tokens": res.input_tokens_bound, "output_tokens": res.max_tokens})

    def _settle_failure(self, res: Reservation, failure: Failure) -> float:
        """Settle a transport failure: $0 for an HTTP error status, else the reserved worst case."""
        if failure.status is not None and failure.status >= 400:
            return self.budget.settle(res, {})
        return self._settle_worst(res)

    def _give_up(self, decision: Retry | Repair | GiveUp, failure: Failure, key: str) -> NoReturn:
        """Raise ``ModelCallFailed`` for a GiveUp decision (the only give-up raise in the client)."""
        if not isinstance(decision, GiveUp):
            raise RuntimeError(f"policy returned {type(decision).__name__} where only GiveUp fits")
        raise ModelCallFailed(decision.reason, failure.error_class, failure.status, key)

    def _log(self, key: str, event: Event, attempt: int, decision: Retry | Repair | GiveUp,
             from_cache: bool, *, failure: Failure, stop_reason: str | None = None,
             request_id: str | None = None) -> None:
        """Log a failure and the decision taken on it."""
        outcome: Outcome = ("retry" if isinstance(decision, Retry)
                            else "repair" if isinstance(decision, Repair) else "give_up")
        detail = decision.reason if isinstance(decision, GiveUp) else failure.detail
        self._entry(key, event, attempt, outcome, from_cache, error_class=failure.error_class,
                    status=failure.status, stop_reason=stop_reason, request_id=request_id, detail=detail)

    def _entry(self, key: str, event: Event, attempt: int, outcome: Outcome, from_cache: bool,
               **fields: Any) -> None:
        """Record one call-log entry for this run."""
        self.log.record(CallLogEntry(run_id=self.run_id, key=key, event=event, attempt=attempt,
                                     outcome=outcome, from_cache=from_cache, **fields))
