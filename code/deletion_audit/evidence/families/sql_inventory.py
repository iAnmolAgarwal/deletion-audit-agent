"""Family ``sql_inventory``: SQL with a ``snapshot_scope(origin_system, captured_at)``
table and typed per-system tables.

Each ``snapshot_scope`` row is declared as a ``sql_snapshot_scope`` scope; rows of the
other tables are records, timed by their ``updated_at`` column.
"""
from __future__ import annotations

from ..model import ParseError, RawFile, RawRecord, RawScope
from ._common import Content
from ._sql import SCOPE_TABLE, load, row_fields, typed_row

NAME = "sql_inventory"


def sniff(content: Content) -> bool:
    """SQL text that creates a ``snapshot_scope`` table."""
    return SCOPE_TABLE in content.sql_tables


def parse(content: Content) -> RawFile:
    """Scopes from ``snapshot_scope``; one RawRecord per row of every other table."""
    scopes: list[RawScope] = []
    records: list[RawRecord] = []
    for table in load(content):
        if table.name.lower() == SCOPE_TABLE:
            for rowid, values in table.rows:
                fields = row_fields(table, values)
                if "origin_system" not in fields or "captured_at" not in fields:
                    raise ParseError(f"{SCOPE_TABLE}: expected origin_system and captured_at")
                scopes.append(RawScope("sql_row", f"{table.name}#rowid={rowid}",
                                       (fields["origin_system"],), fields["captured_at"],
                                       "sql_snapshot_scope", None))
            continue
        records.extend(typed_row(table, rowid, values) for rowid, values in table.rows)
    return RawFile(records=tuple(records), scopes=tuple(scopes))
