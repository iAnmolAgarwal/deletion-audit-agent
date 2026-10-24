"""Family ``json_line_log``: ``TS {"severity": ..., "service": ..., "trace_id": ...}``."""
from __future__ import annotations

import json

from ..model import ParseError, RawFile
from ._common import Content, flatten
from ._logs import LineParts, parse_log, sniff_dialect

NAME = "json_line_log"


def sniff(content: Content) -> bool:
    """Every line is a timestamp followed by a JSON object."""
    return sniff_dialect(content, "json_line")


def _body(body: str, line_no: int) -> LineParts:
    """Parse the JSON object and flatten it."""
    try:
        value = json.loads(body)
    except json.JSONDecodeError:
        raise ParseError(f"line {line_no}: invalid JSON object") from None
    if not isinstance(value, dict):
        raise ParseError(f"line {line_no}: expected a JSON object")
    fields = flatten(value)
    service = fields.get("service") or fields.get("logger")
    return LineParts(fields, fields.get("trace_id"), service, fields.get("event"))


def parse(content: Content) -> RawFile:
    """One RawRecord per line."""
    return parse_log(content, _body)
