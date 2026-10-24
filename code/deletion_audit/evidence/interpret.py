"""The single interpretation point: :class:`RawRecord` -> :class:`Observation`.

This module holds, in one place each:

* the time normalizer (:func:`normalize_time`);
* the identifier classifier and normalizer (:func:`classify_identifier`,
  :func:`normalize_identifier`, :func:`make_identifier`);
* the system map (:data:`SYSTEM_MAP`, :data:`RESOURCE_PREFIX_SYSTEM`);
* the rule that attaches declared scopes to observations.

``system_id`` is derived only from names that appear in the evidence itself (the record's
``system`` field, the service / data_store / origin_system that wrote it, its table or
collection, or its resource-ID prefix). Nothing here reads ``system_activity.csv``.
"""
from __future__ import annotations

import datetime as dt
import re
from types import MappingProxyType
from typing import Iterable, Mapping

from .model import (
    FileRef,
    Identifier,
    IdKind,
    Locator,
    Observation,
    RawFile,
    RawRecord,
    RawScope,
    SnapshotScope,
)

# --------------------------------------------------------------------------- time
_TIME_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(\.\d+)?(Z|[+-]\d{2}:?\d{2})$"
)


def normalize_time(raw: str) -> str:
    """Return ``raw`` as ISO-8601 UTC ending in ``Z``, seconds and fractions kept as written.

    An explicit offset is converted to UTC. A time with no zone designator is rejected,
    because guessing its zone could move it. Raises ``ValueError`` on anything else.
    """
    text = raw.strip()
    match = _TIME_RE.match(text)
    if not match:
        raise ValueError(f"unrecognized timestamp format (length {len(text)})")
    year, month, day, hour, minute, second, fraction, zone = match.groups()
    moment = dt.datetime(int(year), int(month), int(day), int(hour), int(minute), int(second))
    if zone != "Z":
        sign = 1 if zone[0] == "+" else -1
        digits = zone[1:].replace(":", "")
        offset = dt.timedelta(hours=int(digits[:2]), minutes=int(digits[2:]))
        moment = moment - sign * offset
    return moment.strftime("%Y-%m-%dT%H:%M:%S") + (fraction or "") + "Z"


# --------------------------------------------------------------------------- systems
CANONICAL_SYSTEMS: frozenset[str] = frozenset({
    "account_service", "search_service", "analytics_platform", "support_platform",
    "export_service", "integration_service", "backup_service", "security_service",
    "identity_service", "legal_service", "marketing_platform",
})

SYSTEM_MAP: Mapping[str, str] = MappingProxyType({
    **{name: name for name in CANONICAL_SYSTEMS},
    # tables of the inventory SQL family
    "customer_profiles": "account_service",
    "customer_search_documents": "search_service",
    "customer_analytics_profiles": "analytics_platform",
    "support_records": "support_platform",
    "customer_exports": "export_service",
    "connector_subscriptions": "integration_service",
    "backup_restore_entries": "backup_service",
    "security_audit_records": "security_service",
    # tables of the hand-built SQL files
    "customer_profiles_primary": "account_service",
    "customer_profiles_failover_replica": "account_service",
    "search_documents_primary": "search_service",
    # collection names used in bundles, replicas and collection exports
    "customer_analytics_reports": "analytics_platform",
    "backup_catalog": "backup_service",
    "customer_export_jobs": "export_service",
    "connector_configurations": "integration_service",
    "security_audit_events": "security_service",
    "support_conversations": "support_platform",
    "ticket_attachments": "support_platform",
    "deleted_customer_references": "identity_service",
    "retained_order_records": "legal_service",
})

RESOURCE_PREFIX_SYSTEM: tuple[tuple[str, str], ...] = (
    ("audit_record_", "security_service"),
    ("legal_hold_", "legal_service"),
    ("data_flow_", "integration_service"),
    ("tombstone_", "identity_service"),
    ("analytics_", "analytics_platform"),
    ("account_", "account_service"),
    ("support_", "support_platform"),
    ("search_", "search_service"),
    ("export_", "export_service"),
    ("backup_", "backup_service"),
)

RESOURCE_ID_IN_TEXT = re.compile(
    r"\b(?:" + "|".join(prefix for prefix, _ in RESOURCE_PREFIX_SYSTEM) + r")\d+\b"
)


def system_from_prefix(resource_id: str | None) -> str | None:
    """Map a resource ID to a system by its prefix, or None."""
    if not resource_id:
        return None
    for prefix, system in RESOURCE_PREFIX_SYSTEM:
        if resource_id.startswith(prefix) and resource_id[len(prefix):].isdigit():
            return system
    return None


def resolve_system(raw: RawRecord, resource_id: str | None) -> str | None:
    """Pick ``system_id``: the record's own ``system`` field, then the writing service or
    data store, then its table or collection, then the resource-ID prefix."""
    for name in (raw.fields.get("system"), raw.source_system, raw.container):
        if name and name in SYSTEM_MAP:
            return SYSTEM_MAP[name]
    return system_from_prefix(resource_id)


