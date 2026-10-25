"""The call log records each failed call's error class and status."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from deletion_audit.model import (
    BudgetGuard,
    FakeTransport,
    JsonlCallLog,
    ModelCallFailed,
    ModelClient,
    ModelRequest,
    ReplyCache,
    RetryPolicy,
)

from ._support import Rig, body, reply, transport_failure


class TestCallLog(unittest.TestCase):
    """Failures and their decisions appear in the log."""

    def test_failed_call_logs_error_class_and_status(self) -> None:
        """A 429 then a 503 with two attempts allowed: two send entries, retry then give_up."""
        rig = Rig([transport_failure(429, "RateLimitError"), transport_failure(503, "InternalServerError")],
                  max_attempts=2)
        with self.assertRaises(ModelCallFailed):
            rig.client.call(ModelRequest(body()))
        self.assertEqual(rig.events(), [("send", 1, "retry", "RateLimitError", 429),
                                        ("send", 2, "give_up", "InternalServerError", 503)])
        self.assertEqual(rig.log.entries[-1].detail, "TRANSPORT_GAVE_UP")
        self.assertEqual({e.run_id for e in rig.log.entries}, {"run-test"})

    def test_jsonl_log_file(self) -> None:
        """The JSON-lines log holds the same fields, one line per entry, with no reply text."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log = JsonlCallLog(root / "run" / "calls.jsonl")
            secret_note = "unique-answer-text-7781"
            client = ModelClient(
                FakeTransport([transport_failure(None, "APITimeoutError"),
                               reply({"intent": "UNCERTAIN", "note": secret_note})]),
                ReplyCache(root / "replies"), BudgetGuard(5.0, 10, root / "ledger.jsonl"),
                RetryPolicy(sleep=lambda _s: None), log, replay_only=False, run_id="run-jsonl")
            with client:
                client.call(ModelRequest(body()))
            text = (root / "run" / "calls.jsonl").read_text()
            lines = [json.loads(x) for x in text.splitlines()]
            self.assertEqual([(x["event"], x["outcome"], x["error_class"], x["status"]) for x in lines],
                             [("send", "retry", "APITimeoutError", None), ("send", "ok", None, None)])
            self.assertEqual(lines[1]["usage"]["output_tokens"], 500)
            self.assertNotIn(secret_note, text)


if __name__ == "__main__":
    unittest.main()
