"""Family ``sql_replica_topology``: SQL whose tables hold
``(resource_id, origin_system, collection_name, record_json, updated_at)`` rows
(primary, read, reporting, regional and failover replicas).

``record_json`` is decoded and flattened as ``record_json.<field>``; the other columns are
kept under their own names. No scope is declared: the files state no coverage.
"""
from __future__ import annotations

import json

from ..model import ParseError, RawFile, RawRecord
from ..sqlsafe import SqlTable
from ._common import Content, flatten
from ._sql import SCOPE_TABLE, has_replica_layout, load, row_fields, row_time, typed_row

NAME = "sql_replica_topology"


def sniff(content: Content) -> bool:
    """SQL text with a ``record_json`` column and no ``snapshot_scope`` table."""
    tables = content.sql_tables
    return bool(tables) and SCOPE_TABLE not in tables and has_replica_layout(content)


def _replica_row(table: SqlTable, rowid: int, values: tuple[object, ...]) -> RawRecord:
    """Decode one replica row."""
    ref = f"{table.name}#rowid={rowid}"
    columns = row_fields(table, values)
    try:
        document = json.loads(columns.pop("record_json"))
    except json.JSONDecodeError:
        raise ParseError(f"{ref}: record_json is not valid JSON") from None
    if not isinstance(document, dict):
        raise ParseError(f"{ref}: record_json is not an object")
    fields = {**columns, **flatten(document, "record_json")}
    return RawRecord(
        locator_kind="sql_row",
        ref=ref,
        fields=fields,
        record_time=row_time(columns),
        trace_id=None,
        source_system=columns.get("origin_system"),
        container=columns.get("collection_name"),
        event=table.name,
    )


def parse(content: Content) -> RawFile:
    """One RawRecord per row of every table."""
    records: list[RawRecord] = []
    for table in load(content):
        replica = "record_json" in table.columns
        for rowid, values in table.rows:
            records.append(_replica_row(table, rowid, values) if replica
                           else typed_row(table, rowid, values))
    return RawFile(records=tuple(records))
