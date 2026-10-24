"""Family ``sql_typed_tables``: SQL with plain typed tables only (no ``snapshot_scope``
table, no ``record_json`` column), e.g. ``customer_profiles_primary``.

Rows are records timed by ``updated_at`` or ``indexed_at``. No scope is declared.
"""
from __future__ import annotations

from ..model import RawFile
from ._common import Content
from ._sql import SCOPE_TABLE, has_replica_layout, load, typed_row

NAME = "sql_typed_tables"


def sniff(content: Content) -> bool:
    """SQL text with tables but neither a scope table nor the replica layout."""
    tables = content.sql_tables
    return bool(tables) and SCOPE_TABLE not in tables and not has_replica_layout(content)


def parse(content: Content) -> RawFile:
    """One RawRecord per row of every table."""
    records = [typed_row(table, rowid, values)
               for table in load(content) for rowid, values in table.rows]
    return RawFile(records=tuple(records))
