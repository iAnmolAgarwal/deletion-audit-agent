"""Builds the repaired request for a :class:`~.policy.Repair` decision.

The repair appends the decision's text as a new text block at the end of the last user
message (or as a new user message when the last message is not from the user). The failed
assistant reply is not replayed, so no thinking or partial ``tool_use`` block is ever edited
or resent. The body changes, so the repaired request has a new key and replays exactly.
"""
from __future__ import annotations

from typing import Any

from .request import ModelRequest


def build_repair(req: ModelRequest, text: str) -> ModelRequest:
    """Return ``req`` with ``text`` appended to the conversation's last user turn."""
    body = req.plain_body()
    messages: list[dict[str, Any]] = body["messages"]
    block = {"type": "text", "text": text}
    last = messages[-1]
    if last.get("role") != "user":
        messages.append({"role": "user", "content": [block]})
    elif isinstance(last.get("content"), str):
        last["content"] = [{"type": "text", "text": last["content"]}, block]
    else:
        last["content"] = [*list(last.get("content") or []), block]
    return ModelRequest(body)