# --------------------------------------------------------------------------- identifiers
NULL_MARKERS: frozenset[str] = frozenset({"", "null", "none", "nil", "no direct identifier"})

RECORD_ID_FIELDS: frozenset[str] = frozenset({
    "email", "phone", "email_hash", "user_id", "customer_email", "customer_reference",
    "requester_email", "requester_phone", "owner_email", "owner_phone",
    "uploaded_by", "subject_selector", "matched_value",
    "full_name", "display_name", "name", "requester_name",
})
LOOKUP_ID_FIELDS: frozenset[str] = frozenset({
    "lookup_key", "match_key", "subject_key", "scan_key", "owner_key", "query", "lookup_value",
})
# Developer ruling T49: these fields take their role from the line. On a line or row that
# names a resource_id they are that resource's own key (a search hit's correlation_key is
# the key the hit is indexed under; a subject_ref is the record's subject). On a line with
# no resource_id they are a lookup key, which reaches a resource only through its trace.
LINE_ROLE_ID_FIELDS: frozenset[str] = frozenset({
    "correlation_key", "subject_ref", "subject_reference",
})
TEXT_FIELDS: tuple[str, ...] = ("message_text", "message_excerpt")
NAME_FIELDS: frozenset[str] = frozenset({"full_name", "display_name", "name", "requester_name"})
PHONE_FIELDS: frozenset[str] = frozenset({"phone", "requester_phone", "owner_phone"})

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
_USER_ID_RE = re.compile(r"^user_\d+$")
_HASH_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_PHONE_RE = re.compile(r"^\+?[\d\s().-]{7,}$")
EMAIL_IN_TEXT = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
USER_ID_IN_TEXT = re.compile(r"\buser_\d+\b")
PHONE_IN_TEXT = re.compile(r"\+\d[\d ()-]{5,}\d")
_INDEX_RE = re.compile(r"\[\d+\]")


def leaf_name(key: str) -> str:
    """Last segment of a flattened key: ``hits.documents[0].email`` -> ``email``."""
    return _INDEX_RE.sub("", key).rsplit(".", 1)[-1]


def is_null(raw: str | None) -> bool:
    """True for values that state the absence of a value."""
    return raw is None or raw.strip().lower() in NULL_MARKERS


def classify_identifier(leaf: str, raw: str) -> IdKind:
    """Kind of an identifier, from its field name first and its shape second."""
    value = raw.strip()
    if leaf == "email_hash":
        return "email_hash"
    if leaf in NAME_FIELDS:
        return "name"
    if leaf in PHONE_FIELDS:
        return "phone"
    if _EMAIL_RE.match(value):
        return "email"
    if _USER_ID_RE.match(value):
        return "user_id"
    if _HASH_RE.match(value):
        return "email_hash"
    if _PHONE_RE.match(value) and sum(ch.isdigit() for ch in value) >= 7:
        return "phone"
    if leaf == "subject_reference":
        return "subject_reference"
    return "other"


def normalize_identifier(kind: IdKind, raw: str) -> str:
    """The one identifier normalizer.

    email, email_hash and name: stripped and lower-cased (names also collapse inner
    whitespace); phone: its digits with a leading ``+``; every other kind: stripped.
    """
    value = raw.strip()
    if kind in ("email", "email_hash"):
        return value.lower()
    if kind == "phone":
        return "+" + "".join(ch for ch in value if ch.isdigit())
    if kind == "name":
        return " ".join(value.split()).lower()
    return value


def make_identifier(kind: IdKind, raw: str, field: str) -> Identifier:
    """Build an Identifier with its normalized value."""
    return Identifier(kind=kind, value=normalize_identifier(kind, raw), raw=raw, field=field)


def identifiers_in_text(text: str, field: str) -> list[Identifier]:
    """Emails, user IDs and +-prefixed phone numbers that appear in free text."""
    found: list[Identifier] = []
    for match in EMAIL_IN_TEXT.finditer(text):
        found.append(make_identifier("email", match.group(0), field))
    for match in USER_ID_IN_TEXT.finditer(text):
        found.append(make_identifier("user_id", match.group(0), field))
    for match in PHONE_IN_TEXT.finditer(text):
        found.append(make_identifier("phone", match.group(0), field))
    return found


def names_resource(fields: Mapping[str, str]) -> bool:
    """True when the record's own fields name a resource_id."""
    return not is_null(fields.get("resource_id"))


def split_identifiers(fields: Mapping[str, str]) -> tuple[list[Identifier], list[Identifier]]:
    """Return (record identifiers, lookup identifiers) found in one record's fields."""
    record: list[Identifier] = []
    lookup: list[Identifier] = []
    line_role = record if names_resource(fields) else lookup
    for key, raw in fields.items():
        leaf = leaf_name(key)
        if leaf in TEXT_FIELDS and not is_null(raw):
            record.extend(identifiers_in_text(raw, key))
            continue
        if is_null(raw):
            continue
        if leaf in RECORD_ID_FIELDS:
            record.append(make_identifier(classify_identifier(leaf, raw), raw, key))
        elif leaf in LOOKUP_ID_FIELDS:
            lookup.append(make_identifier(classify_identifier(leaf, raw), raw, key))
        elif leaf in LINE_ROLE_ID_FIELDS:
            line_role.append(make_identifier(classify_identifier(leaf, raw), raw, key))
    return record, lookup


