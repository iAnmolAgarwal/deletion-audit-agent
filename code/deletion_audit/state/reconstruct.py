"""State of one resource at ``audit_at``.

Rules, each with its basis:

* **R5**: nothing after ``audit_at`` decides state (DEV: a post-audit recreation is ignored).
* **R6 latest wins**: the latest observation at or before ``audit_at``, over every file, decides;
  observations at the same time that disagree resolve to the violating state for the record's
  category (research/15 R6; "any violation ever seen" loses one DEV case).
* **T54 absence by omission**: a file that declares completeness for the record's system (a SQL
  ``snapshot_scope`` row, or a snapshot-bundle entry naming its data store, T50) and does not
  list the record is an ABSENT observation at the scope's time, when the file was captured at or
  before ``audit_at``. Limits (the tested ``sql_strict`` form, ``g2f2-g2f2_h3_omission-0242``):
  a scope never rules out a record that has a replica copy, and a SQL ``support_records`` table
  (messages) never covers an attachment. A bundle snapshot covers only its own collection type.
  A plain export declares nothing and proves nothing (T50).
* **R8 default**: an account with no observation is ABSENT (9/9 DEV accounts); any other record
  with no observation has no state, and gets no step.
* **T8**: ``depends_on`` names the unparsed files a state could not be settled without.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from .. import timeutil
from ..discovery.obstime import ObsTime, at_or_before, observation_time
from ..evidence.model import EvidenceIndex, Locator, Observation, SnapshotScope
from ..identity.resolve import IdentifierSet
from .observe import is_attachment_listing, observation_state

StateBasis = Literal[
    "latest_observation", "omission_in_declared_scope", "default_absent", "image_extraction", "no_state"
]

#: Collection type a bundle snapshot must be for its omission to cover a record of a system.
#: Basis: G2 H3 ``json_*`` forms (COLL_OF); support: messages vs attachments are separate collections.
BUNDLE_COLLECTION_OF: Mapping[str, str] = {
    "account_service": "customer_profiles",
    "search_service": "customer_search_documents",
    "analytics_platform": "customer_analytics_reports",
    "backup_service": "backup_catalog",
    "export_service": "customer_export_jobs",
    "integration_service": "connector_configurations",
    "security_service": "security_audit_events",
    "identity_service": "deleted_customer_references",
}
SUPPORT_MESSAGE_COLLECTION = "support_conversations"
SUPPORT_ATTACHMENT_COLLECTION = "ticket_attachments"
SQL_SUPPORT_TABLE_COVERS_ATTACHMENTS = False  # T54: support_records lists messages only


@dataclass(frozen=True)
class ResourceKey:
    """A record's identity in the output: its system and resource ID."""

    system_id: str
    resource_id: str


@dataclass(frozen=True)
class StateObservation:
    """One dated state reading of a resource: an evidence record, an alias hit or an omission."""

    value: str
    time: ObsTime
    file_id: str
    captured_at: str
    locator: Locator | None
    kind: Literal["record", "alias", "omission", "image"]


@dataclass(frozen=True)
class ResourceState:
    """A resource's state at ``audit_at`` and what decided it."""

    key: ResourceKey
    value: str | None
    basis: StateBasis
    deciding: Locator | None
    decided_at: str | None
    depends_on: frozenset[str] = field(default_factory=frozenset)
    time_basis: str | None = None  # T68: record_time | pdf_stated | captured_at
    readings: tuple[StateObservation, ...] = ()


def is_replica_copy(obs: Observation) -> bool:
    """A record seen in a replica capture (a replica-topology file, or a table named as a replica).

    Basis: T54 "a SQL inventory doesn't rule out replica copies" (the G2 ``sql_replica_aware`` form)."""
    return obs.family == "sql_replica_topology" or "replica" in (obs.event or "")


@dataclass(frozen=True)
class ScopeListing:
    """One declared scope and the resource IDs it lists for its system."""

    scope: SnapshotScope
    system_id: str
    listed: frozenset[str]
    captured_at: str
    sql: bool


