"""Family ``kv_log``: ``TS [LEVEL] key=value key="value" ...`` lines.

Header keys used: ``trace_id``, ``service``, ``event``. Every pair is kept in ``fields``.
"""
from __future__ import annotations

from ..model import RawFile
from ._common import Content
from ._logs import LineParts, parse_kv, parse_log, sniff_dialect, strip_level

NAME = "kv_log"


def sniff(content: Content) -> bool:
    """Every line is a timestamped key=value line."""
    return sniff_dialect(content, "kv")


def _body(body: str, line_no: int) -> LineParts:
    """Parse one key=value body, with an optional bare level token."""
    level, rest = strip_level(body)
    fields = parse_kv(rest, line_no)
    if level is not None:
        if "level" in fields:
            fields["level_token"] = level
        else:
            fields = {"level": level, **fields}
    return LineParts(fields, fields.get("trace_id"), fields.get("service"), fields.get("event"))


def parse(content: Content) -> RawFile:
    """One RawRecord per line."""
    return parse_log(content, _body)
