"""Family ``flat_record_list``: ``{"records": [{recorded_at, system, resource_id,
record_type, result, subject_reference}]}`` with no ``collection`` member.

No scope is declared: the list states check results, not a collection exported in full.
"""
from __future__ import annotations

from ..model import RawFile, RawRecord
from ._common import Content, flatten, optional_str, require_dict

NAME = "flat_record_list"
_REQUIRED = ("record_type", "resource_id", "system")


def sniff(content: Content) -> bool:
    """A JSON object with a ``records`` array of check results and no collection,
    snapshot or service-export member."""
    doc = content.json
    if not isinstance(doc, dict) or not isinstance(doc.get("records"), list):
        return False
    if any(key in doc for key in ("collection", "snapshots", "service_exports")):
        return False
    return all(isinstance(r, dict) and all(k in r for k in _REQUIRED) for r in doc["records"])


def parse(content: Content) -> RawFile:
    """One RawRecord per list item."""
    records: list[RawRecord] = []
    for index, row in enumerate(content.json["records"]):
        path = f"$.records[{index}]"
        row = require_dict(row, path)
        records.append(RawRecord(
            locator_kind="json_path",
            ref=path,
            fields=flatten(row),
            record_time=optional_str(row.get("recorded_at")),
            trace_id=None,
            source_system=optional_str(row.get("system")),
            container=None,
            event=optional_str(row.get("record_type")),
        ))
    return RawFile(records=tuple(records))
