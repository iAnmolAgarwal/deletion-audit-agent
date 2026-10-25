"""The API's error text reaches calls.jsonl through AnthropicTransport and ModelClient, offline.

A stand-in SDK client raises real ``anthropic`` status errors built on ``httpx2`` responses, or
returns a canned reply. No test opens a connection or reads ``.env``; all values are made up.
"""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import Any

from deletion_audit.model import (
    AnthropicTransport,
    BudgetGuard,
    JsonlCallLog,
    ModelCallFailed,
    ModelClient,
    ModelRequest,
    ReplyCache,
    RetryPolicy,
    TransportFailure,
)

from ._support import body, reply

HAVE_SDK = importlib.util.find_spec("anthropic") is not None
URL = "https://example.invalid/v1/messages"


class _Raw:
    """A stand-in for the SDK's raw response."""

    def __init__(self, data: dict[str, Any]) -> None:
        """Hold the JSON to return."""
        self._data = data
        self.request_id = "req_fake_ok"

    def json(self) -> dict[str, Any]:
        """Return the canned JSON."""
        return self._data


class _SeqStub:
    """A stand-in client whose ``messages.with_raw_response.create`` plays ``actions`` in order."""

    max_retries = 0

    def __init__(self, actions: list[Any]) -> None:
        """Expose the attribute chain the transport uses."""
        self.messages = self
        self.with_raw_response = self
        self._actions = list(actions)
        self.sends = 0

    def create(self, **_kwargs: Any) -> Any:
        """Raise the next exception or return the next response."""
        self.sends += 1
        action = self._actions.pop(0)
        if isinstance(action, BaseException):
            raise action
        return action


def _response(status: int, content: bytes, headers: dict[str, str] | None = None) -> Any:
    """An ``httpx2`` response with ``content`` as its body."""
    import httpx2

    return httpx2.Response(status, headers=headers or {}, content=content,
                           request=httpx2.Request("POST", URL))


def _status_error(cls: Callable[..., Any], status: int, payload: Any, headers: dict[str, str]) -> Any:
    """A real SDK status error whose response body is ``payload`` (JSON-encoded unless bytes)."""
    content = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    parsed = payload.decode() if isinstance(payload, bytes) else payload
    return cls("fake error", response=_response(status, content, headers), body=parsed)


def _error_body(error_type: str, message: str) -> dict[str, Any]:
    """An API error body in the documented shape."""
    return {"type": "error", "error": {"type": error_type, "message": message}}


