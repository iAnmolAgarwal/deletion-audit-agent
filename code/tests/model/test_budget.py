"""BudgetGuard: run dollar cap, run call cap, project ledger stop, and pricing."""
from __future__ import annotations

import json
import unittest

from deletion_audit.model import ModelCallFailed, ModelRequest, usage_cost, worst_case_cost

from ._support import Rig, body, reply, transport_failure


class TestCaps(unittest.TestCase):
    """Each cap stops a send before it goes out."""

    def test_dollar_cap(self) -> None:
        """max_tokens 10,000 reserves at least $0.10 of output, so a $0.05 run cap refuses it."""
        rig = Rig([reply()], dollar_cap=0.05)
        with self.assertRaises(ModelCallFailed) as ctx:
            rig.client.call(ModelRequest(body(max_tokens=10_000)))
        self.assertEqual((ctx.exception.reason, ctx.exception.error_class), ("BUDGET", "RunDollarCap"))
        self.assertEqual(rig.transport.calls, 0)
        self.assertEqual(rig.events(), [("budget", 1, "failed", "RunDollarCap", None)])

    def test_dollar_cap_counts_settled_spend(self) -> None:
        """After $0.007 is spent, a $0.016 cap refuses a call whose output alone may cost $0.010."""
        rig = Rig([reply(input_tokens=1000, output_tokens=500), reply()], dollar_cap=0.016)
        rig.client.call(ModelRequest(body("first")))
        self.assertAlmostEqual(rig.budget.run_spent_usd, 0.007, places=9)
        with self.assertRaises(ModelCallFailed) as ctx:
            rig.client.call(ModelRequest(body("second", max_tokens=1000)))
        self.assertEqual(ctx.exception.reason, "BUDGET")
        self.assertEqual(rig.transport.calls, 1)

    def test_call_cap(self) -> None:
        """call_cap=2: the third distinct request is refused with CALL_CAP and never sent."""
        rig = Rig([reply(), reply(), reply()], call_cap=2)
        rig.client.call(ModelRequest(body("one")))
        rig.client.call(ModelRequest(body("two")))
        with self.assertRaises(ModelCallFailed) as ctx:
            rig.client.call(ModelRequest(body("three")))
        self.assertEqual(ctx.exception.reason, "CALL_CAP")
        self.assertEqual(rig.transport.calls, 2)

    def test_retries_count_against_call_cap(self) -> None:
        """Each send attempt is a call: call_cap=1 stops the retry after a 529."""
        rig = Rig([transport_failure(529, "OverloadedError")], call_cap=1)
        with self.assertRaises(ModelCallFailed) as ctx:
            rig.client.call(ModelRequest(body()))
        self.assertEqual(ctx.exception.reason, "CALL_CAP")
        self.assertEqual(rig.transport.calls, 1)

    def test_project_ledger_stop(self) -> None:
        """A ledger already at $109.995 stops a call that could cost $0.01 against the $110 stop."""
        rig = Rig([reply()], dollar_cap=50.0)
        rig.ledger.write_text(json.dumps({"key": "k", "cost_usd": 109.995}) + "\n")
        with self.assertRaises(ModelCallFailed) as ctx:
            rig.client.call(ModelRequest(body(max_tokens=1000)))
        self.assertEqual((ctx.exception.reason, ctx.exception.error_class), ("BUDGET", "ProjectLedgerCap"))
        self.assertEqual(rig.transport.calls, 0)

    def test_unreadable_ledger_stops(self) -> None:
        """A ledger line that is not JSON stops the call; it is never read as $0."""
        rig = Rig([reply()])
        rig.ledger.write_text("{broken\n")
        with self.assertRaises(ModelCallFailed) as ctx:
            rig.client.call(ModelRequest(body()))
        self.assertEqual((ctx.exception.reason, ctx.exception.error_class), ("BUDGET", "LedgerUnreadable"))

    def test_settle_appends_ledger_line(self) -> None:
        """One send appends one line costing 1000 x $2/M + 500 x $10/M = $0.007."""
        rig = Rig([reply(input_tokens=1000, output_tokens=500)])
        rig.client.call(ModelRequest(body()))
        lines = [json.loads(x) for x in rig.ledger.read_text().splitlines()]
        self.assertEqual(len(lines), 1)
        self.assertAlmostEqual(lines[0]["cost_usd"], 0.007, places=9)
        self.assertEqual(lines[0]["key"], ModelRequest(body()).key())


class TestPricing(unittest.TestCase):
    """Prices from research/13 section 2 (verify/13 C20-C24)."""

    def test_usage_cost(self) -> None:
        """A million of each token type costs its listed rate."""
        self.assertAlmostEqual(usage_cost("claude-sonnet-5-5", {"input_tokens": 1_000_000}), 2.00)
        self.assertAlmostEqual(usage_cost("claude-sonnet-5-5", {"output_tokens": 1_000_000}), 10.00)
        self.assertAlmostEqual(usage_cost("claude-sonnet-5-5", {"cache_read_input_tokens": 1_000_000}), 0.10)
        self.assertAlmostEqual(usage_cost("claude-sonnet-5-5", {
            "cache_creation_input_tokens": 2_000_000, "cache_creation.ephemeral_5m_input_tokens": 1_000_000,
            "cache_creation.ephemeral_1h_input_tokens": 1_000_000}), 6.50)
        self.assertAlmostEqual(usage_cost("claude-sonnet-5-5", {"cache_creation_input_tokens": 1_000_000}), 4.00)

    def test_worst_case_bounds(self) -> None:
        """The worst case covers full max_tokens output, and an image adds at least 4,784 input tokens."""
        plain = worst_case_cost(ModelRequest(body(max_tokens=8000)))
        self.assertGreater(plain, 8000 * 10 / 1_000_000)
        image = body(max_tokens=8000)
        image["messages"][0]["content"].insert(0, {"type": "image", "source": {
            "type": "base64", "media_type": "image/png", "data": "QUFB"}})
        self.assertGreaterEqual(worst_case_cost(ModelRequest(image)) - plain, 4784 * 2 / 1_000_000 - 1e-12)


if __name__ == "__main__":
    unittest.main()