def record_text(raw: RawRecord) -> str | None:
    """Free text of a record: the parser's text, else the first text field present."""
    if raw.text is not None:
        return raw.text
    for key, value in raw.fields.items():
        if leaf_name(key) in TEXT_FIELDS:
            return value
    return None


# --------------------------------------------------------------------------- scopes
def build_scope(ref: FileRef, raw: RawScope) -> SnapshotScope:
    """Interpret one declared scope."""
    systems = frozenset(SYSTEM_MAP.get(name, name) for name in raw.systems)
    as_of = normalize_time(raw.as_of) if raw.as_of is not None else None
    return SnapshotScope(
        file_id=ref.file_id,
        systems=systems,
        as_of=as_of,
        source=raw.source,
        collection=raw.collection,
        locator=Locator(ref.file_id, raw.locator_kind, raw.ref),
    )


def pick_scope(
    raw: RawRecord, system_id: str | None, scopes: tuple[SnapshotScope, ...]
) -> SnapshotScope | None:
    """The scope a record falls under: the one its parser named, else the file's
    ``snapshot_scope`` row for the record's system."""
    if raw.scope_index is not None:
        return scopes[raw.scope_index]
    for scope in scopes:
        if scope.source == "sql_snapshot_scope" and system_id in scope.systems:
            return scope
    return None


# --------------------------------------------------------------------------- records
def _trace_lookups(records: Iterable[RawRecord]) -> dict[str, list[Identifier]]:
    """Lookup identifiers of every trace_id, gathered over all records of one file."""
    by_trace: dict[str, list[Identifier]] = {}
    for raw in records:
        if raw.trace_id:
            _, lookup = split_identifiers(raw.fields)
            by_trace.setdefault(raw.trace_id, []).extend(lookup)
    return by_trace


def _resource_ids(raw: RawRecord, text: str | None) -> list[str | None]:
    """Resource IDs an observation is made for: the record's ``resource_id`` field, or,
    for a PDF page, every resource ID named in its text (first appearance order)."""
    value = raw.fields.get("resource_id")
    if value is not None and not is_null(value):
        return [value]
    if raw.locator_kind == "pdf_page" and text:
        named = list(dict.fromkeys(m.group(0) for m in RESOURCE_ID_IN_TEXT.finditer(text)))
        return named or [None]
    return [None]


def _observations_for(
    ref: FileRef,
    family: str,
    raw: RawRecord,
    scopes: tuple[SnapshotScope, ...],
    trace_lookups: Mapping[str, list[Identifier]],
) -> list[Observation]:
    """Interpret one RawRecord. A record whose own fields carry no resource ID, no
    identifier and no text (for example a connection-pool or cache line) yields nothing;
    identifiers borrowed from its trace do not count for that test."""
    text = record_text(raw)
    record_ids, lookup_ids = split_identifiers(raw.fields)
    if raw.locator_kind == "pdf_page" and text:
        record_ids.extend(identifiers_in_text(text, "pdf_text"))
    resource_ids = _resource_ids(raw, text)
    if resource_ids == [None] and not record_ids and not lookup_ids and text is None:
        return []
    if raw.trace_id:
        lookup_ids.extend(trace_lookups.get(raw.trace_id, ()))
    record_time = normalize_time(raw.record_time) if raw.record_time is not None else None
    attrs = MappingProxyType(dict(raw.fields))
    out: list[Observation] = []
    for resource_id in resource_ids:
        system_id = resolve_system(raw, resource_id)
        out.append(Observation(
            file_id=ref.file_id,
            family=family,
            locator=Locator(ref.file_id, raw.locator_kind, raw.ref),
            captured_at=ref.captured_at,
            record_time=record_time,
            system_id=system_id,
            resource_id=resource_id,
            record_identifiers=frozenset(record_ids),
            lookup_identifiers=frozenset(lookup_ids),
            trace_id=raw.trace_id,
            scope=pick_scope(raw, system_id, scopes),
            event=raw.event,
            attrs=attrs,
            text=text,
        ))
    return out


def interpret_file(
    ref: FileRef, family: str, raw_file: RawFile
) -> tuple[tuple[Observation, ...], tuple[SnapshotScope, ...]]:
    """Interpret every record and scope of one file, keeping the parser's order."""
    scopes = tuple(build_scope(ref, raw) for raw in raw_file.scopes)
    trace_lookups = _trace_lookups(raw_file.records)
    observations: list[Observation] = []
    for raw in raw_file.records:
        observations.extend(_observations_for(ref, family, raw, scopes, trace_lookups))
    return tuple(observations), scopes
