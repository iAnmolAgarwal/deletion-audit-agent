"""Family ``pipe_handover``: a text report whose rows are
``- TIME | system | resource_id | record_type | result | subject_reference``.

Lines that do not start with ``- `` are report prose and are not records.
"""
from __future__ import annotations

import re

from ..model import ParseError, RawFile, RawRecord
from ._common import Content

NAME = "pipe_handover"
COLUMNS = ("recorded_at", "system", "resource_id", "record_type", "result", "subject_reference")
_ROW = re.compile(r"^- \d{4}-\d{2}-\d{2}T\S+ \|")
_TS_START = re.compile(r"^\d{4}-\d{2}-\d{2}T")


def sniff(content: Content) -> bool:
    """A text file with at least one handover row and no timestamp-led (log) lines."""
    if content.text is None or content.json is not None or content.sql_tables:
        return False
    if any(_TS_START.match(line) for line in content.lines):
        return False
    return any(_ROW.match(line) for line in content.lines)


def parse(content: Content) -> RawFile:
    """One RawRecord per ``- `` row; a row with the wrong column count is a ParseError."""
    records: list[RawRecord] = []
    for index, line in enumerate(content.lines, start=1):
        if not line.startswith("- "):
            continue
        parts = [p.strip() for p in line[2:].split("|")]
        if len(parts) != len(COLUMNS):
            raise ParseError(f"line {index}: expected {len(COLUMNS)} columns")
        fields = dict(zip(COLUMNS, parts))
        records.append(RawRecord(
            locator_kind="line",
            ref=f"L{index}",
            fields=fields,
            record_time=fields["recorded_at"],
            trace_id=None,
            source_system=fields["system"],
            container=None,
            event=fields["record_type"],
        ))
    return RawFile(records=tuple(records))
