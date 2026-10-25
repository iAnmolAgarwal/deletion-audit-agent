"""Coherence checks on any output file. They report violations and never fix them.

The rule numbers follow G1's hard invariants in ``notes/CONTRACT_DRAFT.md`` section 3
(each held on 22 of 22 DEV cases there). "hard" rules come from the spec text confirmed on
DEV. "soft" rules are empirical DEV regularities (G1 11-15); they are warnings, because a
correct test row could break one.

Hard:
  H01 header; H02 status enum; H03 steps_json is a JSON list and status <-> steps
  (NOT_APPLICABLE <=> [], INCOMPLETE <=> at least one FINDING plus remediation and
  verification, COMPLETE <=> non-empty and VERIFICATION only); H04 exactly the 7 keys,
  int ``step_no`` equal to its 1-based position, other values strings; H05 operation in
  the table with its tabled phase and state; H06 spec order; H07 no duplicate step key and
  at most one operation per resource per phase; H08 INCOMPLETE finding <-> remediation
  <-> verification mapping; H09 evidence by status and phase; H10 every non-empty
  evidence ID exists and was captured at or before ``audit_at``; H16 one row per expected
  case, sorted.
Soft:
  S10 evidence cites an activity or audit ID (allowed by the spec, never seen in DEV);
  S11 more than one cited file in a case; S12 system_id differs from the DEV prefix map;
  S13 a non-NA case without VERIFY_RECORD_ABSENT on account_service; S15 a backup with
  VERIFY_RECORD_PRESENT.
"""
from __future__ import annotations

import csv
import datetime as dt
import re
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .contract import (
    FINDING_TO_REMEDIATION,
    OPERATIONS,
    PREFIX_SYSTEM,
    REMEDIATION_TO_VERIFICATION,
    STATUSES,
    STEP_KEYS,
    hashable,
    resource_prefix,
    sort_key,
    step_key,
)
from .outputs import OUTPUT_HEADER, OutputFile, OutputRow, case_label, is_case_name
from .paths import EVIDENCE_MANIFEST, SYSTEM_ACTIVITY, USER_AUDIT_LOG


@dataclass(frozen=True)
class Violation:
    """One broken rule: where, which rule, how bad, and what was seen."""

    case_id: str
    rule: str
    severity: str        # "hard" | "soft"
    detail: str
    step_no: Any = None  # the step's 1-based position in steps_json, never a cell value


def parse_time(value: str) -> dt.datetime:
    """Parse an ISO-8601 UTC timestamp such as ``2026-09-15T11:59:39Z``."""
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


@dataclass(frozen=True)
class EvidenceIndex:
    """Citable IDs with their capture or event times."""

    files: dict[str, dt.datetime]
    activities: dict[str, dt.datetime]
    audits: dict[str, dt.datetime]


def load_evidence_index(manifest: Path = EVIDENCE_MANIFEST, activity: Path = SYSTEM_ACTIVITY,
                        audit_log: Path = USER_AUDIT_LOG) -> EvidenceIndex:
    """Load file_id -> captured_at, activity_id -> event_time, audit_id -> event_time."""
    def read(path: Path, key: str, time_col: str) -> dict[str, dt.datetime]:
        with path.open(newline="", encoding="utf-8") as f:
            return {r[key]: parse_time(r[time_col]) for r in csv.DictReader(f)}
    return EvidenceIndex(read(manifest, "file_id", "captured_at"),
                         read(activity, "activity_id", "event_time"),
                         read(audit_log, "audit_id", "event_time"))


def _numeric_key(case_id: str) -> tuple[int, str]:
    m = re.search(r"(\d+)$", case_id)
    return (int(m.group(1)) if m else -1, case_id)


