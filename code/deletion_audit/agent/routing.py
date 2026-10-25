"""The turn-1 routing check (G3 section 3; T70): every distinct text, read once per namespace.

Each client must have its own reply-cache root, so the second reading of a text is an
independent reply, not a replay of the first (the T88 replicate rule, as for vision). The table
names texts by sha256 prefix, never by the text itself (``artifacts.py`` rule).
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from ..model import ModelClient
from .intent import run_turn1
from .tools import tool_definitions


def text_id(text: str) -> str:
    """A stable name for a request text: ``t_`` plus 12 hex characters of its sha256."""
    return "t_" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def routing_table(texts: Iterable[str], clients: Sequence[ModelClient]) -> list[dict[str, Any]]:
    """One row per distinct text: the label from each client, and whether they all agree."""
    roots = {Path(c.cache.root).resolve() for c in clients}
    if len(roots) != len(clients):
        raise ValueError("each replicate needs its own reply-cache root")
    tools = tool_definitions()
    rows = []
    for text in sorted(set(texts), key=text_id):
        readings = [run_turn1(text, tools, c) for c in clients]
        labels = [r.label for r in readings]
        rows.append({
            "text_id": text_id(text),
            "labels": labels,
            "via": [r.via for r in readings],
            "quote_valid": [r.quote_valid for r in readings],
            "agree": len(set(labels)) == 1 and labels[0] is not None,
            "request_key": readings[0].request_key,
        })
    return rows
