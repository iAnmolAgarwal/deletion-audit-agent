"""Family ``pipe_log``: ``TS | LEVEL | service | trace | event | key="value" ...`` lines."""
from __future__ import annotations

from ..model import ParseError, RawFile
from ._common import Content
from ._logs import LineParts, merge_header, parse_kv, parse_log, sniff_dialect

NAME = "pipe_log"


def sniff(content: Content) -> bool:
    """Every line is a timestamped pipe-delimited line."""
    return sniff_dialect(content, "pipe")


def _body(body: str, line_no: int) -> LineParts:
    """Split the four header columns off the kv tail."""
    parts = body[2:].split(" | ", 4)
    if len(parts) != 5:
        raise ParseError(f"line {line_no}: expected 5 pipe-delimited columns")
    level, service, trace, event, tail = (p.strip() for p in parts)
    header = {"level": level, "service": service, "trace_id": trace, "event": event}
    fields = merge_header(header, parse_kv(tail, line_no), line_no)
    return LineParts(fields, trace, service, event)


def parse(content: Content) -> RawFile:
    """One RawRecord per line."""
    return parse_log(content, _body)