def check_file(out: OutputFile, *, audit_at: Mapping[str, str], evidence: EvidenceIndex,
               expected_ids: Iterable[str] | None = None) -> list[Violation]:
    """Check a whole output file: file-level rules, then every row."""
    v: list[Violation] = []
    if out.header != OUTPUT_HEADER:
        v.append(Violation("<file>", "H01", "hard", f"header: not {','.join(OUTPUT_HEADER)}"))
    for issue in out.issues:
        if not issue.startswith("header"):
            hard = any(w in issue for w in ("duplicate", "fields", "CSV error", "invalid UTF-8"))
            v.append(Violation("<file>", "H16", "hard" if hard else "soft", issue))
    if expected_ids is not None:
        exp = set(expected_ids)
        got = set(out.rows)
        for k, cid in enumerate(sorted(exp - got), start=1):
            v.append(Violation(cid if is_case_name(cid) else f"<expected case {k}>", "H16", "hard",
                               "expected case has no row"))
        for cid in sorted(got - exp, key=lambda c: out.record_no.get(c, 0)):
            v.append(Violation(case_label(cid, out.record_no.get(cid)), "H16", "hard",
                               "row for a case that is not expected"))
    if out.order not in (sorted(out.order), sorted(out.order, key=_numeric_key)):
        v.append(Violation("<file>", "H16", "hard", "rows are sorted neither by string nor by numeric case_id"))
    elif out.order != sorted(out.order):
        v.append(Violation("<file>", "H16", "soft",
                           "rows are in numeric, not string, case_id order (G1 A1, unsettled)"))
    for cid in out.order:
        v.extend(check_row(out.rows[cid], audit_at=audit_at.get(cid), evidence=evidence,
                           label=case_label(cid, out.record_no.get(cid))))
    return v



@dataclass
class RowChecks:
    """One row under check: its parsed steps, its status (if valid) and the violations found.

    Each named check below reads this and appends to ``found`` through :meth:`add`. Messages name
    the case, the column, the step position and the field, never a cell value (T51 in
    ``code/docs/DECISIONS.md``).
    """

    cid: str
    row: OutputRow
    steps: list[Any]
    audit_at: str | None
    evidence: EvidenceIndex
    found: list[Violation] = field(default_factory=list)

    @property
    def objs(self) -> list[tuple[int, dict[str, Any]]]:
        """The steps that are JSON objects, with their 1-based positions."""
        return [(i, s) for i, s in enumerate(self.steps, start=1) if isinstance(s, dict)]

    @property
    def status(self) -> str | None:
        """The row's status when it is one of the three; else None (never echoed)."""
        return self.row.status if self.row.status in STATUSES else None

    def add(self, rule: str, detail: str, pos: Any = None, severity: str = "hard") -> None:
        """Record one violation on this row."""
        self.found.append(Violation(self.cid, rule, severity, detail, pos))


def _at(pos: int, fld: str | None = None) -> str:
    return f"steps_json step {pos}" + (f" field {fld}" if fld else "")


def check_step_shape(r: RowChecks) -> None:
    """H04: every step is an object with exactly the 7 keys, ``step_no`` is the int equal to its
    1-based position, and the other six values are strings.

    Reason: the spec's step schema, held on 22 of 22 DEV cases (CONTRACT_DRAFT section 3, item 4);
    a scorer that parses ``steps_json`` cannot match a step whose keys or types differ.
    """
    for i, s in enumerate(r.steps, start=1):
        if not isinstance(s, dict):
            r.add("H04", f"{_at(i)}: a JSON {type(s).__name__}, not an object", i)
            continue
        keys = set(s)
        if keys != set(STEP_KEYS):
            r.add("H04", f"{_at(i)}: keys missing {sorted(set(STEP_KEYS) - keys)}, "
                         f"{len(keys - set(STEP_KEYS))} unexpected key(s)", i)
        sn = s.get("step_no")
        if not (isinstance(sn, int) and not isinstance(sn, bool)) or sn != i:
            r.add("H04", f"{_at(i, 'step_no')}: must be the int {i} (its position)", i)
        for k in STEP_KEYS[1:]:
            if k in s and not isinstance(s[k], str):
                r.add("H04", f"{_at(i, k)}: a JSON {type(s[k]).__name__}, not a string", i)


def check_operation_enums(r: RowChecks) -> None:
    """H05: ``operation`` is in the operation table, and ``phase`` and ``state`` are that
    operation's tabled values.

    Reason: the spec fixes one phase and one state per operation (CONTRACT_DRAFT section 3,
    item 5; 22 of 22 DEV cases), so any other pair is an invalid enum, not a judgement call.
    """
    for i, s in r.objs:
        op = s.get("operation")
        if not isinstance(op, str) or op not in OPERATIONS:
            r.add("H05", f"{_at(i, 'operation')}: not in the operation table", i)
            continue
        phase, state = OPERATIONS[op]
        if s.get("phase") != phase:
            r.add("H05", f"{_at(i, 'phase')}: not the operation's tabled phase", i)
        if s.get("state") != state:
            r.add("H05", f"{_at(i, 'state')}: not the operation's tabled state", i)


