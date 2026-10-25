"""Catalog links: ``LINK_RESOURCE_IDENTITY`` activity rows, and the aliases they name.

A catalog row such as "Data catalog linked export_1842 (NST-2026-0718-1842) to <email> and
user_18" ties a resource to a person, and may name an alias the record is known by elsewhere.

Rules (each with its basis):

* A catalog row links its resource to the people its identifiers resolve to, exactly (T49). If
  they resolve to more than one person the row links no one (the T68 several-people rule,
  applied to the same kind of statement). Basis: research/15 section 3.5 item 3; DEV unchanged.
* An alias is the parenthesised token after the resource ID when it differs from the ID, is not a
  user ID and has no ``.``: a user ID names a person, not a record (T49 field roles), and a
  dotted token names a file. Basis: research/15 section 3.5 item 3.
* An evidence record whose text or fields contain the alias is evidence that the resource is
  present there, but only for an audit whose ``audit_at`` is at or after the catalog row
  (developer ruling T71 Q3: an alias counts when a link row at or before ``audit_at`` ties it).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ..evidence.interpret import EMAIL_IN_TEXT, USER_ID_IN_TEXT, make_identifier, system_from_prefix
from ..evidence.model import EvidenceIndex, Identifier, Observation
from ..identity.resolve import PeopleIndex
from ..inputs.model import ActivityRow

LINK_EVENT = "LINK_RESOURCE_IDENTITY"
_ALIAS_RE = re.compile(r"\b(\S+) \(([^)]+)\)")


@dataclass(frozen=True)
class CatalogLink:
    """One ``LINK_RESOURCE_IDENTITY`` row, interpreted."""

    activity_id: str
    event_time: str
    resource_id: str
    system_id: str
    identifiers: tuple[Identifier, ...]
    persons: frozenset[str]  # empty when the identifiers resolve to no one or to several people
    several_people: bool
    alias: str | None


@dataclass(frozen=True)
class AliasEvidence:
    """An evidence record that names a catalog alias: the aliased resource is present there."""

    resource_id: str
    system_id: str
    file_id: str
    observation: Observation  # the first record of the file (locator order) naming the alias
    link_activity_id: str
    link_time: str  # usable only when link_time <= audit_at (T71 Q3)


def _alias(details: str, resource_id: str) -> str | None:
    """The alias a catalog row names for its resource, if any (rules in the module docstring)."""
    for match in _ALIAS_RE.finditer(details):
        rid, alias = match.group(1), match.group(2)
        if rid != resource_id or alias == rid:
            continue
        if USER_ID_IN_TEXT.fullmatch(alias) or "." in alias:
            return None
        return alias
    return None


def catalog_links(activity: Sequence[ActivityRow], people: PeopleIndex) -> tuple[CatalogLink, ...]:
    """Every catalog row, in file order."""
    out: list[CatalogLink] = []
    for row in activity:
        if row.event_type != LINK_EVENT or not row.resource_id:
            continue
        idents = [make_identifier("email", m.group(0), "details") for m in EMAIL_IN_TEXT.finditer(row.details)]
        idents += [make_identifier("user_id", m.group(0), "details") for m in USER_ID_IN_TEXT.finditer(row.details)]
        persons: set[str] = set()
        for ident in idents:
            persons |= people.persons_for(ident)
        several = len(persons) > 1
        system = system_from_prefix(row.resource_id) or row.target_system
        out.append(
            CatalogLink(
                activity_id=row.activity_id,
                event_time=row.event_time,
                resource_id=row.resource_id,
                system_id=system,
                identifiers=tuple(idents),
                persons=frozenset() if several else frozenset(persons),
                several_people=several,
                alias=_alias(row.details, row.resource_id),
            )
        )
    return tuple(out)


def _mentions(obs: Observation, alias: str) -> bool:
    """True when the record's text or any field value contains the alias exactly."""
    if obs.text and alias in obs.text:
        return True
    return any(alias in value for value in obs.attrs.values())


def alias_evidence(links: Sequence[CatalogLink], index: EvidenceIndex) -> tuple[AliasEvidence, ...]:
    """One :class:`AliasEvidence` per (catalog row with an alias, file naming it), in manifest order."""
    out: list[AliasEvidence] = []
    for link in links:
        if not link.alias:
            continue
        for fp in index.files.values():
            hit = next((o for o in fp.observations if _mentions(o, link.alias)), None)
            if hit is not None:
                out.append(
                    AliasEvidence(link.resource_id, link.system_id, fp.file_id, hit, link.activity_id, link.event_time)
                )
    return tuple(out)


def catalog_by_resource(links: Sequence[CatalogLink]) -> Mapping[str, tuple[CatalogLink, ...]]:
    """Catalog rows grouped by resource, file order kept."""
    out: dict[str, list[CatalogLink]] = {}
    for link in links:
        out.setdefault(link.resource_id, []).append(link)
    return {k: tuple(v) for k, v in out.items()}