def scope_listings(index: EvidenceIndex) -> tuple[ScopeListing, ...]:
    """Every (declared scope, system) with the records it lists, in manifest order (T50, T54)."""
    out: list[ScopeListing] = []
    for fp in index.files.values():
        if not fp.ok:
            continue
        captured = next((o.captured_at for o in fp.observations), None)
        for scope in fp.scopes:
            for system in sorted(scope.systems):
                listed = frozenset(
                    o.resource_id
                    for o in fp.observations
                    if o.scope == scope and o.resource_id and o.system_id == system
                )
                out.append(
                    ScopeListing(
                        scope, system, listed, captured or scope.as_of or "", scope.source == "sql_snapshot_scope"
                    )
                )
    return tuple(out)


def _covers(listing: ScopeListing, key: ResourceKey, is_attachment: bool) -> bool:
    """Whether a declared scope covers this record (module docstring)."""
    if listing.system_id != key.system_id:
        return False
    if listing.sql:
        return not (key.system_id == "support_platform" and is_attachment and not SQL_SUPPORT_TABLE_COVERS_ATTACHMENTS)
    if key.system_id == "support_platform":
        want = SUPPORT_ATTACHMENT_COLLECTION if is_attachment else SUPPORT_MESSAGE_COLLECTION
    else:
        want = BUNDLE_COLLECTION_OF.get(key.system_id, "")
    return listing.scope.collection == want


def omission_readings(
    key: ResourceKey, listings: Sequence[ScopeListing], file_captured: Mapping[str, str], is_attachment: bool
) -> tuple[StateObservation, ...]:
    """ABSENT readings from declared scopes that do not list the record (T54)."""
    out = []
    for lst in listings:
        if key.resource_id in lst.listed or not _covers(lst, key, is_attachment):
            continue
        when = lst.scope.as_of or file_captured.get(lst.scope.file_id, "")
        if not when:
            continue
        out.append(
            StateObservation(
                "ABSENT",
                ObsTime(when, "second", "record_time"),
                lst.scope.file_id,
                file_captured.get(lst.scope.file_id, when),
                lst.scope.locator,
                "omission",
            )
        )
    return tuple(out)


def record_readings(
    key: ResourceKey, observations: Sequence[Observation], person: IdentifierSet | None = None
) -> tuple[StateObservation, ...]:
    """State readings from the resource's own evidence records (``person``: T86 item 3)."""
    out = []
    for o in observations:
        value = observation_state(o, o.system_id or key.system_id, person)
        if value is None:
            continue
        kind: Literal["record", "image"] = "image" if o.locator.kind == "image" else "record"
        out.append(StateObservation(value, observation_time(o), o.file_id, o.captured_at, o.locator, kind))
    return tuple(out)


def state_at(
    key: ResourceKey,
    readings: Sequence[StateObservation],
    audit_at: str,
    *,
    violating: frozenset[str],
    default_absent: bool,
    depends_on: frozenset[str] = frozenset(),
) -> ResourceState:
    """Decide the state at ``audit_at`` from dated readings (module docstring).

    ``violating`` is the category's set of states that make a finding; it breaks same-time ties.
    """
    usable = [
        r
        for r in readings
        if r.time.value
        and at_or_before(r.time, audit_at)
        and (r.kind != "omission" or timeutil.le(r.captured_at, audit_at))
    ]
    if not usable:
        if default_absent and not depends_on:
            return ResourceState(key, "ABSENT", "default_absent", None, None, depends_on, None, ())
        return ResourceState(key, None, "no_state", None, None, depends_on, None, ())
    latest = max(timeutil.parse(r.time.value) for r in usable)
    last = [r for r in usable if timeutil.parse(r.time.value) == latest]
    viol = sorted({r.value for r in last} & violating)
    value = viol[0] if viol else sorted({r.value for r in last})[0]
    deciding = sorted(
        (r for r in last if r.value == value), key=lambda r: (r.file_id, r.locator.ref if r.locator else "")
    )[0]
    basis: StateBasis = {"omission": "omission_in_declared_scope", "image": "image_extraction"}.get(
        deciding.kind, "latest_observation"
    )  # type: ignore[assignment]
    return ResourceState(
        key, value, basis, deciding.locator, deciding.time.value, depends_on, deciding.time.basis, tuple(usable)
    )


def has_attachment_listing(observations: Sequence[Observation]) -> bool:
    """Any record of the resource listed as a ticket attachment."""
    return any(is_attachment_listing(o) for o in observations)
