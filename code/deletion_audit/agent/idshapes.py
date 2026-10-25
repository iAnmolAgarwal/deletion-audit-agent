"""Per-system resource-ID shapes, learned from the dataset's own records (developer ruling T88 (2)).

A shape is a prefix ending in ``_`` followed by a run of digits whose length lies in the range
seen for that prefix and system. Shapes come from two sources, never from a hand-typed table:

* every parsed evidence observation that names a ``resource_id`` with a ``system_id`` (the
  evidence layer resolves the system from the record's own fields, ``evidence/interpret.py``);
* every ``LINK_RESOURCE_IDENTITY`` row, whose system is the catalog's (``discovery/catalog.py``).

Other activity rows are not a source: their ``target_system`` is noisy (support IDs under
``search_service``, account IDs under ``privacy_case_management``), so learning from them would
make a prefix ambiguous. Basis: counted on the dataset inputs by this gate (no gold read): every
evidence ``(system, prefix)`` pair is unique per prefix.

An ID "named elsewhere" appears as a ``resource_id`` in a parsed evidence record, a LINK row or
any activity row (T88 (2): an ID no other input names is flagged, never dropped).
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from ..discovery.catalog import LINK_EVENT
from ..evidence.interpret import system_from_prefix
from ..evidence.model import Observation
from ..inputs.model import ActivityRow

_ID_RE = re.compile(r"([A-Za-z][A-Za-z_]*_)(\d+)")
_DISPLAY_RE = re.compile(r"\b(\S+) \(([^)]+)\)")
IdBasis = Literal["shape", "catalog_display_name", "malformed", "unrecognized", "ambiguous"]


def split_id(value: str) -> tuple[str, int] | None:
    """``(prefix, digit count)`` for an ID made of a prefix ending in ``_`` and digits, else None."""
    m = _ID_RE.fullmatch(value)
    return (m.group(1), len(m.group(2))) if m else None


@dataclass(frozen=True)
class IdShapes:
    """Learned shapes: ``ranges[(system, prefix)] = (min digits, max digits)``, plus the known IDs."""

    ranges: Mapping[tuple[str, str], tuple[int, int]]
    known_ids: Mapping[str, frozenset[str]]  # resource_id -> sources naming it ("evidence", "link_row", "activity")
    display_names: Mapping[str, tuple[str, str, str]]  # LINK-row display name -> (resource_id, system, activity_id)

    def prefixes(self) -> frozenset[str]:
        """Every learned prefix."""
        return frozenset(p for _, p in self.ranges)

    def systems_for(self, resource_id: str) -> tuple[str, ...]:
        """The systems whose shape ``resource_id`` fits, sorted."""
        parts = split_id(resource_id)
        if parts is None:
            return ()
        prefix, digits = parts
        return tuple(sorted(s for (s, p), (lo, hi) in self.ranges.items() if p == prefix and lo <= digits <= hi))

    def named_by(self, resource_id: str) -> tuple[str, ...]:
        """The input kinds that name ``resource_id`` (empty: no other input names it)."""
        return tuple(sorted(self.known_ids.get(resource_id, frozenset())))


@dataclass(frozen=True)
class IdCheck:
    """How one shown identifier maps to a resource ID (T88 (2))."""

    shown_id: str
    resource_id: str | None  # set only when the ID is usable (well-formed or a catalog display name)
    system_id: str | None
    basis: IdBasis
    well_formed: bool
    named_by: tuple[str, ...]
    link_activity_id: str | None = None

    @property
    def named_elsewhere(self) -> bool:
        """Whether any other input names the resource ID."""
        return bool(self.named_by)


def learn_shapes(observations: Iterable[Observation], activity: Sequence[ActivityRow]) -> IdShapes:
    """Learn the shapes and the known-ID index (module docstring)."""
    seen: dict[tuple[str, str], list[int]] = defaultdict(list)
    known: dict[str, set[str]] = defaultdict(set)
    names: dict[str, tuple[str, str, str]] = {}
    for o in observations:
        if o.resource_id:
            known[o.resource_id].add("evidence")
            parts = split_id(o.resource_id)
            if parts and o.system_id:
                seen[(o.system_id, parts[0])].append(parts[1])
    for a in activity:
        if not a.resource_id:
            continue
        known[a.resource_id].add("activity")
        if a.event_type != LINK_EVENT:
            continue
        known[a.resource_id].add("link_row")
        system = system_from_prefix(a.resource_id) or a.target_system
        parts = split_id(a.resource_id)
        if parts:
            seen[(system, parts[0])].append(parts[1])
        for m in _DISPLAY_RE.finditer(a.details):
            if m.group(1) == a.resource_id and m.group(2) != a.resource_id:
                names.setdefault(m.group(2), (a.resource_id, system, a.activity_id))
    return IdShapes(
        ranges={k: (min(v), max(v)) for k, v in sorted(seen.items())},
        known_ids={k: frozenset(v) for k, v in sorted(known.items())},
        display_names=dict(sorted(names.items())),
    )


def check_id(shown_id: str, shapes: IdShapes) -> IdCheck:
    """Map a shown identifier to a resource ID, or say why it cannot be used (T88 (2)).

    Order: (1) the ID fits exactly one learned shape -> usable; (2) it is a display name a LINK row
    gives a resource -> usable as that resource; (3) it fits several systems' shapes -> not used,
    ``ambiguous``; (4) its prefix is a learned prefix but the digits do not fit -> ``malformed``,
    not used; (5) anything else is a label, not a resource ID -> ``unrecognized``, not used.
    """
    value = shown_id.strip()
    systems = shapes.systems_for(value)
    if len(systems) == 1:
        return IdCheck(shown_id, value, systems[0], "shape", True, shapes.named_by(value))
    if value in shapes.display_names:
        rid, system, act = shapes.display_names[value]
        return IdCheck(shown_id, rid, system, "catalog_display_name", True, shapes.named_by(rid), act)
    if len(systems) > 1:
        return IdCheck(shown_id, None, None, "ambiguous", False, shapes.named_by(value))
    lead = re.match(r"[A-Za-z][A-Za-z_]*", value)
    prefix = lead.group(0).rstrip("_") + "_" if lead else ""
    if prefix in shapes.prefixes():
        owner = sorted(s for (s, p) in shapes.ranges if p == prefix)
        return IdCheck(shown_id, None, owner[0] if len(owner) == 1 else None, "malformed", False, ())
    return IdCheck(shown_id, None, None, "unrecognized", False, ())
