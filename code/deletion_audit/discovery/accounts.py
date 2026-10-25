"""Primary-account assignment: one global pass over every request of both request files.

Rule: every request gets at most one primary account, from the first stage below that finds one,
and one account has one owner per *person* (two requests of one person may share it). Reason: an
account candidate is shared between requests, so only a pass over all requests can keep two people
from getting the same account (T29, T32 in code/docs/DECISIONS.md). Baseline on DEV, run
``g2f2-g2f2_baseline-0242``: 21 of 22 accounts correct; the one miss is a hand-built DEV account.

1. **S1 identifier link:** an ``account_service`` record linked to the person in the request
   window. DEV 11 of 11 (T4).
2. **S2 timed rule:** account delete rows -75..-44 min before ``reported_at`` (inclusive) whose
   result matches the reported status, leaving out accounts any input ties to another person (the
   owner filter). DEV 7 of 7; on test with identifier links hidden, it picks the linked account
   116 of 116 (T4).
3. **T26 near window:** only when S1 and S2 find nothing, a delete row within +-10 min,
   result-matched and owner-filtered. DEV 3 of 3, test 0. The mismatched-result fallback is not
   used; its one DEV case stays a known miss (T26, T58).
4. **S3 one-to-one:** a request with a single candidate keeps it, and that account leaves the
   other people's candidate sets, repeated to a fixed point.
5. **S4 D17 fingerprint, then S4b one-to-one again:** keep the candidates whose timing phase fits
   every one of the person's own deletion-worker rows (bands and their basis in ``config.py``'s
   job-timing block). On test with identifier links hidden: 77 of 77 and 28 of 28 (T5).
6. **S5 tie order:** for each group of requests still tied over shared candidates, a one-to-one
   matching is chosen that gives the most requests an account, then the smallest total distance
   of the picked rows from -60 min. Among matchings still equal, the requests are taken in the
   order of sha256 of the resolved ``user_id``, each preferring its own candidates by distance from
   -60 min and then by account ID. No input separates these ties, so the order is deterministic
   but carries no evidence: every row it decides is flagged ``D18_TIE_PICK`` (T6, T39, T57). In
   the shipped test run ``cand-test-Aplus-20261025T1352`` it decides 27 of 518 cases (25 between
   2 candidates, 2 among 3; ``cases.jsonl``, account stage ``S5_TIE_PICK``).
7. **T27 later lookup:** still nothing: the person's own email or phone used as a log lookup key,
   joined on the same trace to an account, at any line time. This settles identity only: the
   account's state and every citation still come from evidence at or before ``audit_at``; flagged.
8. **T28 none:** still nothing: no account step, flagged. An account ID is never invented.

T-numbers refer to the developer's rulings in code/docs/DECISIONS.md; D17 is the job-timing
fingerprint (T5) and D18 the tie pick (T6). No stage reads sample answers, a case ID, a file name
or a row position. Every order is named: the visiting and tie order is sha256 of the resolved
``user_id`` (an unresolved request uses sha256 of its email), then the request's own times.
"""

from __future__ import annotations

import functools
import hashlib
import itertools
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from ..config import AccountConfig
from ..evidence.interpret import system_from_prefix
from ..identity.resolve import IdentityResolution
from ..inputs.model import ActivityRow
from ..inputs.requests import DeletionRequest
from .links import Link
from .timing import DELETION_WORKER, account_phase, in_template_window, offset_min, sig_match, template

AccountStage = Literal[
    "S1_IDENTIFIER",
    "S2_TIMED",
    "T26_HAND_BUILT",
    "S3_ONE_TO_ONE",
    "S4_FINGERPRINT",
    "S4B_ONE_TO_ONE",
    "S5_TIE_PICK",
    "T27_LATER_LOOKUP",
    "T28_NONE",
]
ACCOUNT_SYSTEM = "account_service"
LOG_FAMILIES_SUFFIX = "_log"


@dataclass(frozen=True)
class Flag:
    """A run-artifact flag. ``detail`` names IDs and counts only, never cell text."""

    code: str
    detail: str


@dataclass(frozen=True)
class AccountAssignment:
    """The primary account of one request, the stage that found it, and its D17 anchor row."""

    case_id: str
    resource_id: str | None
    stage: AccountStage
    candidates: tuple[str, ...]
    activity_ids: tuple[str, ...]
    flags: tuple[Flag, ...]
    anchor_activity_id: str | None = None  # the account delete row the job's timing is read from


@dataclass
class _State:
    req: DeletionRequest
    person: str
    order: str
    candidates: dict[str, ActivityRow]
    own_rows: list[ActivityRow]
    pre: int
    flags: list[Flag] = field(default_factory=list)
    stage: str | None = None
    pick: str | None = None
    pick_row: ActivityRow | None = None
    linked_accounts: tuple[str, ...] = ()


def person_key(req: DeletionRequest, ident: IdentityResolution) -> str:
    """The one-to-one owner key: the resolved ``user_id``, else a key of the request email (T29)."""
    return ident.person if ident.person else "?" + req.email.value


