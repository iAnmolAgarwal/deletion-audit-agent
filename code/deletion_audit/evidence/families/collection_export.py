"""Family ``collection_export``: ``{"captured_at", "collection", "records": [...]}``.

The file exports one named collection at one time, so it declares one
``full_collection`` scope. Each record's time is the collection's ``captured_at``.
"""
from __future__ import annotations

from ..model import ParseError, RawFile, RawRecord, RawScope
from ._common import Content, flatten, require_dict, require_list

NAME = "collection_export"


def sniff(content: Content) -> bool:
    """A JSON object with a string ``collection`` and a ``records`` array."""
    doc = content.json
    return (isinstance(doc, dict) and isinstance(doc.get("collection"), str)
            and isinstance(doc.get("records"), list))


def parse(content: Content) -> RawFile:
    """One RawScope for the collection and one RawRecord per record."""
    doc = content.json
    captured_at = doc.get("captured_at")
    if not isinstance(captured_at, str) or not captured_at:
        raise ParseError("$: missing captured_at")
    collection = doc["collection"]
    scope = RawScope("json_path", "$", (collection,), captured_at, "full_collection", collection)
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
            scope_index=0,
        ))
    return RawFile(records=tuple(records), scopes=(scope,))
