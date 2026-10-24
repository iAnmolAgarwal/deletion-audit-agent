"""Family ``syslog_log``: RFC 5424 ``TS <PRI>1 HOST APP PROCID MSGID SD key="value" ...``.

APP is read as the service and PROCID as the trace ID.
"""
from __future__ import annotations

from ..model import ParseError, RawFile
from ._common import Content
from ._logs import SYSLOG_BODY, LineParts, merge_header, parse_kv, parse_log, sniff_dialect

NAME = "syslog_log"


def sniff(content: Content) -> bool:
    """Every line is a timestamped RFC 5424 line."""
    return sniff_dialect(content, "syslog")


def _body(body: str, line_no: int) -> LineParts:
    """Parse the syslog header and the kv message."""
    match = SYSLOG_BODY.match(body)
    if match is None:
        raise ParseError(f"line {line_no}: not a RFC 5424 line")
    pri, host, app, procid, msgid, sdata, message = match.groups()
    header = {"pri": pri, "host": host, "app": app, "procid": procid,
              "msgid": msgid, "structured_data": sdata}
    fields = merge_header(header, parse_kv(message, line_no), line_no)
    return LineParts(fields, procid, app, fields.get("event"))


def parse(content: Content) -> RawFile:
    """One RawRecord per line."""
    return parse_log(content, _body)