def check_status_steps(r: RowChecks) -> None:
    """H03: status and steps agree. NOT_APPLICABLE has ``[]``; COMPLETE and INCOMPLETE are
    non-empty; COMPLETE holds VERIFICATION steps only; INCOMPLETE holds at least one FINDING,
    REMEDIATION and VERIFICATION step; any FINDING makes the status INCOMPLETE.

    Reason: steps are the source of truth and status is derived from them (``../CLAUDE.md``
    section 3; CONTRACT_DRAFT section 3, item 3). A FAILED_CLOSED row reports H03 by design (T86).
    The status names below are the rule's own vocabulary; a status value is named only after it
    has been checked to be one of them.
    """
    phases = Counter(hashable(s.get("phase")) for _, s in r.objs)
    status, steps = r.status, r.steps
    if status == "NOT_APPLICABLE" and steps:
        r.add("H03", f"deletion_status/steps_json: NOT_APPLICABLE must have [], has {len(steps)} step(s)")
    if status in ("COMPLETE", "INCOMPLETE") and not steps:
        r.add("H03", f"deletion_status/steps_json: {status} with [] (only NOT_APPLICABLE may be empty)")
    if status == "COMPLETE":
        other = sum(n for p, n in phases.items() if p != "VERIFICATION")
        if other:
            r.add("H03", f"deletion_status/steps_json: COMPLETE must hold only VERIFICATION steps; "
                         f"{other} step(s) have another phase")
    if status == "INCOMPLETE":
        for p in ("FINDING", "REMEDIATION", "VERIFICATION"):
            if not phases.get(p):
                r.add("H03", f"deletion_status/steps_json: INCOMPLETE without any {p} step")
    if phases.get("FINDING") and status != "INCOMPLETE":
        r.add("H03", f"deletion_status/steps_json: {phases['FINDING']} FINDING step(s), but the status is not "
                     "INCOMPLETE (findings imply INCOMPLETE)")


def check_spec_order(r: RowChecks) -> None:
    """H06: each step sorts at or after the one before it by (phase rank, operation-table index,
    ``system_id``, ``resource_id``).

    Reason: the spec's sort order, held on 22 of 22 DEV cases (CONTRACT_DRAFT section 3, item 6);
    an exact-row or exact-order scorer counts any other order as wrong.
    """
    objs = r.objs
    for (_, a), (i, b) in zip(objs, objs[1:], strict=False):
        if sort_key(b) < sort_key(a):
            r.add("H06", f"{_at(i)}: out of spec order (phase, operation table, system_id, resource_id)", i)


def check_duplicates(r: RowChecks) -> None:
    """H07: no two steps share the key (phase, operation, system_id, resource_id), and no resource
    gets more than one operation within one phase.

    Reason: CONTRACT_DRAFT section 3, item 7 (22 of 22 DEV cases); a duplicate key would be
    matched once and counted as an extra step by the step-level scorer.
    """
    by_key: dict[Any, list[int]] = {}
    by_slot: dict[Any, list[int]] = {}
    for i, s in r.objs:
        by_key.setdefault(step_key(s), []).append(i)
        by_slot.setdefault(tuple(hashable(s.get(k)) for k in ("phase", "system_id", "resource_id")), []).append(i)
    for pos in by_key.values():
        if len(pos) > 1:
            r.add("H07", f"steps_json steps {pos}: the same (phase, operation, system_id, resource_id) key", pos[0])
    for pos in by_slot.values():
        if len(pos) > 1:
            r.add("H07", f"steps_json steps {pos}: {len(pos)} operations on one resource in one phase", pos[0])


def check_finding_mapping(r: RowChecks) -> None:
    """H08 (INCOMPLETE only): on each (system_id, resource_id), every FINDING has its matching
    REMEDIATION, every REMEDIATION has its FINDING, and every REMEDIATION has its VERIFICATION
    (``contract.FINDING_TO_REMEDIATION`` and ``REMEDIATION_TO_VERIFICATION``).

    Reason: the spec's finding, remediation and verification tables, held on 22 of 22 DEV cases
    (CONTRACT_DRAFT section 3, item 8); a broken chain is a plan that leaves a finding unfixed or
    an action unverified.
    """
    if r.status != "INCOMPLETE":
        return
    by_res: dict[tuple[Any, Any], dict[str, list[tuple[int, str]]]] = {}
    for i, s in r.objs:
        by_res.setdefault((hashable(s.get("system_id")), hashable(s.get("resource_id"))), {}).setdefault(
            str(s.get("phase")), []).append((i, str(s.get("operation"))))
    for phase_ops in by_res.values():
        fs, rs = phase_ops.get("FINDING", []), phase_ops.get("REMEDIATION", [])
        f_ops, r_ops = [o for _, o in fs], [o for _, o in rs]
        v_ops = [o for _, o in phase_ops.get("VERIFICATION", [])]
        for i, f_op in fs:
            if not any(x in FINDING_TO_REMEDIATION.get(f_op, ()) for x in r_ops):
                r.add("H08", f"{_at(i)}: a finding with no matching remediation on its resource", i)
        for i, r_op in rs:
            if not any(r_op in FINDING_TO_REMEDIATION.get(f, ()) for f in f_ops):
                r.add("H08", f"{_at(i)}: a remediation with no matching finding on its resource", i)
            if REMEDIATION_TO_VERIFICATION.get(r_op) not in v_ops:
                r.add("H08", f"{_at(i)}: a remediation without its verification on its resource", i)


