"""AnthropicTransport against SDK 1.13.0, offline: error mapping, construction, SDK facts.

No test sends a request. Clients are built with a made-up key, or replaced by a stub whose
``messages.with_raw_response.create`` raises or returns a canned response.
"""
from __future__ import annotations

import importlib.util
import inspect
import os
import unittest
from typing import Any
from unittest import mock

from deletion_audit.model import AnthropicTransport, TransportConfigError, TransportFailure
from deletion_audit.model.request import ALLOWED_FIELDS, API_VERSION

HAVE_SDK = importlib.util.find_spec("anthropic") is not None
DUMMY_KEY = "test-dummy-key-not-real"


class _Raw:
    """A stand-in for the SDK's raw response."""

    def __init__(self, data: dict[str, Any]) -> None:
        """Hold the JSON to return."""
        self._data = data
        self.request_id = "req_stub"

    def json(self) -> dict[str, Any]:
        """Return the canned JSON."""
        return self._data


class _Stub:
    """A stand-in client: ``messages.with_raw_response.create`` runs ``action``."""

    max_retries = 0

    def __init__(self, action: Any) -> None:
        """Expose the attribute chain the transport uses."""
        self.messages = self
        self.with_raw_response = self
        self._action = action
        self.kwargs: dict[str, Any] = {}

    def create(self, **kwargs: Any) -> Any:
        """Record the kwargs, then raise or return."""
        self.kwargs = kwargs
        if isinstance(self._action, BaseException):
            raise self._action
        return self._action


@unittest.skipUnless(HAVE_SDK, "anthropic SDK not installed in this interpreter")
class TestAnthropicTransport(unittest.TestCase):
    """Offline checks of the real transport."""

    def _response(self, status: int, headers: dict[str, str] | None = None) -> Any:
        """An httpx2 response for building SDK exceptions."""
        import httpx2

        request = httpx2.Request("POST", "https://example.invalid/v1/messages")
        return httpx2.Response(status, headers=headers or {}, request=request)

    def _failure_for(self, exc: BaseException) -> Any:
        """Send through a stub that raises ``exc``; return the TransportFailure's Failure."""
        transport = AnthropicTransport(client=_Stub(exc))
        with self.assertRaises(TransportFailure) as ctx:
            transport.send({"model": "claude-sonnet-5-5"})
        return ctx.exception.failure

    def test_status_errors_mapped(self) -> None:
        """SDK status errors keep their class name, status and retry headers."""
        import anthropic

        f = self._failure_for(anthropic.RateLimitError(
            "limited", response=self._response(429, {"retry-after": "2", "x-should-retry": "true"}), body=None))
        self.assertEqual((f.kind, f.error_class, f.status, f.retry_after_s, f.should_retry),
                         ("TRANSPORT", "RateLimitError", 429, 2.0, "true"))
        f = self._failure_for(anthropic.OverloadedError("busy", response=self._response(529), body=None))
        self.assertEqual((f.error_class, f.status, f.retry_after_s), ("OverloadedError", 529, None))

    def test_connection_errors_mapped(self) -> None:
        """Timeouts and connection errors have no status and keep their class name."""
        import anthropic
        import httpx2

        request = httpx2.Request("POST", "https://example.invalid/v1/messages")
        f = self._failure_for(anthropic.APITimeoutError(request=request))
        self.assertEqual((f.error_class, f.status), ("APITimeoutError", None))
        f = self._failure_for(anthropic.APIConnectionError(request=request))
        self.assertEqual((f.error_class, f.status), ("APIConnectionError", None))

    def test_sdk_maps_503_504_to_internal_server_error(self) -> None:
        """SDK 1.13.0 raises InternalServerError for 503 and 504 (verify/13 WRONG #2 holds here too)."""
        import anthropic

        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": DUMMY_KEY}):
            client = anthropic.Anthropic(api_key=DUMMY_KEY, max_retries=0)
        for status in (503, 504):
            err = client._make_status_error("x", body=None, response=self._response(status))
            self.assertEqual(type(err).__name__, "InternalServerError")

    def test_success_envelope(self) -> None:
        """A reply comes back as the raw JSON plus the request-id; the body is passed as kwargs."""
        data = {"stop_reason": "end_turn", "content": []}
        stub = _Stub(_Raw(data))
        out = AnthropicTransport(client=stub).send({"model": "claude-sonnet-5-5", "max_tokens": 5})
        self.assertEqual(out, {"reply": data, "request_id": "req_stub"})
        self.assertEqual(stub.kwargs, {"model": "claude-sonnet-5-5", "max_tokens": 5})

    def test_built_from_environment_with_retries_off(self) -> None:
        """Built from ANTHROPIC_API_KEY: max_retries 0, version header pinned, key sent as X-Api-Key."""
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": DUMMY_KEY}):
            transport = AnthropicTransport()
        client = transport._client
        self.assertEqual(client.max_retries, 0)
        self.assertEqual(client.default_headers["anthropic-version"], "2023-06-01")
        self.assertEqual(API_VERSION, "2023-06-01")
        self.assertEqual(client.auth_headers, {"X-Api-Key": DUMMY_KEY})

    def test_refuses_without_key_or_with_retries(self) -> None:
        """No key in the environment, or an injected client that retries, is refused."""
        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
        with mock.patch.dict(os.environ, env, clear=True), self.assertRaises(TransportConfigError):
            AnthropicTransport()
        retrying = _Stub(None)
        retrying.max_retries = 2
        with self.assertRaises(TransportConfigError):
            AnthropicTransport(client=retrying)

    def test_sdk_create_signature(self) -> None:
        """messages.create in 1.13.0 takes every allowed body field and no sampling parameter."""
        import anthropic

        params = set(inspect.signature(anthropic.resources.messages.Messages.create).parameters)
        self.assertLessEqual(ALLOWED_FIELDS, params)
        self.assertEqual({"temperature", "top_p", "top_k"} & params, set())
        self.assertEqual(anthropic._constants.ANTHROPIC_API_VERSION, API_VERSION)


if __name__ == "__main__":
    unittest.main()
