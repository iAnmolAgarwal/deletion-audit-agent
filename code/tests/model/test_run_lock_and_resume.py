"""One paid run at a time (the run lock), a capped run that resumes from the cache at no cost,
and the request carried on every reply (developer decision T83)."""
from __future__ import annotations

import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

from deletion_audit.model import (
    BudgetGuard,
    FakeTransport,
    MemoryCallLog,
    ModelCallFailed,
    ModelClient,
    ModelRequest,
    PaidRunLocked,
    ReplyCache,
    RetryPolicy,
    usage_cost,
    worst_case_cost,
)
from deletion_audit.model.reply import flatten_usage

from ._support import Rig, body, reply

CODE_DIR = Path(__file__).resolve().parents[2]
OK = {"intent": "DELETION_REQUEST", "note": "n"}


def client_on(rig: Rig, *, replay_only: bool) -> ModelClient:
    """A second client sharing ``rig``'s cache and ledger, with its own transport and budget."""
    return ModelClient(FakeTransport([reply()]), ReplyCache(rig.root / "replies"),
                       BudgetGuard(5.0, 100, rig.ledger), RetryPolicy(sleep=lambda s: None),
                       MemoryCallLog(), replay_only=replay_only, run_id="run-second")


class RunLock(unittest.TestCase):
    """A second paid run on the same ledger refuses to start; replay-only runs take no lock."""

    def test_second_paid_run_refuses_to_start(self) -> None:
        rig = Rig([reply()])
        self.assertTrue(rig.budget.holds_run_lock)
        with self.assertRaises(PaidRunLocked):
            client_on(rig, replay_only=False)
        replay = client_on(rig, replay_only=True)
        self.assertFalse(replay.budget.holds_run_lock)
        rig.client.close()
        self.assertFalse(rig.budget.holds_run_lock)
        second = client_on(rig, replay_only=False)
        self.assertTrue(second.budget.holds_run_lock)
        second.close()

    def test_lock_is_seen_by_another_process(self) -> None:
        rig = Rig([reply()])
        script = textwrap.dedent(f"""
            import sys
            sys.path.insert(0, {str(CODE_DIR)!r})
            from pathlib import Path
            from deletion_audit.model import BudgetGuard, PaidRunLocked
            try:
                BudgetGuard(1.0, 1, Path({str(rig.ledger)!r})).acquire_run_lock()
            except PaidRunLocked:
                sys.exit(3)
            sys.exit(0)
        """)
        held = subprocess.run([sys.executable, "-B", "-c", script], check=False)
        self.assertEqual(held.returncode, 3)
        rig.client.close()
        free = subprocess.run([sys.executable, "-B", "-c", script], check=False)
        self.assertEqual(free.returncode, 0)

    def test_no_send_without_the_lock(self) -> None:
        rig = Rig([reply()])
        rig.client.close()
        with self.assertRaises(PaidRunLocked):
            rig.client.call(ModelRequest(body()))
        self.assertEqual(rig.transport.calls, 0)


class CappedRunResumes(unittest.TestCase):
    """A run that hits a cap stops cleanly; a re-run serves every reply already bought from the
    cache at no cost and pays only for the rest."""

    def run_capped_then_resume(self, cap: str) -> None:
        requests = [ModelRequest(body(f"Request number {n}.")) for n in range(5)]
        replies = [reply(OK, input_tokens=1000 + n, output_tokens=500) for n in range(5)]
        settled = [usage_cost("claude-sonnet-5-5", flatten_usage(r["usage"])) for r in replies]
        if cap == "call":
            first = Rig(list(replies), call_cap=3)
        else:
            dollar_cap = sum(settled[:3]) + worst_case_cost(requests[3]) - 1e-9
            first = Rig(list(replies), dollar_cap=dollar_cap)
        for req in requests[:3]:
            self.assertFalse(first.client.call(req).from_cache)
        with self.assertRaises(ModelCallFailed) as stop:
            first.client.call(requests[3])
        self.assertEqual(stop.exception.reason, "CALL_CAP" if cap == "call" else "BUDGET")
        self.assertEqual(first.transport.calls, 3)
        self.assertIsNone(first.cache.get(requests[3].key()))
        self.assertEqual(len(first.ledger.read_text(encoding="utf-8").splitlines()), 3)
        first.client.close()

        second = Rig(list(replies[3:]), root=first.root, run_id="run-resume")
        out = [second.client.call(req) for req in requests]
        self.assertEqual([o.from_cache for o in out], [True, True, True, False, False])
        self.assertEqual([o.bought_by_run for o in out[:3]], ["run-test"] * 3)
        self.assertEqual(second.transport.calls, 2)
        self.assertEqual(second.budget.calls, 2)
        self.assertAlmostEqual(second.budget.run_spent_usd, settled[3] + settled[4])
        self.assertEqual(len(second.ledger.read_text(encoding="utf-8").splitlines()), 5)

    def test_call_cap(self) -> None:
        self.run_capped_then_resume("call")

    def test_dollar_cap(self) -> None:
        self.run_capped_then_resume("dollar")


class ReplyCarriesRequest(unittest.TestCase):
    """Every reply names the request it answers; after a repair, the repaired request."""

    def test_fresh_and_cached_reply_carry_their_request(self) -> None:
        rig = Rig([reply()])
        req = ModelRequest(body())
        fresh = rig.client.call(req)
        self.assertEqual(fresh.request.key(), req.key())
        self.assertEqual(fresh.request.key(), fresh.key)
        rig.client.close()
        cached = Rig([], root=rig.root, replay_only=True).client.call(req)
        self.assertTrue(cached.from_cache)
        self.assertEqual(cached.request.key(), req.key())

    def test_repaired_reply_carries_the_repaired_request(self) -> None:
        rig = Rig([reply(OK, stop_reason="refusal"), reply(OK)])
        out = rig.client.call(ModelRequest(body()))
        first, second = rig.transport.sent
        self.assertNotEqual(out.request.key(), ModelRequest(body()).key())
        self.assertEqual(out.request.key(), ModelRequest(second).key())
        self.assertEqual(out.request.key(), out.key)


if __name__ == "__main__":
    unittest.main()
