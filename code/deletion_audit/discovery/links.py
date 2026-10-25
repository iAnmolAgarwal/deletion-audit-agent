"""Which evidence records belong to which person (exact identifier links only).

Rules, each with its basis:

* **Exact match only** on the normalized value of a linkable identifier (email, phone, email
  hash, user ID); a look-alike such as ``name.jr@domain`` never matches. Basis: T49.
* **A field's role comes from its line** (the evidence layer already split record keys from
  lookup keys, ``interpret.split_identifiers``). A record links by its own key, or by an
  identifier in its free text. Basis: T49; research/15 R1 (one DEV record links only by an old email hash).
* **A line's own key beats a trace lookup** (T59): a record that carries its own linkable key is
  linked only through that key, compared against the person's complete identifier set. Only a
  record with no own key, that names a resource, borrows the lookup keys of its trace. So a decoy
  hit whose own key is a look-alike never links, even when its trace looked up the person.
* **PDF pages (T68):** identifiers on a page that names several resources, or whose identifiers
  resolve to several people, never link.
* **Catalog rows** link their resource to the person they name (``catalog.py``).
* **Window (R3, R4, R5):** a link discovers a record only when the record's own time is in
  ``[requested_at, audit_at]`` (research/15 R3: 59 of 76 DEV pairs, 0 extras; no lower bound
  gives 19/22). A line inside a file captured after ``audit_at`` still counts when its own time
  is at or before ``audit_at`` (R4: 5 DEV pairs), but such a file is never cited.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from .. import timeutil
from ..config import LINK_KINDS, TEXT_ID_FIELDS
from ..evidence.interpret import leaf_name
from ..evidence.model import EvidenceIndex, Identifier, Observation
from ..identity.resolve import IdentityResolution, PeopleIndex
from .catalog import AliasEvidence, CatalogLink
from .obstime import ObsTime, in_window, observation_time

LinkBasis = Literal["record_identifier", "trace_lookup", "link_row", "alias", "image_extraction"]


@dataclass(frozen=True)
class Window:
    """The discovery window of one request (R3)."""

    requested_at: str
    audit_at: str


@dataclass(frozen=True)
class Link:
    """One record tied to one person.

    ``observation`` is None for a catalog row (``basis == "link_row"``), which is an activity row,
    not an evidence record; ``activity_id`` names it then.
    """

    observation: Observation | None
    basis: LinkBasis
    matched: Identifier | None
    in_window: bool  # the record's own time is in [requested_at, audit_at] (R3/R4)
    citable: bool  # its file was captured at or before audit_at (G1 F21, equality allowed)
    resource_id: str | None
    system_id: str | None
    time: ObsTime | None
    activity_id: str | None = None

    @property
    def file_id(self) -> str | None:
        """The evidence file holding the record (None for a catalog row)."""
        return self.observation.file_id if self.observation is not None else None


@dataclass(frozen=True)
class ObservationLink:
    """A person-independent link of one observation: who it belongs to and through which key."""

    person: str
    basis: LinkBasis
    matched: Identifier


def is_own_key(ident: Identifier) -> bool:
    """A record's own linkable key: a linkable kind written in a key field, not in free text (T49)."""
    return ident.kind in LINK_KINDS and leaf_name(ident.field) not in TEXT_ID_FIELDS


def _pdf_page_blocked(index: EvidenceIndex, people: PeopleIndex) -> frozenset[tuple[str, str]]:
    """PDF pages whose identifiers never link (T68): several resources, or several people."""
    blocked: set[tuple[str, str]] = set()
    pages: dict[tuple[str, str], list[Observation]] = defaultdict(list)
    for o in index.observations():
        if o.locator.kind == "pdf_page":
            pages[(o.file_id, o.locator.ref)].append(o)
    for key, obs in pages.items():
        resources = {o.resource_id for o in obs if o.resource_id}
        persons: set[str] = set()
        for o in obs:
            for ident in o.record_identifiers:
                persons |= people.persons_for(ident)
        if len(resources) > 1 or len(persons) > 1:
            blocked.add(key)
    return frozenset(blocked)


