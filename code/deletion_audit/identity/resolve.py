"""Identity resolution: request email -> the person and their complete identifier set.

Rules (each with its basis):

* R1: the request email maps to one person through the current email in ``user_identities.csv``
  or an old email in ``user_audit_log.csv``, case-insensitively. Basis: research/15 R1, DEV 22/22
  (21 current, 1 historical).
* T59: the identifier set is complete: ``user_id``, every current and old email and phone, every
  email hash on file, and sha256 of every email ever held (the identities file's own formula:
  sha256 of the lower-cased email, 850/850 rows).
* T49: matching is exact on the normalized value only, so a look-alike never matches.
* T63: a request whose email resolves to no one is ``UNRESOLVED``: its set holds only the
  request email and its hash, and a deletion request gets a defined fail-closed outcome
  downstream (a request read as NOT_DELETION is NOT_APPLICABLE; ``engine`` module docstring).
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from ..config import LINK_KINDS
from ..evidence.model import Identifier
from ..inputs.model import AuditLogRow, IdentityRow
from ..inputs.requests import DeletionRequest

ResolutionStatus = Literal["CURRENT", "HISTORICAL", "UNRESOLVED"]


def email_hash(email: str) -> str:
    """sha256 of the lower-cased, stripped email: the formula ``user_identities.csv`` uses (T59)."""
    return hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class IdentifierSet:
    """Every identifier a person has held (T59). Values are normalized as the evidence layer does."""

    user_id: str | None
    emails: frozenset[str]
    phones: frozenset[str]
    email_hashes: frozenset[str]

    def values_for(self, kind: str) -> frozenset[str]:
        """The set of normalized values of one identifier kind."""
        if kind == "email":
            return self.emails
        if kind == "phone":
            return self.phones
        if kind == "email_hash":
            return self.email_hashes
        if kind == "user_id":
            return frozenset({self.user_id}) if self.user_id else frozenset()
        return frozenset()

    def matches(self, ident: Identifier) -> bool:
        """Exact match on the normalized value, for linkable kinds only (T49)."""
        return ident.kind in LINK_KINDS and ident.value in self.values_for(ident.kind)


@dataclass(frozen=True)
class IdentityResolution:
    """Who a request is about. ``identifiers.user_id`` is the person (None when UNRESOLVED)."""

    status: ResolutionStatus
    identifiers: IdentifierSet
    via_audit_ids: tuple[str, ...]  # audit rows that tie an old email to the person (citable IDs)

    @property
    def person(self) -> str | None:
        """The resolved ``user_id``, or None."""
        return self.identifiers.user_id


@dataclass(frozen=True)
class PeopleIndex:
    """Every person's identifier set, plus a reverse index value -> person(s)."""

    people: Mapping[str, IdentifierSet]
    current_email: Mapping[str, str]  # normalized email -> user_id (current only)
    by_value: Mapping[tuple[str, str], frozenset[str]]  # (kind, value) -> user_ids
    email_audit_rows: Mapping[str, tuple[str, ...]] = field(default_factory=dict)  # email -> audit_ids

    def persons_for(self, ident: Identifier) -> frozenset[str]:
        """The people an identifier belongs to (exact normalized match; empty for other kinds)."""
        if ident.kind not in LINK_KINDS:
            return frozenset()
        return self.by_value.get((ident.kind, ident.value), frozenset())


def build_people(identities: Sequence[IdentityRow], audit_log: Sequence[AuditLogRow]) -> PeopleIndex:
    """Build every person's complete identifier set from both identity files (T59)."""
    emails: dict[str, set[str]] = defaultdict(set)
    phones: dict[str, set[str]] = defaultdict(set)
    hashes: dict[str, set[str]] = defaultdict(set)
    current: dict[str, str] = {}
    known: set[str] = set()
    audit_rows: dict[str, list[str]] = defaultdict(list)
    for row in identities:
        known.add(row.user_id)
        if row.email is not None:
            emails[row.user_id].add(row.email.value)
            current[row.email.value] = row.user_id
        if row.phone is not None:
            phones[row.user_id].add(row.phone.value)
        if row.email_hash:
            hashes[row.user_id].add(row.email_hash.strip().lower())
    for a in audit_log:
        known.add(a.user_id)
        for ident in (a.old_identifier, a.new_identifier):
            if ident is None:
                continue
            if ident.kind == "email":
                emails[a.user_id].add(ident.value)
                audit_rows[ident.value].append(a.audit_id)
            elif ident.kind == "phone":
                phones[a.user_id].add(ident.value)
            elif ident.kind == "email_hash":
                hashes[a.user_id].add(ident.value)
    people: dict[str, IdentifierSet] = {}
    by_value: dict[tuple[str, str], set[str]] = defaultdict(set)
    for uid in sorted(known):
        hs = set(hashes[uid]) | {email_hash(e) for e in emails[uid]}
        ids = IdentifierSet(
            user_id=uid, emails=frozenset(emails[uid]), phones=frozenset(phones[uid]), email_hashes=frozenset(hs)
        )
        people[uid] = ids
        by_value[("user_id", uid)].add(uid)
        for kind in ("email", "phone", "email_hash"):
            for v in ids.values_for(kind):
                by_value[(kind, v)].add(uid)
    return PeopleIndex(
        people=people,
        current_email=current,
        by_value={k: frozenset(v) for k, v in by_value.items()},
        email_audit_rows={k: tuple(v) for k, v in audit_rows.items()},
    )


def resolve(
    req: DeletionRequest, identities: Sequence[IdentityRow], audit_log: Sequence[AuditLogRow]
) -> IdentityResolution:
    """Resolve one request (the pinned signature, ``notes/ARCHITECTURE_OPTIONS.md`` section 5)."""
    return resolve_with(req, build_people(identities, audit_log))


def resolve_with(req: DeletionRequest, people: PeopleIndex) -> IdentityResolution:
    """Resolve one request's email to a person (R1), current first, then historical.

    A current email wins outright, even if someone else held it earlier. Otherwise an email held
    by two different people is never guessed: it is ``UNRESOLVED`` (0 shared values measured by
    ``build_people`` in the data).
    """
    value = req.email.value
    uid = people.current_email.get(value)
    if uid is not None:
        return IdentityResolution("CURRENT", people.people[uid], ())
    owners = people.by_value.get(("email", value), frozenset())
    if len(owners) == 1:
        uid = next(iter(owners))
        return IdentityResolution(
            "HISTORICAL", people.people[uid], tuple(sorted(people.email_audit_rows.get(value, ())))
        )
    fallback = IdentifierSet(
        user_id=None, emails=frozenset({value}), phones=frozenset(), email_hashes=frozenset({email_hash(value)})
    )
    return IdentityResolution("UNRESOLVED", fallback, ())