def order_key(req: DeletionRequest, ident: IdentityResolution) -> str:
    """The visiting and tie order: sha256 of the resolved ``user_id`` (else of the email), then the request times."""
    base = ident.person or req.email.value
    return hashlib.sha256(base.encode("utf-8")).hexdigest() + "|" + req.requested_at + "|" + req.reported_at


def account_delete_rows(activity: Sequence[ActivityRow]) -> tuple[ActivityRow, ...]:
    """Every ``DELETE_RECORD`` row aimed at ``account_service`` in file order."""
    return tuple(
        a for a in activity if a.event_type == "DELETE_RECORD" and a.target_system == ACCOUNT_SYSTEM and a.resource_id
    )


def assign_primary_accounts(
    requests: Sequence[DeletionRequest],
    people: Mapping[str, IdentityResolution],
    activity: Sequence[ActivityRow],
    links: Mapping[str, tuple[Link, ...]],
    cfg: AccountConfig,
    *,
    owners: Mapping[str, frozenset[str]],
) -> Mapping[str, AccountAssignment]:
    """Assign every request's primary account (module docstring). ``owners`` maps a resource to
    every person any input ties it to (the owner filter)."""
    adr = account_delete_rows(activity)
    worker = [a for a in activity if a.source_system == DELETION_WORKER]
    lo, hi = cfg.window_min
    states: dict[str, _State] = {}
    for req in requests:
        ident = people[req.case_id]
        person = person_key(req, ident)
        want = cfg.result_map.get(req.reported_status)
        lk = links.get(req.case_id, ())
        linked_accounts = tuple(
            sorted({lk.resource_id for lk in lk if lk.in_window and lk.resource_id and _is_account(lk)})
        )

        def owner_ok(rid: str, _p: str = person) -> bool:
            return not (owners.get(rid, frozenset()) - {_p})

        cand: dict[str, ActivityRow] = {}
        for a in adr:
            if (
                lo <= offset_min(a, req.reported_at) <= hi
                and a.reported_result == want
                and owner_ok(a.resource_id or "")
            ):
                cand[a.resource_id or ""] = a
        st = _State(req, person, order_key(req, ident), cand, [], len(cand), linked_accounts=linked_accounts)
        if not linked_accounts and not cand:
            near = {
                a.resource_id or "": a
                for a in adr
                if -cfg.hand_built_min <= offset_min(a, req.reported_at) <= cfg.hand_built_min
                and a.reported_result == want
                and owner_ok(a.resource_id or "")
            }
            if near:
                st.candidates, st.pre = near, len(near)
                st.flags.append(
                    Flag("T26_HAND_BUILT_WINDOW", f"{len(near)} candidate(s) within +-{cfg.hand_built_min} min")
                )
        own_res = {lk.resource_id for lk in lk if lk.in_window and lk.resource_id}
        st.own_rows = [
            a
            for a in worker
            if a.resource_id in own_res and template(a) != "submit" and in_template_window(a, req.reported_at)
        ]
        if linked_accounts:
            st.stage, st.pick = "S1_IDENTIFIER", linked_accounts[0]
            rows = [a for a in adr if a.resource_id == st.pick]
            st.pick_row = (
                min(rows, key=lambda a: (abs(offset_min(a, req.reported_at) + 60), a.activity_id)) if rows else None
            )
            if len(linked_accounts) > 1:
                st.flags.append(Flag("S1_SEVERAL_ACCOUNTS", f"{len(linked_accounts)} identifier-linked accounts"))
        states[req.case_id] = st

    _propagate(states, "S2S3")
    for st in states.values():
        if st.stage == "S2S3":
            st.stage = "S2_TIMED" if st.pre == 1 else "S3_ONE_TO_ONE"
            if any(f.code == "T26_HAND_BUILT_WINDOW" for f in st.flags):
                st.stage = "T26_HAND_BUILT"
    _d17(states)
    _propagate(states, "S4B_ONE_TO_ONE")
    _s5(states)
    _t27(states, links)
    out: dict[str, AccountAssignment] = {}
    for cid, st in states.items():
        if st.pick is None:
            st.stage = "T28_NONE"
            st.flags.append(Flag("T28_NO_ACCOUNT", "no input names an account for this request"))
        out[cid] = AccountAssignment(
            case_id=cid,
            resource_id=st.pick,
            stage=st.stage,  # type: ignore[arg-type]
            candidates=tuple(sorted(st.candidates)),
            activity_ids=tuple(sorted({a.activity_id for a in st.candidates.values()})),
            flags=tuple(st.flags),
            anchor_activity_id=st.pick_row.activity_id if st.pick_row is not None else None,
        )
    return out


def _is_account(link: Link) -> bool:
    """An ``account_service`` record (by the evidence's own system, else by its ID prefix)."""
    system = link.system_id or system_from_prefix(link.resource_id)
    return system == ACCOUNT_SYSTEM


def _taken_by_others(states: Mapping[str, _State], st: _State) -> set[str]:
    """Accounts already picked for a different person (T29: one owner per person)."""
    return {o.pick for o in states.values() if o.pick and o.person != st.person}


