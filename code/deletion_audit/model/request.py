"""The model request: a checked, frozen request body and its content-addressed key.

A :class:`ModelRequest` holds only the Messages API body. Its key is the sha256 of the
canonical JSON of that body followed by the ``anthropic-version`` header value, so it never
depends on a case ID, a row position or anything outside the body.

Rules checked when the request is built (each raises :class:`RequestRejected`):

* only the top-level fields in :data:`ALLOWED_FIELDS`; ``temperature``, ``top_p``, ``top_k``
  and ``stream`` are refused by name;
* ``model`` is one with a price in :mod:`.prices` (the budget guard needs one);
* ``tool_choice``, when present, is ``{"type": "auto"}`` or ``{"type": "none"}``;
* ``output_config.format`` is a ``json_schema`` format whose schema the in-code checker
  fully supports, and ``output_config.effort`` is set to a fixed level;
* ``max_tokens`` is a positive integer no larger than :data:`MAX_NONSTREAMING_TOKENS`;
* the body is plain JSON (no NaN, no non-string keys).
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from .errors import RequestRejected
from .prices import PRICES
from .schema_check import check_schema_supported, unresolved_refs

API_VERSION = "2023-06-01"
"""The ``anthropic-version`` header. SDK 1.13.0 sends this value (``anthropic/_constants.py``
``ANTHROPIC_API_VERSION``); :class:`~.transport.AnthropicTransport` also sets it explicitly."""

ALLOWED_FIELDS: frozenset[str] = frozenset({
    "model", "max_tokens", "messages", "system", "tools", "tool_choice", "output_config",
    "thinking", "cache_control",
})
SAMPLING_FIELDS: frozenset[str] = frozenset({"temperature", "top_p", "top_k"})
ALLOWED_TOOL_CHOICES: frozenset[str] = frozenset({"auto", "none"})
ALLOWED_EFFORTS: frozenset[str] = frozenset({"low", "medium", "high", "xhigh", "max"})

MAX_NONSTREAMING_TOKENS = 21_333
"""SDK 1.13.0 raises ValueError for a non-streaming call when ``3600 * max_tokens / 128000``
exceeds 600 s (``anthropic/_base_client.py`` ``_calculate_nonstreaming_timeout``); 21,333 is
the largest value that passes (same formula as 2.3.0, ``verify/13`` C08)."""


def canonical_json(value: Any) -> str:
    """Serialize ``value`` as canonical JSON: sorted keys, no spaces, UTF-8 text, no NaN."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def freeze(value: Any) -> Any:
    """A read-only deep copy of a JSON value: objects become MappingProxyType, arrays tuples."""
    if isinstance(value, Mapping):
        return MappingProxyType({k: freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze(v) for v in value)
    return value


def thaw(value: Any) -> Any:
    """A plain, mutable deep copy of a JSON value (mappings become dicts, tuples lists)."""
    if isinstance(value, Mapping):
        return {k: thaw(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [thaw(v) for v in value]
    return value


def _plain_copy(body: Mapping[str, Any]) -> dict[str, Any]:
    """Return a private deep copy of ``body`` as plain JSON, or raise RequestRejected."""
    try:
        copied = json.loads(canonical_json(thaw(body)))
    except (TypeError, ValueError) as exc:
        raise RequestRejected(f"request body is not plain JSON: {exc}") from exc
    if not isinstance(copied, dict):
        raise RequestRejected("request body must be a JSON object")
    return copied


def _check_fields(body: Mapping[str, Any]) -> None:
    """Reject sampling parameters, streaming and any field outside :data:`ALLOWED_FIELDS`."""
    sampling = sorted(SAMPLING_FIELDS & set(body))
    if sampling:
        raise RequestRejected(f"sampling parameters are not allowed: {sampling}")
    unknown = sorted(set(body) - ALLOWED_FIELDS)
    if unknown:
        raise RequestRejected(f"fields not allowed in a request body: {unknown}")
    for required in ("model", "max_tokens", "messages", "output_config"):
        if required not in body:
            raise RequestRejected(f"request body needs {required!r}")


def _check_model_and_tokens(body: Mapping[str, Any]) -> None:
    """Check ``model`` has a price and ``max_tokens`` is in range."""
    if body["model"] not in PRICES:
        raise RequestRejected(f"no price for model {body['model']!r}")
    max_tokens = body["max_tokens"]
    if not isinstance(max_tokens, int) or isinstance(max_tokens, bool) or max_tokens <= 0:
        raise RequestRejected("max_tokens must be a positive integer")
    if max_tokens > MAX_NONSTREAMING_TOKENS:
        raise RequestRejected(f"max_tokens above {MAX_NONSTREAMING_TOKENS} needs streaming")
    messages = body["messages"]
    if not isinstance(messages, list) or not messages:
        raise RequestRejected("messages must be a non-empty list")


def _check_tool_choice(body: Mapping[str, Any]) -> None:
    """Allow only ``auto`` and ``none``; forced choices (``any``, ``tool``) return 400 on Sonnet 5.5."""
    if "tool_choice" not in body:
        return
    choice = body["tool_choice"]
    if not isinstance(choice, Mapping) or choice.get("type") not in ALLOWED_TOOL_CHOICES:
        raise RequestRejected(f"tool_choice must be auto or none, got {choice!r}")


def _check_output_config(body: Mapping[str, Any]) -> None:
    """Require a supported ``json_schema`` format and a fixed effort level."""
    config = body["output_config"]
    if not isinstance(config, Mapping):
        raise RequestRejected("output_config must be an object")
    if config.get("effort") not in ALLOWED_EFFORTS:
        raise RequestRejected(f"output_config.effort must be one of {sorted(ALLOWED_EFFORTS)}")
    fmt = config.get("format")
    if not isinstance(fmt, Mapping) or fmt.get("type") != "json_schema" or "schema" not in fmt:
        raise RequestRejected("output_config.format must be {'type': 'json_schema', 'schema': ...}")
    problems = check_schema_supported(fmt["schema"]) + [
        f"unresolved $ref {r}" for r in unresolved_refs(fmt["schema"])]
    if problems:
        raise RequestRejected(f"output schema not fully checkable in code: {problems}")


@dataclass(frozen=True)
class ModelRequest:
    """A checked Messages API request body.

    ``body`` holds model, system, tools, tool_choice, messages, output_config (format and
    effort) and max_tokens. The stored body is a private, deep read-only copy (objects are
    ``MappingProxyType``, arrays are tuples), so neither the caller's mapping nor the stored body
    can change after the rules were checked. The canonical text the key hashes is fixed when the
    request is built; :meth:`recheck` confirms the body still produces it.
    """

    body: Mapping[str, Any]

    def __post_init__(self) -> None:
        """Copy the body, apply every build-time rule, then store it deep-frozen."""
        plain = _plain_copy(self.body)
        _check_fields(plain)
        _check_model_and_tokens(plain)
        _check_tool_choice(plain)
        _check_output_config(plain)
        object.__setattr__(self, "body", freeze(plain))
        object.__setattr__(self, "_canonical", canonical_json(plain))

    def key(self) -> str:
        """sha256 hex of ``canonical_json(body) + API_VERSION``, from the text fixed at build time."""
        canonical: str = object.__getattribute__(self, "_canonical")
        return hashlib.sha256((canonical + API_VERSION).encode("utf-8")).hexdigest()

    def plain_body(self) -> dict[str, Any]:
        """A fresh, mutable deep copy of the body, for sending or for building a new request."""
        return _plain_copy(self.body)

    def recheck(self) -> dict[str, Any]:
        """Re-apply every rule to the stored body and confirm it still has this key; return it plain.

        Raises :class:`RequestRejected` when a rule fails or the body no longer hashes to the key.
        """
        plain = self.plain_body()
        if ModelRequest(plain).key() != self.key():
            raise RequestRejected("request body changed after the request was built")
        return plain

    @property
    def output_schema(self) -> Mapping[str, Any]:
        """A plain copy of the JSON schema under ``output_config.format``."""
        schema: Mapping[str, Any] = thaw(self.body["output_config"]["format"]["schema"])
        return schema

    @property
    def tools_enabled(self) -> bool:
        """Whether the model may answer with a tool call (tools sent and tool_choice not none)."""
        choice = self.body.get("tool_choice") or {"type": "auto"}
        return bool(self.body.get("tools")) and choice.get("type") != "none"