def link_observation(obs: Observation, people: PeopleIndex, blocked: bool = False) -> tuple[ObservationLink, ...]:
    """Every person one observation links to, with the basis (module docstring)."""
    if blocked:
        return ()
    out: dict[str, ObservationLink] = {}
    own = sorted((i for i in obs.record_identifiers if is_own_key(i)), key=_ident_key)
    text = sorted((i for i in obs.record_identifiers if i.kind in LINK_KINDS and not is_own_key(i)), key=_ident_key)
    for ident in own + text:
        for p in sorted(people.persons_for(ident)):
            out.setdefault(p, ObservationLink(p, "record_identifier", ident))
    if not own and obs.resource_id:
        for ident in sorted(obs.lookup_identifiers, key=_ident_key):
            for p in sorted(people.persons_for(ident)):
                out.setdefault(p, ObservationLink(p, "trace_lookup", ident))
    return tuple(out[p] for p in sorted(out))


def _ident_key(i: Identifier) -> tuple[str, str, str]:
    return (i.kind, i.value, i.field)


@dataclass(frozen=True)
class LinkIndex:
    """Person-independent link facts, computed once for all requests."""

    by_person: Mapping[str, tuple[tuple[Observation, ObservationLink], ...]]
    resource_persons: Mapping[str, frozenset[str]]  # every person any record or catalog row ties a resource to
    catalog_by_person: Mapping[str, tuple[CatalogLink, ...]]
    blocked_pages: frozenset[tuple[str, str]]


def build_link_index(
    index: EvidenceIndex, people: PeopleIndex, catalog: Sequence[CatalogLink], extra: Sequence[Observation] = ()
) -> LinkIndex:
    """Link every observation (and any extra image observations) and every catalog row."""
    blocked = _pdf_page_blocked(index, people)
    by_person: dict[str, list[tuple[Observation, ObservationLink]]] = defaultdict(list)
    res_persons: dict[str, set[str]] = defaultdict(set)
    for o in list(index.observations()) + list(extra):
        for ol in link_observation(o, people, (o.file_id, o.locator.ref) in blocked):
            by_person[ol.person].append((o, ol))
            if o.resource_id:
                res_persons[o.resource_id].add(ol.person)
    cat: dict[str, list[CatalogLink]] = defaultdict(list)
    for c in catalog:
        for p in sorted(c.persons):
            cat[p].append(c)
            res_persons[c.resource_id].add(p)
    return LinkIndex(
        by_person={k: tuple(v) for k, v in by_person.items()},
        resource_persons={k: frozenset(v) for k, v in res_persons.items()},
        catalog_by_person={k: tuple(v) for k, v in cat.items()},
        blocked_pages=blocked,
    )


def link_observations(
    person: IdentityResolution, links: LinkIndex, window: Window, aliases: Sequence[AliasEvidence] = ()
) -> tuple[Link, ...]:
    """Every link of one person, flagged with whether it falls in the window and can be cited.

    The pinned form takes the evidence index and activity rows; this one takes the
    :class:`LinkIndex` built from them once (same facts, computed for all requests together).
    """
    uid = person.person
    if uid is None:
        return ()
    out: list[Link] = []
    for o, ol in links.by_person.get(uid, ()):
        t = observation_time(o)
        out.append(
            Link(
                o,
                ol.basis,
                ol.matched,
                in_window(t, window.requested_at, window.audit_at),
                timeutil.le(o.captured_at, window.audit_at),
                o.resource_id,
                o.system_id,
                t,
            )
        )
    owned = set()
    for c in links.catalog_by_person.get(uid, ()):
        owned.add(c.resource_id)
        t = ObsTime(c.event_time, "second", "record_time")
        out.append(
            Link(
                None,
                "link_row",
                c.identifiers[0] if c.identifiers else None,
                timeutil.within(c.event_time, window.requested_at, window.audit_at),
                False,
                c.resource_id,
                c.system_id,
                t,
                activity_id=c.activity_id,
            )
        )
    for a in aliases:
        if a.resource_id not in owned or not timeutil.le(a.link_time, window.audit_at):
            continue
        t = observation_time(a.observation)
        out.append(
            Link(
                a.observation,
                "alias",
                None,
                in_window(t, window.requested_at, window.audit_at),
                timeutil.le(a.observation.captured_at, window.audit_at),
                a.resource_id,
                a.system_id,
                t,
                activity_id=a.link_activity_id,
            )
        )
    return tuple(out)
