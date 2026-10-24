"""Family ``service_resource_export``: ``{"service_exports": {service: {collection: [row]}}}``.

Each row is one record. Its time is the row's ``observed_at``; nested objects (``profile``,
``hits.documents[i]``) are flattened into dotted fields.
"""
from __future__ import annotations

from ..model import RawFile, RawRecord
from ._common import Content, flatten, optional_str, require_dict, require_list

NAME = "service_resource_export"


def sniff(content: Content) -> bool:
    """A JSON object whose ``service_exports`` member is an object."""
    doc = content.json
    return isinstance(doc, dict) and isinstance(doc.get("service_exports"), dict)


def parse(content: Content) -> RawFile:
    """One RawRecord per row, in document order."""
    exports = require_dict(content.json["service_exports"], "$.service_exports")
    records: list[RawRecord] = []
    for service, collections in exports.items():
        where = f"$.service_exports.{service}"
        for collection, rows in require_dict(collections, where).items():
            path = f"{where}.{collection}"
            for index, row in enumerate(require_list(rows, path)):
                row_path = f"{path}[{index}]"
                row = require_dict(row, row_path)
                records.append(RawRecord(
                    locator_kind="json_path",
                    ref=row_path,
                    fields=flatten(row),
                    record_time=optional_str(row.get("observed_at")),
                    trace_id=None,
                    source_system=service,
                    container=collection,
                    event=collection,
                ))
    return RawFile(records=tuple(records))
