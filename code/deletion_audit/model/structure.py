"""Checks a reply's structure against its request; reports a :class:`Failure` or None.

A reply passes when:

* ``stop_reason`` is ``tool_use`` and the request allowed tool calls, with at least one
  ``tool_use`` block; or
* ``stop_reason`` is ``end_turn`` and the last text block is a JSON value that matches the
  request's ``output_config.format`` schema (re-validated by :mod:`.schema_check`).

Anything else is a failure: ``max_tokens``, ``refusal``, ``model_context_window_exceeded``
and other stop reasons are named by their stop reason; ``NoText`` and ``SchemaMismatch``
cover a bad ``end_turn``. A ``max_tokens`` reply fails even when its text is valid JSON
(``verify/13`` WRONG #1: treat any ``max_tokens`` response as failed).
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from .policy import Failure
from .reply import reply_text, tool_uses
from .request import ModelRequest
from .schema_check import validate


def _failure(error_class: str, detail: str = "") -> Failure:
    """A reply failure on an HTTP 200 reply."""
    return Failure(kind="STRUCTURE", error_class=error_class, status=200, detail=detail)


def check_structure(req: ModelRequest, raw: Mapping[str, Any]) -> Failure | None:
    """Return the reply failure for ``raw`` as an answer to ``req``, or None when it passes."""
    stop = raw.get("stop_reason")
    if stop == "tool_use":
        if req.tools_enabled and tool_uses(raw):
            return None
        return _failure("tool_use", "tool call where none was allowed, or no tool_use block")
    if stop != "end_turn":
        return _failure(str(stop))
    text = reply_text(raw)
    if text is None or not text.strip():
        return _failure("NoText")
    try:
        value = json.loads(text)
    except ValueError:
        return _failure("SchemaMismatch", "answer text is not JSON")
    errors = validate(value, req.output_schema)
    if errors:
        return _failure("SchemaMismatch", f"{len(errors)} schema errors; first: {errors[0]}")
    return None