def check_evidence_by_phase(r: RowChecks) -> None:
    """H09: FINDING cites evidence; REMEDIATION has ``""``; VERIFICATION has ``""`` in an
    INCOMPLETE case and cites evidence in a COMPLETE case.

    Reason: the spec's evidence rules per status and phase, held on 22 of 22 DEV cases
    (CONTRACT_DRAFT section 3, item 9; ``../CLAUDE.md`` section 3): a step after remediation has no
    evidence yet, and a COMPLETE claim must point at what shows it.
    """
    status = r.status
    for i, s in r.objs:
        ev, ph = s.get("evidence_id"), s.get("phase")
        if ph == "FINDING" and not ev:
            r.add("H09", f"{_at(i, 'evidence_id')}: empty on a FINDING step", i)
        if ph == "REMEDIATION" and ev != "":
            r.add("H09", f"{_at(i, 'evidence_id')}: must be \"\" on a REMEDIATION step", i)
        if ph == "VERIFICATION" and status == "INCOMPLETE" and ev != "":
            r.add("H09", f"{_at(i, 'evidence_id')}: must be \"\" on a VERIFICATION step of an INCOMPLETE case", i)
        if ph == "VERIFICATION" and status == "COMPLETE" and not ev:
            r.add("H09", f"{_at(i, 'evidence_id')}: empty on a VERIFICATION step of a COMPLETE case", i)


def check_evidence_times(r: RowChecks) -> None:
    """H10: every non-empty ``evidence_id`` exists in the evidence manifest, activity table or audit
    log, and its capture or event time is at or before the case's ``audit_at``. S10 (soft): an
    activity or audit ID is cited instead of a file ID. Soft H10: no ``audit_at`` is known, so
    capture times cannot be checked.

    Reason: evidence IDs are copied from the index, never composed, and evidence after
    ``audit_at`` cannot support the state at ``audit_at`` (``../CLAUDE.md`` section 3;
    CONTRACT_DRAFT section 3, item 10). Activity and audit IDs are allowed by the spec but DEV
    cites files only (CONTRACT_DRAFT A10), so they are a warning.
    """
    objs = r.objs
    cutoff = parse_time(r.audit_at) if r.audit_at else None
    if cutoff is None and any(s.get("evidence_id") for _, s in objs):
        r.add("H10", "no audit_at known for this case; capture times not checked", severity="soft")
    for i, s in objs:
        ev = s.get("evidence_id")
        if not ev or not isinstance(ev, str):
            continue
        if ev in r.evidence.files:
            t = r.evidence.files[ev]
        elif ev in r.evidence.activities or ev in r.evidence.audits:
            t = r.evidence.activities.get(ev) or r.evidence.audits[ev]
            r.add("S10", f"{_at(i, 'evidence_id')}: an activity or audit ID, not a file_id (allowed by the spec; "
                         "DEV cites files only, G1 A10)", i, "soft")
        else:
            r.add("H10", f"{_at(i, 'evidence_id')}: in no manifest, activity or audit table", i)
            continue
        if cutoff is not None and t > cutoff:
            r.add("H10", f"{_at(i, 'evidence_id')}: dated after the case's audit_at", i)


