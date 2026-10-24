"""Family ``cloud_runtime_log``:
``TS requestId=... level=... function=... message="escaped key=value pairs"``.

``requestId`` is read as the trace ID and ``function`` as the service. The pairs inside
``message`` are unescaped and kept as fields; an inner key that repeats an outer one is
kept as ``message.<key>``.
"""
from __future__ import annotations

from ..model import RawFile
from ._common import Content
from ._logs import LineParts, parse_kv, parse_log, sniff_dialect

NAME = "cloud_runtime_log"


def sniff(content: Content) -> bool:
    """Every line is a timestamped cloud-runtime line."""
    return sniff_dialect(content, "cloud_runtime")


def _body(body: str, line_no: int) -> LineParts:
    """Parse the outer pairs, then the pairs inside ``message``."""
    outer = parse_kv(body, line_no)
    inner = parse_kv(outer.pop("message", ""), line_no)
    fields = dict(outer)
    for key, value in inner.items():
        fields["message." + key if key in fields else key] = value
    return LineParts(fields, outer.get("requestId"), outer.get("function"), inner.get("event"))


def parse(content: Content) -> RawFile:
    """One RawRecord per line."""
    return parse_log(content, _body)
