"""Transports: the only code that sends a request.

``Transport.send(body)`` returns an envelope ``{"reply": <reply JSON as returned>,
"request_id": <request-id header or None>}`` or raises :class:`TransportFailure`, which
carries a :class:`~.policy.Failure` with the error class, status and retry headers. For an HTTP
error status (``anthropic.APIStatusError``) the Failure also carries the API's error ``type`` and
``message`` from the parsed error body, each capped at :data:`API_TEXT_LIMIT` characters, and
the response's request ID. That text is API-generated and untrusted: it is stored as data only.
Connection errors, timeouts and unreadable replies leave those three fields None.

* :class:`AnthropicTransport` wraps ``anthropic.Anthropic`` (SDK 1.13.0) with
  ``max_retries=0`` so the client's own ladder is the only retry loop. It reads
  ``ANTHROPIC_API_KEY`` from the environment when constructed, never from a file.
* :class:`FakeTransport` replays a scripted list of replies and failures and records every
  body it was sent. It never opens a connection.
"""
from __future__ import annotations

import os
import time
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from .policy import Failure, parse_retry_after
from .request import API_VERSION

API_TEXT_LIMIT = 500
"""The most characters of API error text kept in a Failure (marker included)."""


def cap_api_text(value: object, limit: int = API_TEXT_LIMIT) -> str | None:
    """``value`` if it is a string of at most ``limit`` characters; a longer string is cut to
    ``limit`` characters ending in a ``...[cut, N chars]`` marker; anything else gives None."""
    if not isinstance(value, str):
        return None
    if len(value) <= limit:
        return value
    marker = f"...[cut, {len(value)} chars]"
    return value[: max(limit - len(marker), 0)] + marker


def api_error_fields(body: object) -> tuple[str | None, str | None]:
    """``(type, message)`` from an API error body ``{"type": "error", "error": {...}}``.

    A body that is missing or not that shape gives ``(None, None)``; a field that is not a
    string gives None for that field. Both values are capped by :func:`cap_api_text`.
    """
    error = body.get("error") if isinstance(body, Mapping) else None
    if not isinstance(error, Mapping):
        return None, None
    return cap_api_text(error.get("type")), cap_api_text(error.get("message"))


def _status_failure(exc: Any) -> Failure:
    """The Failure for an ``anthropic.APIStatusError``: status, retry headers and API error text."""
    headers = exc.response.headers
    error_type, error_message = api_error_fields(getattr(exc, "body", None))
    request_id = getattr(exc, "request_id", None) or headers.get("request-id")
    return Failure(
        kind="TRANSPORT", error_class=type(exc).__name__, status=exc.status_code,
        retry_after_s=parse_retry_after(dict(headers.items()), time.time()),
        should_retry=headers.get("x-should-retry"), api_error_type=error_type,
        api_error_message=error_message, request_id=cap_api_text(request_id))


class TransportFailure(Exception):
    """A send that returned no reply; ``failure`` describes it for the retry policy."""

    def __init__(self, failure: Failure) -> None:
        """Wrap ``failure``."""
        super().__init__(f"{failure.error_class} (status={failure.status})")
        self.failure = failure


class Transport(Protocol):
    """Sends one request body and returns the reply envelope."""

    def send(self, body: Mapping[str, Any]) -> Mapping[str, Any]:
        """Send ``body``; return ``{"reply": ..., "request_id": ...}`` or raise TransportFailure."""
        ...


class FakeTransport:
    """A scripted transport for tests.

    ``script`` items are consumed in order: a mapping is returned as the reply JSON, a
    :class:`Failure` is raised as a :class:`TransportFailure`. Sending past the end of the
    script raises AssertionError.
    """

    def __init__(self, script: Sequence[Mapping[str, Any] | Failure] = ()) -> None:
        """Store the script; ``sent`` records each body sent."""
        self.script: list[Mapping[str, Any] | Failure] = list(script)
        self.sent: list[Mapping[str, Any]] = []

    @property
    def calls(self) -> int:
        """How many sends were made."""
        return len(self.sent)

    def send(self, body: Mapping[str, Any]) -> Mapping[str, Any]:
        """Record ``body`` and play the next script item."""
        self.sent.append(body)
        if not self.script:
            raise AssertionError("FakeTransport: send past the end of the script")
        item = self.script.pop(0)
        if isinstance(item, Failure):
            raise TransportFailure(item)
        return {"reply": item, "request_id": f"fake-request-{len(self.sent)}"}


class TransportConfigError(RuntimeError):
    """The real transport cannot be built (no API key in the environment, or retries enabled)."""


class AnthropicTransport:
    """The Anthropic Messages API through SDK 1.13.0, with SDK retries off.

    ``client`` may be given (an ``anthropic.Anthropic`` or a stand-in with the same
    ``messages.with_raw_response.create``); a client with ``max_retries`` other than 0 is
    refused. Otherwise one is built from ``ANTHROPIC_API_KEY`` with ``max_retries=0`` and the
    ``anthropic-version`` header pinned to :data:`~.request.API_VERSION`.
    """

    def __init__(self, *, client: Any | None = None) -> None:
        """Build or accept the SDK client; reads the API key from the environment only."""
        if client is None:
            client = self._build_client()
        if getattr(client, "max_retries", 0) != 0:
            raise TransportConfigError("the SDK client must have max_retries=0")
        self._client = client

    @staticmethod
    def _build_client() -> Any:
        """Construct ``anthropic.Anthropic`` from the environment's API key."""
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise TransportConfigError("ANTHROPIC_API_KEY is not set in the environment")
        import anthropic  # imported here so the package imports without the SDK installed

        return anthropic.Anthropic(api_key=key, max_retries=0,
                                   default_headers={"anthropic-version": API_VERSION})

    def send(self, body: Mapping[str, Any]) -> Mapping[str, Any]:
        """Send ``body`` once through ``messages.with_raw_response.create``.

        A connection lost while the reply body is read (an ``httpx2`` transport error) is
        reported as ``APIConnectionError`` with no status; a 200 body that is not JSON is
        reported as ``MalformedReply`` with status 200. An HTTP error status keeps the API's
        error type, message and request ID (see :func:`_status_failure`).
        """
        import anthropic
        import httpx2

        try:
            raw_response = self._client.messages.with_raw_response.create(**dict(body))
        except anthropic.APIStatusError as exc:
            raise TransportFailure(_status_failure(exc)) from exc
        except anthropic.APIConnectionError as exc:  # APITimeoutError is a subclass
            raise TransportFailure(Failure(kind="TRANSPORT", error_class=type(exc).__name__)) from exc
        except anthropic.AnthropicError as exc:  # any other SDK error: no status, not retried
            raise TransportFailure(Failure(kind="TRANSPORT", error_class=type(exc).__name__)) from exc
        try:
            reply = raw_response.json()
        except httpx2.TransportError as exc:
            raise TransportFailure(Failure(kind="TRANSPORT", error_class="APIConnectionError",
                                           detail=f"{type(exc).__name__} while reading the reply")) from exc
        except ValueError as exc:  # json.JSONDecodeError is a ValueError
            raise TransportFailure(Failure(kind="TRANSPORT", error_class="MalformedReply", status=200,
                                           detail="reply body is not JSON")) from exc
        return {"reply": reply, "request_id": raw_response.request_id}
