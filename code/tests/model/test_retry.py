"""The transport retry ladder, retry-after handling and the single give-up place."""
from __future__ import annotations

import ast
import unittest
from email.utils import formatdate
from pathlib import Path

from deletion_audit.model import ModelCallFailed, ModelRequest
from deletion_audit.model.policy import parse_retry_after

from ._support import Rig, body, reply, transport_failure

MODEL_PKG = Path(__file__).resolve().parents[2] / "deletion_audit" / "model"

RETRIED = [(408, "APIStatusError"), (409, "ConflictError"), (429, "RateLimitError"),
           (500, "InternalServerError"), (503, "InternalServerError"), (504, "InternalServerError"),
           (529, "OverloadedError"), (None, "APIConnectionError"), (None, "APITimeoutError")]
NOT_RETRIED = [(400, "BadRequestError"), (401, "AuthenticationError"), (402, "APIStatusError"),
               (403, "PermissionDeniedError"), (404, "NotFoundError"), (413, "RequestTooLargeError"),
               (422, "UnprocessableEntityError"), (None, "AnthropicError")]


class TestLadder(unittest.TestCase):
    """Each status class is retried or not, with the pinned waits and attempt limit."""

    def test_retry_ladder_fake_client(self) -> None:
        """One failure then success: 2 sends, one 1-second wait, reply returned."""
        for status, cls in RETRIED:
            with self.subTest(status=status, cls=cls):
                rig = Rig([transport_failure(status, cls), reply()])
                out = rig.client.call(ModelRequest(body()))
                self.assertEqual(rig.transport.calls, 2)
                self.assertEqual(rig.sleeps, [1.0])
                self.assertEqual(out.stop_reason, "end_turn")
                self.assertFalse(out.from_cache)

    def test_non_retryable_gives_up_after_one_send(self) -> None:
        """A non-retryable status: one send, NON_RETRYABLE, status and class kept, no wait."""
        for status, cls in NOT_RETRIED:
            with self.subTest(status=status, cls=cls):
                rig = Rig([transport_failure(status, cls)])
                with self.assertRaises(ModelCallFailed) as ctx:
                    rig.client.call(ModelRequest(body()))
                self.assertEqual((ctx.exception.reason, ctx.exception.error_class, ctx.exception.status),
                                 ("NON_RETRYABLE", cls, status))
                self.assertEqual(rig.transport.calls, 1)
                self.assertEqual(rig.sleeps, [])

    def test_exhaustion_after_five_sends(self) -> None:
        """Five 529s: five sends, waits 1, 2, 4, 8 s, then TRANSPORT_GAVE_UP."""
        rig = Rig([transport_failure(529, "OverloadedError")] * 5)
        with self.assertRaises(ModelCallFailed) as ctx:
            rig.client.call(ModelRequest(body()))
        self.assertEqual(ctx.exception.reason, "TRANSPORT_GAVE_UP")
        self.assertEqual(ctx.exception.status, 529)
        self.assertEqual(rig.transport.calls, 5)
        self.assertEqual(rig.sleeps, [1.0, 2.0, 4.0, 8.0])

    def test_should_retry_header_overrides(self) -> None:
        """x-should-retry false stops a 529; true retries a 400."""
        rig = Rig([transport_failure(529, "OverloadedError", should_retry="false")])
        with self.assertRaises(ModelCallFailed) as ctx:
            rig.client.call(ModelRequest(body()))
        self.assertEqual(ctx.exception.reason, "NON_RETRYABLE")
        rig = Rig([transport_failure(400, "BadRequestError", should_retry="true"), reply()])
        rig.client.call(ModelRequest(body()))
        self.assertEqual(rig.transport.calls, 2)

    def test_malformed_reply_not_retried(self) -> None:
        """A reply without usage is a NON_RETRYABLE MalformedReply, charged at the reserved worst case."""
        rig = Rig([{"content": [], "stop_reason": "end_turn", "model": "claude-sonnet-5-5"}])
        with self.assertRaises(ModelCallFailed) as ctx:
            rig.client.call(ModelRequest(body(max_tokens=1000)))
        self.assertEqual((ctx.exception.reason, ctx.exception.error_class), ("NON_RETRYABLE", "MalformedReply"))
        self.assertGreaterEqual(rig.budget.run_spent_usd, 1000 * 10 / 1_000_000)


class TestRetryAfter(unittest.TestCase):
    """Server waits are honoured when sane."""

    def test_retry_after_header_honoured(self) -> None:
        """A 3.5 s retry-after replaces the 1 s backoff; a 120 s one falls back to backoff."""
        rig = Rig([transport_failure(429, "RateLimitError", retry_after_s=3.5), reply()])
        rig.client.call(ModelRequest(body()))
        self.assertEqual(rig.sleeps, [3.5])
        rig = Rig([transport_failure(429, "RateLimitError", retry_after_s=120.0), reply()])
        rig.client.call(ModelRequest(body()))
        self.assertEqual(rig.sleeps, [1.0])

    def test_parse_retry_after(self) -> None:
        """retry-after-ms wins; retry-after takes seconds or an HTTP date."""
        now = 1_800_000_000.0
        self.assertEqual(parse_retry_after({"retry-after-ms": "1500", "retry-after": "9"}, now), 1.5)
        self.assertEqual(parse_retry_after({"Retry-After": "7"}, now), 7.0)
        self.assertAlmostEqual(parse_retry_after({"retry-after": formatdate(now + 30, usegmt=True)}, now) or 0,
                               30.0, places=3)
        self.assertIsNone(parse_retry_after({}, now))
        self.assertIsNone(parse_retry_after({"retry-after": "soon"}, now))


class TestGiveUpSinglePlace(unittest.TestCase):
    """Only the policy builds GiveUp; only the client's _give_up turns it into ModelCallFailed."""

    def _calls(self, name: str) -> dict[str, list[tuple[str, ast.Call]]]:
        """Map each module to (enclosing function, call node) for every call of ``name``."""
        found: dict[str, list[tuple[str, ast.Call]]] = {}
        for path in sorted(MODEL_PKG.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for fn in ast.walk(tree):
                if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for node in ast.walk(fn):
                        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == name:
                            found.setdefault(path.name, []).append((fn.name, node))
        return found

    def test_give_up_single_place(self) -> None:
        """GiveUp( only in policy.py; ModelCallFailed( in client._give_up once, else budget caps only."""
        self.assertEqual(sorted(self._calls("GiveUp")), ["policy.py"])
        raises = self._calls("ModelCallFailed")
        self.assertEqual(sorted(raises), ["budget.py", "client.py"])
        self.assertEqual([fn for fn, _ in raises["client.py"]], ["_give_up"])
        budget_reasons = {n.args[0].value for _, n in raises["budget.py"] if isinstance(n.args[0], ast.Constant)}
        self.assertEqual(len(raises["budget.py"]), 5)
        self.assertEqual(budget_reasons, {"BUDGET", "CALL_CAP"})


if __name__ == "__main__":
    unittest.main()
