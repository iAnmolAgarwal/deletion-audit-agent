"""Family detection from file content.

Every family module's ``sniff`` runs on the file's content; dispatch needs exactly one
match. File names and the manifest ``origin`` are never consulted.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import ModuleType
from typing import Sequence

from .families import (
    bracketed_log,
    cloud_runtime_log,
    collection_export,
    flat_record_list,
    image,
    json_line_log,
    kv_log,
    pdf_text,
    pipe_handover,
    pipe_log,
    service_resource_export,
    snapshot_bundle,
    sql_inventory,
    sql_replica_topology,
    sql_typed_tables,
    syslog_log,
)
from .families._common import Content
from .model import ParseStatus

FAMILIES: tuple[ModuleType, ...] = (
    kv_log, bracketed_log, syslog_log, pipe_log, cloud_runtime_log, json_line_log,
    service_resource_export, snapshot_bundle, flat_record_list, collection_export,
    pipe_handover, sql_inventory, sql_replica_topology, sql_typed_tables, pdf_text, image,
)


@dataclass(frozen=True)
class Detection:
    """Outcome of family detection."""

    status: ParseStatus          # "OK", "UNKNOWN_FAMILY" or "AMBIGUOUS_FAMILY"
    family: ModuleType | None
    detail: str | None


def detect(content: Content, families: Sequence[ModuleType] = FAMILIES) -> Detection:
    """Run every sniffer; return the single match, or why there is none."""
    matches = [family for family in families if family.sniff(content)]
    if len(matches) == 1:
        return Detection("OK", matches[0], None)
    if not matches:
        return Detection("UNKNOWN_FAMILY", None, "no family sniffer matched the content")
    names = ", ".join(sorted(f.NAME for f in matches))
    return Detection("AMBIGUOUS_FAMILY", None, f"several family sniffers matched: {names}")


def family_names(families: Sequence[ModuleType] = FAMILIES) -> tuple[str, ...]:
    """Names of the registered families."""
    return tuple(f.NAME for f in families)
