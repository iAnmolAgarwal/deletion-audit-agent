"""The model reply as the client hands it back, plus helpers that read a raw reply."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .request import ModelRequest


@dataclass(frozen=True)
class ModelReply:
    """One reply, fresh or replayed from the reply cache.

    Attributes:
        key: the request key this reply answers.
        raw: the reply JSON exactly as the API returned it.
        model: the model ID the reply names.
        usage: the reply's ``usage`` flattened to integers (see :func:`flatten_usage`).
        stop_reason: the reply's ``stop_reason``.
        request_id: the API ``request-id`` header, when the transport saw one.
        from_cache: True when this reply was read from the cache, not bought in this call.
        bought_by_run: the run ID that paid for the reply.
        request: the request this reply answers (after a repair, the repaired request). It is
            deep read-only and cannot be changed in place; to extend the conversation, build a
            new :class:`ModelRequest` from ``request.plain_body()`` plus the new messages.
    """

    key: str
    raw: Mapping[str, Any]
    model: str
    usage: Mapping[str, int]
    stop_reason: str
    request_id: str | None
    from_cache: bool
    bought_by_run: str
    request: ModelRequest


def flatten_usage(usage: Any) -> dict[str, int]:
    """Flatten a raw ``usage`` object to ``{name: int}``; nested objects use dotted names.

    Only integer leaves are kept (``service_tier`` and similar strings are dropped). A missing
    or non-object usage gives an empty mapping.
    """
    flat: dict[str, int] = {}
    if not isinstance(usage, Mapping):
        return flat
    for name, value in usage.items():
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            flat[str(name)] = value
        elif isinstance(value, Mapping):
            for sub, sub_value in flatten_usage(value).items():
                flat[f"{name}.{sub}"] = sub_value
    return flat


def content_blocks(raw: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """The reply's content blocks that are objects, in order."""
    content = raw.get("content")
    if not isinstance(content, list):
        return []
    return [b for b in content if isinstance(b, Mapping)]


def reply_text(raw: Mapping[str, Any]) -> str | None:
    """The text of the last ``text`` block (thinking blocks may come first), or None."""
    texts = [b.get("text") for b in content_blocks(raw) if b.get("type") == "text"]
    texts = [t for t in texts if isinstance(t, str)]
    return texts[-1] if texts else None


def tool_uses(raw: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """The reply's ``tool_use`` blocks, in order."""
    return [b for b in content_blocks(raw) if b.get("type") == "tool_use"]
