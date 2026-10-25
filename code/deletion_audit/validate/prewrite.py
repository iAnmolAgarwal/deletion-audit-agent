"""Pre-write validator: every row is checked before it is written; it reports, and fails closed.

Checks (``hard`` blocks the row as written; ``flag`` is counted in the run artifacts):

Row and step rules (G1 hard invariants H01-H16, ``notes/CONTRACT_DRAFT.md`` section 3):
  ``STATUS_DERIVED`` the status agrees with the steps, stated on the steps alone and not by calling
  ``derive_status`` again (COMPLETE: at least one step and no FINDING; INCOMPLETE: a FINDING, or a
  FAILED_CLOSED row; NOT_APPLICABLE: no step), so a bug in the derivation is caught; ``NA_EMPTY`` NOT_APPLICABLE
  <=> ``[]`` (a deletion row is never empty); ``ENUM`` operation in the table with its phase and
  state; ``STEP_NO`` 1..n; ``ORDER`` phase, operation, system, resource; ``DUPLICATE`` no repeated
  key and one operation per resource per phase; ``F_R_V`` INCOMPLETE finding <-> remediation <->
  verification; ``COMPLETE_VERIFICATION_ONLY`` a COMPLETE row holds VERIFICATION steps only
  (``../CLAUDE.md`` section 3; G1 H03, which ``code/evaluation/coherence.py`` checks on every
  output file; ``compile_steps`` never builds anything else, so this guards rows edited later).
Row rules of T77 (DEV 53/53, 23/23, 29/29): ``T77_INCOMPLETE_VERIFICATION_EMPTY``,
  ``T77_COMPLETE_VERIFICATION_CITES``, ``T77_FINDING_CITES``, plus ``REMEDIATION_EMPTY`` (DEV 29/29).
Evidence rules (T66 part 4; G1 F21): ``EVIDENCE_EXISTS`` every cited ID is a file, activity or
  audit ID (an ``audit_id`` is accepted); ``EVIDENCE_TIME`` captured at or before ``audit_at``
  (equality allowed).
Citation content (T66 as amended by T71 Q3/Q4 and T77):
  ``HARD_CONTAINS`` a cited step that says a record still exists (a FINDING, or a cited
  VERIFY_RECORD_PRESENT) cites a file that contains the resource; an alias counts as contained
  when a catalog row at or before ``audit_at`` ties it to the resource (T71 Q3).
  ``ABSENT_BRANCH`` a cited VERIFY_RECORD_ABSENT may cite a file that contains the resource, a
  file whose declared scope covers its system, or a file listing records of its own system; a
  citation meeting none is flagged and counted, never changed.
  ``OTHER_ABSENCE`` cited REDACTED / ANONYMIZED / DATA_FLOW_DISABLED / RESTORE_BLOCKED
  verifications: flag-and-count when the file does not contain the resource (T71 Q4).
Ownership (developer ruling T105, main's safety net on red-team fixture R04):
  ``OWN_KEY_OTHER_PERSON`` (hard) no step names a record whose own key belongs to a known person
  other than the requester (``ValidationContext.resource_own_persons``, built from every
  observation of the record, whatever the file or trace).
``FAILED_CLOSED`` (flag): the row is the enumerated fail-closed class (T71 Q5).

:func:`gate` applies the result: a row with a hard failure keeps every step (a finding is never
dropped), any citation that fails the evidence rules is blanked (a forbidden ID is never written;
T105 on R06 adds ``HARD_CONTAINS``, so a file that does not hold the record is never written as its
evidence), and the row becomes FAILED_CLOSED(VALIDATOR_REFUSED), status INCOMPLETE (a row already
FAILED_CLOSED keeps its own reason). The gated row is validated again; its checks are the first
pass plus only the failures the second pass finds anew, so a failure seen by both passes is counted
once (T105 on R06).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Literal

from .. import timeutil
from ..record import CaseRecord
from ..state.reconstruct import ResourceKey
from ..steps.model import Step
from ..steps.order import (
    EXISTS_VERIFICATIONS,
    FINDING_TO_REMEDIATION,
    FLAG_VERIFICATIONS,
    OPERATIONS,
    REMEDIATION_TO_VERIFICATION,
    step_sort_key,
)

Severity = Literal["hard", "flag"]
STATUSES = ("COMPLETE", "INCOMPLETE", "NOT_APPLICABLE")


@dataclass(frozen=True)
class CheckResult:
    """One check on one row (``step_no`` is None for row-level checks)."""

    rule: str
    severity: Severity
    ok: bool
    step_no: int | None
    detail: str


@dataclass(frozen=True)
class ValidationContext:
    """Facts the validator checks citations against, built once per run."""

    citable_time: Mapping[str, str]  # file_id / activity_id / audit_id -> time
    file_resources: Mapping[str, frozenset[ResourceKey]]  # incl. image-extraction observations
    file_scope_systems: Mapping[str, frozenset[str]]  # declared scopes only (T50)
    file_listed_systems: Mapping[str, frozenset[str]]  # systems with >= 1 record in the file
    file_status: Mapping[str, str]
    file_aliases: Mapping[str, frozenset[str]]  # alias tokens a file names (T71 Q3)
    resource_aliases: Mapping[str, tuple[tuple[str, str], ...]]  # resource -> ((alias, catalog row time), ...)
    activity_resource: Mapping[str, str]  # activity_id -> resource_id
    resource_own_persons: Mapping[str, frozenset[str]] = field(default_factory=dict)  # record -> own-key persons

    def contains(self, cited: str, resource_id: str, audit_at: str) -> bool:
        """The cited file (or activity row) holds the resource, directly or by a timely alias."""
        if cited in self.activity_resource:
            return self.activity_resource[cited] == resource_id
        if any(k.resource_id == resource_id for k in self.file_resources.get(cited, ())):
            return True
        names = self.file_aliases.get(cited, frozenset())
        return any(
            alias in names and timeutil.le(t, audit_at) for alias, t in self.resource_aliases.get(resource_id, ())
        )


def _check(
    out: list[CheckResult], rule: str, ok: bool, detail: str, step_no: int | None = None, severity: Severity = "hard"
) -> None:
    out.append(CheckResult(rule, severity, ok, step_no, detail))


def status_agrees_with_steps(status: str, steps: tuple[Step, ...], failed_closed: str | None) -> bool:
    """The status/steps invariants on the steps alone (``../CLAUDE.md`` section 3; module docstring)."""
    has_finding = any(s.phase == "FINDING" for s in steps)
    if status == "NOT_APPLICABLE":
        return not steps
    if status == "COMPLETE":
        return bool(steps) and not has_finding and failed_closed is None
    return status == "INCOMPLETE" and (has_finding or failed_closed is not None)


def validate_row(record: CaseRecord, ctx: ValidationContext) -> tuple[CheckResult, ...]:
    """Every check of the module docstring on one row. Never edits the row."""
    out: list[CheckResult] = []
    steps, status = record.steps, record.status
    audit_at = record.request.audit_at if record.request is not None else ""
    _check(out, "STATUS_ENUM", status in STATUSES, "status in the enum")
    _check(out, "STATUS_DERIVED", status_agrees_with_steps(status, steps, record.failed_closed),
           "status agrees with the steps")
    if record.failed_closed is None:
        _check(
            out,
            "NA_EMPTY",
            (status == "NOT_APPLICABLE") == (len(steps) == 0),
            "NOT_APPLICABLE exactly when steps are []",
        )
    else:  # a FAILED_CLOSED row may hold no step when nothing citable was found (T71 Q5); never NA
        _check(out, "NA_EMPTY", status != "NOT_APPLICABLE", "a FAILED_CLOSED row is never NOT_APPLICABLE")
    _check(out, "STEP_NO", [s.step_no for s in steps] == list(range(1, len(steps) + 1)), "step_no runs 1..n")
    known = [s for s in steps if s.operation in OPERATIONS]
    for s in steps:
        good = s.operation in OPERATIONS and OPERATIONS[s.operation] == (s.phase, s.state)
        _check(out, "ENUM", good, "operation in the table with its phase and state", s.step_no)
    keys = [step_sort_key(s.phase, s.operation, s.system_id, s.resource_id) for s in known]
    _check(out, "ORDER", keys == sorted(keys), "phase, operation, system_id, resource_id order")
    dup = Counter((s.phase, s.operation, s.system_id, s.resource_id) for s in steps)
    slot = Counter((s.phase, s.system_id, s.resource_id) for s in steps)
    _check(
        out,
        "DUPLICATE",
        max(dup.values(), default=1) == 1 and max(slot.values(), default=1) == 1,
        "no duplicate step and one operation per resource per phase",
    )
    if status == "INCOMPLETE":
        _frv(out, steps)
    if status == "COMPLETE":
        _check(
            out,
            "COMPLETE_VERIFICATION_ONLY",
            all(s.phase == "VERIFICATION" for s in steps),
            "a COMPLETE row holds VERIFICATION steps only",
        )
    for s in steps:
        _evidence_rules(out, s, status, audit_at, ctx)
    requester = {record.identity.person} if record.identity.person else set()
    for s in steps:
        others = ctx.resource_own_persons.get(s.resource_id, frozenset()) - requester
        _check(
            out,
            "OWN_KEY_OTHER_PERSON",
            not others,
            "the step's record has no own key of another known person",
            s.step_no,
        )
    if record.failed_closed is not None:
        _check(out, "FAILED_CLOSED", False, f"row is FAILED_CLOSED({record.failed_closed})", severity="flag")
    return tuple(out)


def _frv(out: list[CheckResult], steps: tuple[Step, ...]) -> None:
    """G1 invariant 8 on an INCOMPLETE row."""
    by_res: dict[tuple[str, str], dict[str, list[str]]] = {}
    for s in steps:
        by_res.setdefault((s.system_id, s.resource_id), {}).setdefault(s.phase, []).append(s.operation)
    for (_system, rid), ph in sorted(by_res.items()):
        fs, rs, vs = ph.get("FINDING", []), ph.get("REMEDIATION", []), ph.get("VERIFICATION", [])
        ok = all(any(r in FINDING_TO_REMEDIATION.get(f, ()) for r in rs) for f in fs)
        ok = ok and all(any(r in FINDING_TO_REMEDIATION.get(f, ()) for f in fs) for r in rs)
        ok = ok and all(REMEDIATION_TO_VERIFICATION.get(r) in vs for r in rs)
        _check(out, "F_R_V", ok, f"finding/remediation/verification correspond on {rid}")


def _evidence_rules(out: list[CheckResult], s: Step, status: str, audit_at: str, ctx: ValidationContext) -> None:
    """T77 row rules, evidence existence and time, and the T66 citation-content checks."""
    ev = s.evidence_id
    if s.phase == "FINDING":
        _check(out, "T77_FINDING_CITES", bool(ev), "a FINDING cites evidence", s.step_no)
    if s.phase == "REMEDIATION":
        _check(out, "REMEDIATION_EMPTY", ev == "", 'a REMEDIATION carries ""', s.step_no)
    if s.phase == "VERIFICATION" and status == "INCOMPLETE":
        _check(out, "T77_INCOMPLETE_VERIFICATION_EMPTY", ev == "", 'an INCOMPLETE verification carries ""', s.step_no)
    if s.phase == "VERIFICATION" and status == "COMPLETE":
        _check(out, "T77_COMPLETE_VERIFICATION_CITES", bool(ev), "a COMPLETE verification cites evidence", s.step_no)
    if not ev:
        return
    exists = ev in ctx.citable_time
    _check(out, "EVIDENCE_EXISTS", exists, "cited ID is a file, activity or audit ID", s.step_no)
    if not exists:
        return
    _check(
        out,
        "EVIDENCE_TIME",
        timeutil.le(ctx.citable_time[ev], audit_at),
        "cited evidence captured at or before audit_at",
        s.step_no,
    )
    contains = ctx.contains(ev, s.resource_id, audit_at)
    if s.phase == "FINDING" or s.operation in EXISTS_VERIFICATIONS:
        _check(out, "HARD_CONTAINS", contains, "a step saying a record exists cites a file containing it", s.step_no)
    elif s.operation == "VERIFY_RECORD_ABSENT":
        branch = (
            contains
            or s.system_id in ctx.file_scope_systems.get(ev, frozenset())
            or s.system_id in ctx.file_listed_systems.get(ev, frozenset())
        )
        _check(
            out,
            "ABSENT_BRANCH",
            branch,
            "absence cited by containment, declared scope or same-system listing",
            s.step_no,
            "flag",
        )
    elif s.operation in FLAG_VERIFICATIONS:
        _check(out, "OTHER_ABSENCE", contains, "the cited file contains the resource", s.step_no, "flag")


def hard_failures(checks: tuple[CheckResult, ...]) -> tuple[CheckResult, ...]:
    """The failed hard checks."""
    return tuple(c for c in checks if c.severity == "hard" and not c.ok)


def gate(record: CaseRecord, ctx: ValidationContext) -> CaseRecord:
    """Validate a row and fail it closed on any hard failure (module docstring). Never drops a step."""
    checks = validate_row(record, ctx)
    bad = hard_failures(checks)
    if not bad:
        return replace(record, checks=checks)
    blank = {
        c.step_no
        for c in bad
        if c.rule in ("EVIDENCE_EXISTS", "EVIDENCE_TIME", "HARD_CONTAINS") and c.step_no is not None
    }
    # the row becomes INCOMPLETE, whose verifications carry "" (T77 rule 1)
    steps = tuple(
        replace(s, evidence_id="") if s.step_no in blank or s.phase == "VERIFICATION" else s for s in record.steps
    )
    failed = replace(record, steps=steps, failed_closed=record.failed_closed or "VALIDATOR_REFUSED")
    seen = {(c.rule, c.step_no) for c in checks if not c.ok}
    again = tuple(c for c in validate_row(failed, ctx) if not c.ok and (c.rule, c.step_no) not in seen)
    return replace(failed, checks=checks + again)