def _propagate(states: dict[str, _State], stage: str) -> None:
    """Unique-first fixed point (T4 S3), visiting requests in the T39 order."""
    changed = True
    while changed:
        changed = False
        for st in sorted((s for s in states.values() if s.stage is None), key=lambda s: s.order):
            taken = _taken_by_others(states, st)
            new = {k: v for k, v in st.candidates.items() if k not in taken}
            if len(new) != len(st.candidates):
                st.candidates = new
                changed = True
            if len(new) == 1:
                k = next(iter(new))
                st.stage, st.pick, st.pick_row = stage, k, new[k]
                changed = True
            elif not new and st.pre > 0 and not any(f.code == "S3_EMPTIED" for f in st.flags):
                st.flags.append(Flag("S3_EMPTIED", "every candidate was taken by another person"))


def _d17(states: dict[str, _State]) -> None:
    """T5 fingerprint tie-break: keep candidates whose phase fits every own non-submit row."""
    for st in states.values():
        if st.stage is not None or len(st.candidates) < 2 or not st.own_rows:
            continue
        rep = st.req.reported_at
        fit = {
            k: v for k, v in st.candidates.items() if all(sig_match(o, rep, account_phase(v, rep)) for o in st.own_rows)
        }
        if fit and len(fit) < len(st.candidates):
            st.candidates = fit
            if len(fit) == 1:
                k = next(iter(fit))
                st.stage, st.pick, st.pick_row = "S4_FINGERPRINT", k, fit[k]


def _components(sts: list[_State]) -> list[list[_State]]:
    """Groups of unresolved requests that share a candidate account."""
    parent = list(range(len(sts)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    first: dict[str, int] = {}
    for i, st in enumerate(sts):
        for k in sorted(st.candidates):
            if k in first:
                parent[find(i)] = find(first[k])
            else:
                first[k] = i
    groups: dict[int, list[_State]] = {}
    for i, st in enumerate(sts):
        groups.setdefault(find(i), []).append(st)
    return [groups[k] for k in sorted(groups)]


def _tie_cost(st: _State, rep: str, k: str) -> tuple[float, str]:
    """Distance of a candidate from -60 min, then its ID: a request's preference order in S5."""
    return (abs(offset_min(st.candidates[k], rep) + 60), k)


def _s5(states: dict[str, _State]) -> None:
    """S5: a deterministic one-to-one matching per tied group, each pick flagged (module docstring, stage 6)."""
    unresolved = sorted((s for s in states.values() if s.stage is None and s.candidates), key=lambda s: s.order)
    for comp in _components(unresolved):
        comp.sort(key=lambda s: s.order)
        avail = {}
        for st in comp:
            taken = _taken_by_others(states, st)
            rep = st.req.reported_at
            avail[id(st)] = sorted(
                (k for k in st.candidates if k not in taken), key=functools.partial(_tie_cost, st, rep)
            )
        best: tuple[str | None, ...] | None = None
        best_key: tuple[int, float, tuple[int, ...]] | None = None
        for combo in itertools.product(*[avail[id(st)] + [None] for st in comp]):
            used: dict[str, str] = {}
            ok = True
            for st, p in zip(comp, combo, strict=True):
                if p is None:
                    continue
                if p in used and used[p] != st.person:
                    ok = False
                    break
                used[p] = st.person
            if not ok:
                continue
            n = sum(1 for p in combo if p)
            tot = round(
                sum(
                    abs(offset_min(st.candidates[p], st.req.reported_at) + 60)
                    for st, p in zip(comp, combo, strict=True)
                    if p
                ),
                6,
            )
            lex = tuple((avail[id(st)] + [None]).index(p) for st, p in zip(comp, combo, strict=True))
            key = (-n, tot, lex)
            if best_key is None or key < best_key:
                best, best_key = combo, key
        if best is None:  # the all-None combination is always valid, so this cannot happen
            raise RuntimeError("S5 matching found no assignment")
        for st, p in zip(comp, best, strict=True):
            if p:
                st.stage, st.pick, st.pick_row = "S5_TIE_PICK", p, st.candidates[p]
                st.flags.append(
                    Flag("D18_TIE_PICK", f"one of {len(st.candidates)} tied candidates; order sha256(user_id)")
                )
            else:
                st.flags.append(Flag("S5_EXHAUSTED", "no candidate left in its tie group"))


def _t27(states: dict[str, _State], links: Mapping[str, tuple[Link, ...]]) -> None:
    """T27: the person's own email or phone as a log lookup key, joined on its trace to an account,
    at any line time (identity only)."""
    for cid, st in states.items():
        if st.pick is not None:
            continue
        hits = sorted(
            {
                lk.resource_id
                for lk in links.get(cid, ())
                if lk.resource_id
                and lk.observation is not None
                and _is_account(lk)
                and lk.observation.family.endswith(LOG_FAMILIES_SUFFIX)
                and lk.matched is not None
                and lk.matched.kind in ("email", "phone")
            }
        )
        if hits:
            st.stage, st.pick = "T27_LATER_LOOKUP", hits[0]
            st.flags.append(
                Flag("T27_LATER_IDENTITY_LOOKUP", f"{len(hits)} account(s) via a lookup outside the window")
            )
