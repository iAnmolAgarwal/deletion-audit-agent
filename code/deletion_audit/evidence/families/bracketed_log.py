"""Family ``bracketed_log``: ``TS [LEVEL] [service] [trace] event: key="value" ...`` lines."""
from __future__ import annotations

from ..model import ParseError, RawFile
from ._common import Content
from ._logs import BRACKET_BODY, LineParts, merge_header, parse_kv, parse_log, sniff_dialect

NAME = "bracketed_log"


def sniff(content: Content) -> bool:
    """Every line is a timestamped bracketed line."""
    return sniff_dialect(content, "bracketed")


def _body(body: str, line_no: int) -> LineParts:
    """Parse the three bracketed header fields, the event name and the kv tail."""
    match = BRACKET_BODY.match(body)
    if match is None:
        raise ParseError(f"line {line_no}: not a bracketed line")
    level, service, trace, event, tail = match.groups()
    header = {"level": level, "service": service, "trace_id": trace, "event": event}
    fields = merge_header(header, parse_kv(tail, line_no), line_no)
    return LineParts(fields, trace, service, event)


def parse(content: Content) -> RawFile:
    """One RawRecord per line."""
    return parse_log(content, _body)
