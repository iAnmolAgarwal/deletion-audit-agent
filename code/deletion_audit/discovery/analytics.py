"""Identifier-free records attached to a deletion job by the policy slot's timing band (T5, T53, T62).

Anonymization removed every identifier from these records, so no identifier can tie them to a
person. The generator's job timing can: a deletion-worker "Policy action completed" row of the
same job sits in a policy slot before ``reported_at`` with a fixed residual mod 60 s from the
job's account delete row (``timing.slot_fit``).

Rules, each with its basis:

* Population: deletion-worker rows (not the submit row) of a resource that no input ties to any
  person and that has evidence. Basis: research/15 R19; G2 H2 (125 such rows, all ANONYMIZE).
* A request claims a record when its account's delete row anchors a job the row fits by its
  slot band, and the record has an observation at or before the request's ``audit_at``.
  Basis: T53 (93/93 identifier-linked policy rows in their slot band; DEV 4/4, 0 false positives,
  ``g2f2-g2f2_h2_analytics-0242``). This is generator timing, not a domain rule (README, T5/T53).
* One owner per person (T29), one record per job: a maximum one-to-one matching per group of
  competing requests, and a pair is kept only when every maximum matching contains it (form
  "slot / M": test pairs kept 114, T62).
* T62: analytics follow their job's account, a flagged tie pick included, and carry its flag.
* Every request of both request files competes (T32).
"""

from __future__ import annotations

import itertools
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ..evidence.model import EvidenceIndex, Observation
from ..identity.resolve import IdentityResolution
from ..inputs.model import ActivityRow
from ..inputs.requests import DeletionRequest
from ..timeutil import offset_seconds
from .accounts import AccountAssignment, Flag, order_key, person_key
from .obstime import at_or_before, observation_time
from .timing import DELETION_WORKER, offset_min, slot_fit, slot_of, template


@dataclass(frozen=True)
class AnalyticsClaim:
    """One identifier-free record kept for one request."""

    case_id: str
    resource_id: str
    slot: int
    residual_s: int
    anchor_stage: str
    flags: tuple[Flag, ...]
    activity_id: str = ""


def free_rows(
    activity: Sequence[ActivityRow], owners: Mapping[str, frozenset[str]], evidenced: frozenset[str]
) -> tuple[ActivityRow, ...]:
    """Deletion-worker non-submit rows of resources tied to no one that have evidence."""
    return tuple(
        a
        for a in activity
        if a.source_system == DELETION_WORKER
        and template(a) != "submit"
        and a.resource_id
        and not owners.get(a.resource_id)
        and a.resource_id in evidenced
    )


def attach_identifier_free_analytics(
    assignments: Mapping[str, AccountAssignment],
    requests: Sequence[DeletionRequest],
    people: Mapping[str, IdentityResolution],
    activity: Sequence[ActivityRow],
    index: EvidenceIndex,
    *,
    owners: Mapping[str, frozenset[str]],
    extra: Sequence[Observation] = (),
) -> Mapping[str, tuple[AnalyticsClaim, ...]]:
    """Claims kept per request (module docstring). The slot bands are ``config.SLOT_BANDS``."""
    obs_by_res: dict[str, list[Observation]] = defaultdict(list)
    for o in list(index.observations()) + list(extra):
        if o.resource_id:
            obs_by_res[o.resource_id].append(o)
    rows = free_rows(activity, owners, frozenset(obs_by_res))
    by_id = {a.activity_id: a for a in activity}
    req_by_id = {r.case_id: r for r in requests}
    claims: dict[str, dict[str, ActivityRow]] = {}
    for req in requests:
        asg = assignments.get(req.case_id)
        if asg is None or asg.resource_id is None or asg.anchor_activity_id is None:
            continue
        anchor = by_id[asg.anchor_activity_id]
        a_s = offset_seconds(anchor.event_time, req.reported_at)
        mine: dict[str, ActivityRow] = {}
        for a in rows:
            rid = a.resource_id or ""
            if rid in mine:
                continue
            if not any(at_or_before(observation_time(o), req.audit_at) for o in obs_by_res[rid]):
                continue
            if slot_fit(a, req.reported_at, a_s):
                mine[rid] = a
        if mine:
            claims[req.case_id] = mine
    kept = _one_to_one(
        claims,
        {c: person_key(req_by_id[c], people[c]) for c in claims},
        {c: order_key(req_by_id[c], people[c]) for c in claims},
    )
    out: dict[str, tuple[AnalyticsClaim, ...]] = {}
    for cid, rid in sorted(kept.items()):
        req, asg = req_by_id[cid], assignments[cid]
        row = claims[cid][rid]
        anchor = by_id[asg.anchor_activity_id or ""]
        a_s = offset_seconds(anchor.event_time, req.reported_at)
        row_s = offset_seconds(row.event_time, req.reported_at)
        flags = tuple(
            Flag("ANALYTICS_ON_TIE_PICK", f"anchored on a {asg.stage} account")
            for _ in [0]
            if asg.stage == "S5_TIE_PICK"
        )
        out[cid] = (
            AnalyticsClaim(
                cid,
                rid,
                slot_of(offset_min(row, req.reported_at)) or 0,
                int((row_s - a_s) % 60),
                asg.stage,
                flags,
                row.activity_id,
            ),
        )
    return out


def _one_to_one(
    claims: Mapping[str, Mapping[str, ActivityRow]], person: Mapping[str, str], order: Mapping[str, str]
) -> dict[str, str]:
    """Keep a (request, record) pair only when every maximum matching contains it (form M)."""
    edges = {c: sorted(g) for c, g in claims.items() if g}
    cases = sorted(edges, key=lambda c: order[c])
    parent = {c: c for c in cases}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    first: dict[str, str] = {}
    for c in cases:
        for rid in edges[c]:
            if rid in first:
                parent[find(c)] = find(first[rid])
            else:
                first[rid] = c
    comps: dict[str, list[str]] = defaultdict(list)
    for c in cases:
        comps[find(c)].append(c)
    out: dict[str, str] = {}
    for root in sorted(comps, key=lambda r: order[r]):
        comp = comps[root]
        best, sols = -1, []
        for combo in itertools.product(*[edges[c] + [None] for c in comp]):
            used: dict[str, str] = {}
            ok = True
            for c, p in zip(comp, combo, strict=True):
                if p is None:
                    continue
                if p in used and used[p] != person[c]:
                    ok = False
                    break
                used[p] = person[c]
            if not ok:
                continue
            n = sum(1 for p in combo if p)
            if n > best:
                best, sols = n, [combo]
            elif n == best:
                sols.append(combo)
        for i, c in enumerate(comp):
            vals = {s[i] for s in sols}
            if len(vals) == 1 and None not in vals:
                out[c] = next(iter(vals))  # type: ignore[assignment]
    return out
