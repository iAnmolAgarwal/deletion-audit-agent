"""Family ``snapshot_bundle``: ``{"snapshots": [{captured_at, data_store, collection,
records: [...]}]}``.

Every snapshot is a collection exported in full, so each one is declared as a
``full_collection`` scope, an empty collection included. A record's time is its own
``recorded_at`` when it has one, else its snapshot's ``captured_at``.
"""
from __future__ import annotations

from typing import Any

from ..model import ParseError, RawFile, RawRecord, RawScope
from ._common import Content, flatten, optional_str, require_dict, require_list

NAME = "snapshot_bundle"


def sniff(content: Content) -> bool:
    """A JSON object whose ``snapshots`` member is an array."""
    doc = content.json
    return isinstance(doc, dict) and isinstance(doc.get("snapshots"), list)


def _snapshot_header(snap: dict[str, Any], where: str) -> tuple[str, str, str]:
    """The snapshot's captured_at, data_store and collection, all required strings."""
    values = []
    for key in ("captured_at", "data_store", "collection"):
        value = snap.get(key)
        if not isinstance(value, str) or not value:
            raise ParseError(f"{where}: missing {key}")
        values.append(value)
    return values[0], values[1], values[2]


def parse(content: Content) -> RawFile:
    """One RawScope per snapshot and one RawRecord per record."""
    scopes: list[RawScope] = []
    records: list[RawRecord] = []
    for s_index, snap in enumerate(require_list(content.json["snapshots"], "$.snapshots")):
        where = f"$.snapshots[{s_index}]"
        snap = require_dict(snap, where)
        captured_at, data_store, collection = _snapshot_header(snap, where)
        scopes.append(RawScope("json_path", where, (data_store,), captured_at,
                               "full_collection", collection))
        for r_index, row in enumerate(require_list(snap.get("records"), where + ".records")):
            row_path = f"{where}.records[{r_index}]"
            row = require_dict(row, row_path)
            records.append(RawRecord(
                locator_kind="json_path",
                ref=row_path,
                fields=flatten(row),
                record_time=optional_str(row.get("recorded_at")) or captured_at,
                trace_id=None,
                source_system=data_store,
                container=collection,
                event=optional_str(row.get("record_type")) or collection,
                scope_index=s_index,
            ))
    return RawFile(records=tuple(records), scopes=tuple(scopes))
