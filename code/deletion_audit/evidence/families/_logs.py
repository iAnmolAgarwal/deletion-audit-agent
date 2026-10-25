"""Shared syntax for the log families.

Every log line starts with an ISO-8601 timestamp, then a body in one of six dialects.
:func:`dialect_of` names the dialect of one body; a log family matches a file only when
every non-blank line is timestamped and written in that family's dialect.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from ..model import ParseError, RawFile, RawRecord
from ._common import Content

TS_LINE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2}))\s+(.*)$"
)
KV_PAIR = re.compile(r'([A-Za-z_][A-Za-z0-9_.]*)=("(?:[^"\\]|\\.)*"|[^\s"]*)')
_LEVEL_TOKEN = re.compile(r"^(DEBUG|INFO|NOTICE|WARN|WARNING|ERROR|CRITICAL|FATAL|TRACE)\s+")
SYSLOG_BODY = re.compile(r"^<(\d{1,3})>1 (\S+) (\S+) (\S+) (\S+) (\S+) ?(.*)$")
BRACKET_BODY = re.compile(r"^\[([^\]]*)\] \[([^\]]*)\] \[([^\]]*)\] ([A-Za-z0-9_.-]+):\s?(.*)$")
CLOUD_BODY = re.compile(r'^requestId=\S+ level=\S+ function=\S+ message="')
KV_BODY = re.compile(r"^(?:[A-Z]+\s+)?[A-Za-z_][A-Za-z0-9_.]*=")


def dialect_of(body: str) -> str | None:
    """Name the dialect of one line body (the text after the timestamp)."""
    if body.startswith("{"):
        return "json_line"
    if SYSLOG_BODY.match(body):
        return "syslog"
    if BRACKET_BODY.match(body):
        return "bracketed"
    if body.startswith("| "):
        return "pipe"
    if CLOUD_BODY.match(body):
        return "cloud_runtime"
    if KV_BODY.match(body):
        return "kv"
    return None


def file_dialects(content: Content) -> set[str | None] | None:
    """Dialects of every non-blank line, or None if a line has no leading timestamp."""
    if content.text is None or content.json is not None:
        return None
    found: set[str | None] = set()
    for line in content.lines:
        if not line.strip():
            continue
        match = TS_LINE.match(line)
        if not match:
            return None
        found.add(dialect_of(match.group(2)))
    return found or None


def sniff_dialect(content: Content, dialect: str) -> bool:
    """True when every non-blank line is timestamped and written in ``dialect``."""
    return file_dialects(content) == {dialect}


def parse_kv(text: str, line_no: int) -> dict[str, str]:
    """Parse ``key=value`` / ``key="value"`` pairs, unescaping quoted values.

    Raises ParseError if any non-space text is left over or a key repeats.
    """
    out: dict[str, str] = {}
    leftover = KV_PAIR.sub("", text)
    if leftover.strip():
        raise ParseError(f"line {line_no}: text outside key=value pairs")
    for key, value in KV_PAIR.findall(text):
        if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
            value = re.sub(r'\\(.)', r"\1", value[1:-1])
        if key in out:
            raise ParseError(f"line {line_no}: repeated key {key}")
        out[key] = value
    return out


def strip_level(body: str) -> tuple[str | None, str]:
    """Split a leading bare level token (``INFO service=...``) off a kv body."""
    match = _LEVEL_TOKEN.match(body)
    if match:
        return match.group(1), body[match.end():]
    return None, body


@dataclass(frozen=True)
class LineParts:
    """What a dialect parser extracts from one line body."""

    fields: dict[str, str]
    trace_id: str | None
    service: str | None
    event: str | None


BodyParser = Callable[[str, int], LineParts]


def parse_log(content: Content, body_parser: BodyParser) -> RawFile:
    """Parse every timestamped line with ``body_parser``; one RawRecord per line."""
    records: list[RawRecord] = []
    for index, line in enumerate(content.lines, start=1):
        if not line.strip():
            continue
        match = TS_LINE.match(line)
        if not match:
            raise ParseError(f"line {index}: no leading timestamp")
        parts = body_parser(match.group(2), index)
        records.append(RawRecord(
            locator_kind="line",
            ref=f"L{index}",
            fields=parts.fields,
            record_time=match.group(1),
            trace_id=parts.trace_id or None,
            source_system=parts.service or None,
            container=None,
            event=parts.event or None,
        ))
    return RawFile(records=tuple(records))


def merge_header(header: dict[str, str], kv: dict[str, str], line_no: int) -> dict[str, str]:
    """Combine dialect header fields with the line's kv pairs; a clash is a ParseError."""
    clash = set(header) & set(kv)
    if clash:
        raise ParseError(f"line {line_no}: header field repeated in body: {sorted(clash)[0]}")
    return {**header, **kv}
