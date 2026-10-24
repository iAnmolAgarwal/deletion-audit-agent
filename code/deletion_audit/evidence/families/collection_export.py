"""Family ``collection_export``: ``{"captured_at", "collection", "records": [...]}``.

A plain export names its source and collection but never states that it holds every
record, so it declares no scope and cannot prove absence (developer ruling T50). Only a
file that declares completeness does: a SQL ``snapshot_scope`` row, or a snapshot bundle
entry naming its data store. Each record's time is the collection's ``captured_at``.
"""
from __future__ import annotations

from ..model import ParseError, RawFile, RawRecord
from ._common import Content, flatten, require_dict, require_list

NAME = "collection_export"


def sniff(content: Content) -> bool:
    """A JSON object with a string ``collection`` and a ``records`` array."""
    doc = content.json
    return (isinstance(doc, dict) and isinstance(doc.get("collection"), str)
            and isinstance(doc.get("records"), list))


def parse(content: Content) -> RawFile:
    """One RawRecord per record, and no scope."""
    doc = content.json
    captured_at = doc.get("captured_at")
    if not isinstance(captured_at, str) or not captured_at:
        raise ParseError("$: missing captured_at")
    collection = doc["collection"]
    records: list[RawRecord] = []
    for index, row in enumerate(require_list(doc["records"], "$.records")):
        path = f"$.records[{index}]"
        records.append(RawRecord(
            locator_kind="json_path",
            ref=path,
            fields=flatten(require_dict(row, path)),
            record_time=captured_at,
            trace_id=None,
            source_system=None,
            container=collection,
            event=collection,
            scope_index=None,
        ))
    return RawFile(records=tuple(records), scopes=())
