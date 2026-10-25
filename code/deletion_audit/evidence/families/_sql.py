"""Shared helpers for the SQL families."""
from __future__ import annotations

import re

from ..model import RawRecord
from ..sqlsafe import SqlTable, load_tables, raw_value
from ._common import Content

SCOPE_TABLE = "snapshot_scope"
REPLICA_COLUMNS = ("resource_id", "origin_system", "collection_name", "record_json", "updated_at")
ROW_TIME_COLUMNS = ("updated_at", "indexed_at")
_REPLICA_DDL = re.compile(r"CREATE\s+TABLE[^;]*\brecord_json\b", re.IGNORECASE)


def has_replica_layout(content: Content) -> bool:
    """True when a CREATE TABLE statement declares a ``record_json`` column."""
    return bool(_REPLICA_DDL.search(content.text or ""))


def load(content: Content) -> tuple[SqlTable, ...]:
    """Run the file through the SQL sandbox."""
    return load_tables(content.text or "")


def row_fields(table: SqlTable, values: tuple[object, ...]) -> dict[str, str]:
    """A row's columns as raw strings."""
    return {col: raw_value(val) for col, val in zip(table.columns, values, strict=False)}


def row_time(fields: dict[str, str]) -> str | None:
    """The row's own time column, when it has one."""
    for column in ROW_TIME_COLUMNS:
        value = fields.get(column)
        if value is not None and value != "null":
            return value
    return None


def typed_row(table: SqlTable, rowid: int, values: tuple[object, ...]) -> RawRecord:
    """A row of a plain typed table as a RawRecord."""
    fields = row_fields(table, values)
    return RawRecord(
        locator_kind="sql_row",
        ref=f"{table.name}#rowid={rowid}",
        fields=fields,
        record_time=row_time(fields),
        trace_id=None,
        source_system=None,
        container=table.name,
        event=table.name,
    )