@unittest.skipUnless(HAVE_SDK, "anthropic SDK not installed in this interpreter")
class TestApiErrorText(unittest.TestCase):
    """HTTP error bodies are kept as capped data; other failures are unchanged."""

    def _run(self, actions: list[Any], *, max_attempts: int = 5) -> tuple[list[dict[str, Any]], _SeqStub]:
        """Call once through a real ModelClient with a JSON-lines log; return the log lines."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stub = _SeqStub(actions)
            client = ModelClient(AnthropicTransport(client=stub), ReplyCache(root / "replies"),
                                 BudgetGuard(5.0, 10, root / "ledger.jsonl"),
                                 RetryPolicy(sleep=lambda _s: None, max_attempts=max_attempts),
                                 JsonlCallLog(root / "run" / "calls.jsonl"), replay_only=False, run_id="run-fake")
            with client:
                try:
                    client.call(ModelRequest(body()))
                except ModelCallFailed:
                    pass
            lines = (root / "run" / "calls.jsonl").read_text().splitlines()
        return [json.loads(x) for x in lines], stub

    def test_bad_request_text_in_calls_jsonl(self) -> None:
        """A 400 keeps the API's error type, message and request ID; detail stays NON_RETRYABLE."""
        import anthropic

        exc = _status_error(anthropic.BadRequestError, 400,
                            _error_body("invalid_request_error", "fake: field x is not allowed"),
                            {"request-id": "req_fake_400"})
        lines, stub = self._run([exc])
        self.assertEqual(stub.sends, 1)
        self.assertEqual(len(lines), 1)
        entry = lines[0]
        self.assertEqual((entry["event"], entry["outcome"], entry["error_class"], entry["status"]),
                         ("send", "give_up", "BadRequestError", 400))
        self.assertEqual(entry["detail"], "NON_RETRYABLE")
        self.assertEqual(entry["api_error_type"], "invalid_request_error")
        self.assertEqual(entry["api_error_message"], "fake: field x is not allowed")
        self.assertEqual(entry["request_id"], "req_fake_400")

    def test_rate_limit_retried_with_text_each_attempt(self) -> None:
        """Two 429s with bodies are still retried, then a reply; each failed attempt has the text."""
        import anthropic

        def limited(n: int) -> Any:
            return _status_error(anthropic.RateLimitError, 429, _error_body("rate_limit_error", f"fake limit {n}"),
                                 {"request-id": f"req_fake_429_{n}", "retry-after": "0"})

        lines, stub = self._run([limited(1), limited(2), _Raw(reply())])
        self.assertEqual(stub.sends, 3)
        self.assertEqual([(x["outcome"], x["status"]) for x in lines],
                         [("retry", 429), ("retry", 429), ("ok", None)])
        for n, entry in enumerate(lines[:2], start=1):
            self.assertEqual((entry["api_error_type"], entry["api_error_message"], entry["request_id"]),
                             ("rate_limit_error", f"fake limit {n}", f"req_fake_429_{n}"))
            self.assertEqual(entry["detail"], "")
        self.assertEqual((lines[2]["api_error_type"], lines[2]["api_error_message"], lines[2]["request_id"]),
                         (None, None, "req_fake_ok"))

    def test_odd_bodies_give_null_fields(self) -> None:
        """A non-JSON body, a body with no error object, and non-string fields: no crash, None."""
        import anthropic

        transport_bodies: list[Any] = [b"<html>bad gateway</html>", {"type": "error"},
                                       {"error": "not an object"}, {"error": {"type": 7, "message": None}}, None]
        for payload in transport_bodies:
            with self.subTest(payload=payload):
                if payload is None:
                    exc = anthropic.BadRequestError("fake", response=_response(400, b""), body=None)
                else:
                    exc = _status_error(anthropic.BadRequestError, 400, payload, {})
                with self.assertRaises(TransportFailure) as ctx:
                    AnthropicTransport(client=_SeqStub([exc])).send({"model": "claude-sonnet-5-5"})
                f = ctx.exception.failure
                self.assertEqual((f.error_class, f.status, f.api_error_type, f.api_error_message, f.request_id),
                                 ("BadRequestError", 400, None, None, None))

    def test_long_message_cut_with_marker(self) -> None:
        """A message over 500 characters is cut to 500, ending in the cut marker."""
        import anthropic

        from deletion_audit.model.transport import API_TEXT_LIMIT, cap_api_text

        long_message = "x" * 1200
        exc = _status_error(anthropic.BadRequestError, 400, _error_body("invalid_request_error", long_message), {})
        lines, _stub = self._run([exc])
        kept = lines[0]["api_error_message"]
        self.assertEqual(len(kept), API_TEXT_LIMIT)
        self.assertTrue(kept.endswith("...[cut, 1200 chars]"))
        self.assertTrue(kept.startswith("x" * 100))
        self.assertEqual(cap_api_text("y" * 500), "y" * 500)
        self.assertIsNone(cap_api_text(42))

    def test_connection_error_fields_null(self) -> None:
        """A connection error is retried as before and logs no API error text."""
        import anthropic
        import httpx2

        conn = anthropic.APIConnectionError(request=httpx2.Request("POST", URL))
        lines, stub = self._run([conn, _Raw(reply())])
        self.assertEqual(stub.sends, 2)
        self.assertEqual([(x["outcome"], x["error_class"], x["status"]) for x in lines],
                         [("retry", "APIConnectionError", None), ("ok", None, None)])
        self.assertEqual((lines[0]["api_error_type"], lines[0]["api_error_message"], lines[0]["request_id"]),
                         (None, None, None))


if __name__ == "__main__":
    unittest.main()