def check_dev_regularities(r: RowChecks) -> None:
    """Soft S11, S12, S15, S13: more than one cited evidence ID in a case (S11); a ``system_id``
    that differs from the DEV resource-prefix map (S12); a backup verified PRESENT (S15); a
    COMPLETE or INCOMPLETE case without VERIFY_RECORD_ABSENT on ``account_service`` (S13).

    Reason: these are empirical DEV regularities (CONTRACT_DRAFT section 3, items 11, 12, 13 and
    15), not spec rules, so a correct test row could break one: they are warnings for a human to
    read, never hard failures.
    """
    objs = r.objs
    cited_files = {hashable(s.get("evidence_id")) for _, s in objs if s.get("evidence_id")}
    if len(cited_files) > 1:
        r.add("S11", f"steps_json: {len(cited_files)} distinct evidence IDs cited", severity="soft")
    for i, s in objs:
        rid, sysid = s.get("resource_id"), s.get("system_id")
        if isinstance(rid, str):
            want = PREFIX_SYSTEM.get(resource_prefix(rid))
            if want and sysid != want:
                r.add("S12", f"{_at(i, 'system_id')}: differs from the DEV prefix map for its resource_id", i, "soft")
            if resource_prefix(rid) == "backup" and s.get("operation") == "VERIFY_RECORD_PRESENT":
                r.add("S15", f"{_at(i)}: a backup resource verified PRESENT (DEV backups are only blocked)", i, "soft")
    if r.status in ("COMPLETE", "INCOMPLETE") and not any(
            s.get("operation") == "VERIFY_RECORD_ABSENT" and s.get("system_id") == "account_service" for _, s in objs):
        r.add("S13", "steps_json: no VERIFY_RECORD_ABSENT on account_service (22 of 22 DEV cases have one)",
              severity="soft")


def check_status_enum(r: RowChecks) -> None:
    """H02: ``deletion_status`` is COMPLETE, INCOMPLETE or NOT_APPLICABLE.

    Reason: the spec's three statuses (CONTRACT_DRAFT section 3, item 2); any other value is
    unscoreable at case level. The value itself is never echoed (T51).
    """
    if r.row.status not in STATUSES:
        r.add("H02", f"deletion_status: not one of {', '.join(STATUSES)}")


ROW_CHECKS: tuple[Callable[[RowChecks], None], ...] = (
    check_step_shape, check_operation_enums, check_status_steps, check_spec_order, check_duplicates,
    check_finding_mapping, check_evidence_by_phase, check_evidence_times, check_dev_regularities,
)
"""The named checks on a parsed row, in the order :func:`check_row` runs them (and lists violations)."""


def check_row(row: OutputRow, *, audit_at: str | None, evidence: EvidenceIndex,
              label: str | None = None) -> list[Violation]:
    """Check one row: H02 (status enum), H03 (steps_json parses to a list), then :data:`ROW_CHECKS`.

    H02 and the parse half of H03 come first because every later check needs a known status or a
    parsed list; a row whose ``steps_json`` does not parse gets no other step check, since there
    are no steps to read. Messages name the case, the column, the step position and the field,
    never a cell value (T51): a prediction file, or a file passed by mistake, may hold personal
    data, and coherence output is printed and stored. ``Violation.step_no`` is the step's 1-based
    position in the list, not the value of its ``step_no`` field. The case is named by ``label``
    (from :func:`outputs.case_label`) or, without one, by its ``case_id`` only when that is a case
    name (T72 note 1). T-numbers point to ``code/docs/DECISIONS.md``.
    """
    cid = label if label is not None else case_label(row.case_id, None)
    if row.steps is None:
        r = RowChecks(cid, row, [], audit_at, evidence)
        check_status_enum(r)
        kind = "invalid JSON" if (row.parse_error or "").startswith("invalid JSON") else "valid JSON but not a list"
        r.add("H03", f"steps_json: does not parse to a JSON list ({kind})")
        return r.found
    r = RowChecks(cid, row, row.steps, audit_at, evidence)
    check_status_enum(r)
    for check in ROW_CHECKS:
        check(r)
    return r.found


def summarize(violations: list[Violation]) -> dict[str, Any]:
    """Counts by severity and rule, the offending cases, and every violation."""
    by_rule = Counter((x.severity, x.rule) for x in violations)
    return {
        "hard": sum(1 for x in violations if x.severity == "hard"),
        "soft": sum(1 for x in violations if x.severity == "soft"),
        "by_rule": {f"{sev}:{rule}": n for (sev, rule), n in sorted(by_rule.items())},
        "hard_cases": sorted({x.case_id for x in violations if x.severity == "hard"}),
        "violations": [asdict(x) for x in violations],
    }


def format_report(violations: list[Violation]) -> str:
    """Human-readable listing of every offending row, hard rules first."""
    if not violations:
        return "coherence: 0 violations"
    lines = [f"coherence: {sum(x.severity == 'hard' for x in violations)} hard, "
             f"{sum(x.severity == 'soft' for x in violations)} soft"]
    for x in sorted(violations, key=lambda x: (x.severity != "hard", x.case_id, x.rule)):
        at = f" step {x.step_no}" if x.step_no is not None else ""
        lines.append(f"  [{x.severity.upper()} {x.rule}] {x.case_id}{at}: {x.detail}")
    return "\n".join(lines)
