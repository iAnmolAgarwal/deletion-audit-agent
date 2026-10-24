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
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from .contract import (FINDING_TO_REMEDIATION, OPERATIONS, PREFIX_SYSTEM, REMEDIATION_TO_VERIFICATION,
                       STATUSES, STEP_KEYS, resource_prefix, sort_key, step_key)
from .outputs import OUTPUT_HEADER, OutputFile, OutputRow
from .paths import EVIDENCE_MANIFEST, SYSTEM_ACTIVITY, USER_AUDIT_LOG


@dataclass(frozen=True)
class Violation:
    """One broken rule: where, which rule, how bad, and what was seen."""

    case_id: str
    rule: str
    severity: str        # "hard" | "soft"
    detail: str
    step_no: Any = None


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
        v.append(Violation("<file>", "H01", "hard", f"header {out.header!r}"))
    for issue in out.issues:
        if not issue.startswith("header"):
            v.append(Violation("<file>", "H16", "hard" if "duplicate" in issue or "fields" in issue else "soft", issue))
    if expected_ids is not None:
        exp = set(expected_ids)
        got = set(out.rows)
        for cid in sorted(exp - got):
            v.append(Violation(cid, "H16", "hard", "expected case has no row"))
        for cid in sorted(got - exp):
            v.append(Violation(cid, "H16", "hard", "row for a case that is not expected"))
    if out.order not in (sorted(out.order), sorted(out.order, key=_numeric_key)):
        v.append(Violation("<file>", "H16", "hard", "rows are sorted neither by string nor by numeric case_id"))
    elif out.order != sorted(out.order):
        v.append(Violation("<file>", "H16", "soft", "rows are in numeric, not string, case_id order (G1 A1, unsettled)"))
    for cid in out.order:
        v.extend(check_row(out.rows[cid], audit_at=audit_at.get(cid), evidence=evidence))
    return v


def check_row(row: OutputRow, *, audit_at: str | None, evidence: EvidenceIndex) -> list[Violation]:
    """Check one row against H02-H10 and the soft rules."""
    cid = row.case_id
    v: list[Violation] = []

    def add(rule: str, detail: str, step_no: Any = None, severity: str = "hard") -> None:
        v.append(Violation(cid, rule, severity, detail, step_no))

    if row.status not in STATUSES:
        add("H02", f"status {row.status!r} is not one of {STATUSES}")
    if row.steps is None:
        add("H03", f"steps_json does not parse to a list: {row.parse_error}")
        return v
    steps = row.steps
    objs = [s for s in steps if isinstance(s, dict)]

    # H04 shape
    for i, s in enumerate(steps, start=1):
        if not isinstance(s, dict):
            add("H04", f"step {i} is a JSON {type(s).__name__}, not an object", i)
            continue
        keys = set(s)
        if keys != set(STEP_KEYS):
            add("H04", f"keys missing {sorted(set(STEP_KEYS) - keys)} extra {sorted(keys - set(STEP_KEYS))}", s.get("step_no"))
        sn = s.get("step_no")
        if not (isinstance(sn, int) and not isinstance(sn, bool)) or sn != i:
            add("H04", f"step_no {sn!r} at position {i} (must be the int {i})", sn)
        for k in STEP_KEYS[1:]:
            if k in s and not isinstance(s[k], str):
                add("H04", f"{k} is {type(s[k]).__name__}, not a string", sn)

    # H05 enums
    for s in objs:
        op = s.get("operation")
        if op not in OPERATIONS:
            add("H05", f"operation {op!r} is not in the table", s.get("step_no"))
            continue
        phase, state = OPERATIONS[op]
        if s.get("phase") != phase:
            add("H05", f"{op} must have phase {phase}, has {s.get('phase')!r}", s.get("step_no"))
        if s.get("state") != state:
            add("H05", f"{op} must have state {state}, has {s.get('state')!r}", s.get("step_no"))

    # H03 status <-> steps
    phases = Counter(s.get("phase") for s in objs)
    if row.status == "NOT_APPLICABLE" and steps:
        add("H03", f"NOT_APPLICABLE must be [], has {len(steps)} steps")
    if row.status != "NOT_APPLICABLE" and not steps and row.status in STATUSES:
        add("H03", f"{row.status} with [] (only NOT_APPLICABLE may be empty)")
    if row.status == "COMPLETE" and any(p != "VERIFICATION" for p in phases):
        add("H03", f"COMPLETE must hold only VERIFICATION steps, has {dict(phases)}")
    if row.status == "INCOMPLETE":
        for p in ("FINDING", "REMEDIATION", "VERIFICATION"):
            if not phases.get(p):
                add("H03", f"INCOMPLETE without any {p} step")
    if phases.get("FINDING") and row.status != "INCOMPLETE":
        add("H03", f"{row.status} has {phases['FINDING']} FINDING step(s); findings imply INCOMPLETE")

    # H06 order
    keys_in_order = [sort_key(s) for s in objs]
    for a, b, s in zip(keys_in_order, keys_in_order[1:], objs[1:]):
        if b < a:
            add("H06", f"step out of spec order: {list(step_key(s))}", s.get("step_no"))

    # H07 duplicates
    for k, n in Counter(step_key(s) for s in objs).items():
        if n > 1:
            add("H07", f"duplicate step key {list(k)} x{n}")
    for (phase, sysid, rid), n in Counter((s.get("phase"), s.get("system_id"), s.get("resource_id")) for s in objs).items():
        if n > 1:
            add("H07", f"{sysid}/{rid} has {n} operations in {phase}")

    # H08 F <-> R <-> V mapping (INCOMPLETE only)
    if row.status == "INCOMPLETE":
        by_res: dict[tuple[Any, Any], dict[str, list[str]]] = {}
        for s in objs:
            by_res.setdefault((s.get("system_id"), s.get("resource_id")), {}).setdefault(str(s.get("phase")), []).append(str(s.get("operation")))
        for (sysid, rid), ph in sorted(by_res.items(), key=str):
            fs, rs, vs = ph.get("FINDING", []), ph.get("REMEDIATION", []), ph.get("VERIFICATION", [])
            for f_op in fs:
                if not any(r in FINDING_TO_REMEDIATION.get(f_op, ()) for r in rs):
                    add("H08", f"finding {f_op} on {sysid}/{rid} has no matching remediation")
            for r_op in rs:
                if not any(r_op in FINDING_TO_REMEDIATION.get(f, ()) for f in fs):
                    add("H08", f"remediation {r_op} on {sysid}/{rid} has no matching finding")
                if REMEDIATION_TO_VERIFICATION.get(r_op) not in vs:
                    add("H08", f"remediation {r_op} on {sysid}/{rid} lacks {REMEDIATION_TO_VERIFICATION.get(r_op)}")

    # H09 evidence by status and phase
    for s in objs:
        ev, ph, sn = s.get("evidence_id"), s.get("phase"), s.get("step_no")
        if ph == "FINDING" and not ev:
            add("H09", "FINDING without evidence_id", sn)
        if ph == "REMEDIATION" and ev != "":
            add("H09", f"REMEDIATION must use \"\", has {ev!r}", sn)
        if ph == "VERIFICATION" and row.status == "INCOMPLETE" and ev != "":
            add("H09", f"INCOMPLETE VERIFICATION must use \"\", has {ev!r}", sn)
        if ph == "VERIFICATION" and row.status == "COMPLETE" and not ev:
            add("H09", "COMPLETE VERIFICATION without evidence_id", sn)

    # H10 evidence exists, captured at or before audit_at
    cutoff = parse_time(audit_at) if audit_at else None
    if cutoff is None and any(s.get("evidence_id") for s in objs):
        add("H10", "no audit_at known for this case; capture times not checked", severity="soft")
    for s in objs:
        ev, sn = s.get("evidence_id"), s.get("step_no")
        if not ev or not isinstance(ev, str):
            continue
        if ev in evidence.files:
            t = evidence.files[ev]
        elif ev in evidence.activities or ev in evidence.audits:
            t = evidence.activities.get(ev) or evidence.audits[ev]
            add("S10", f"cites {ev}, not a file_id (allowed by the spec; DEV cites files only, G1 A10)", sn, "soft")
        else:
            add("H10", f"evidence_id {ev!r} exists in no manifest, activity or audit table", sn)
            continue
        if cutoff is not None and t > cutoff:
            add("H10", f"{ev} is dated {t.isoformat()}, after audit_at {audit_at}", sn)

    # soft DEV regularities
    cited_files = {s.get("evidence_id") for s in objs if s.get("evidence_id")}
    if len(cited_files) > 1:
        add("S11", f"{len(cited_files)} distinct evidence IDs cited: {sorted(map(str, cited_files))}", severity="soft")
    for s in objs:
        rid, sysid = s.get("resource_id"), s.get("system_id")
        if isinstance(rid, str):
            want = PREFIX_SYSTEM.get(resource_prefix(rid))
            if want and sysid != want:
                add("S12", f"{rid} under {sysid!r}; DEV maps this prefix to {want}", s.get("step_no"), "soft")
            if resource_prefix(rid) == "backup" and s.get("operation") == "VERIFY_RECORD_PRESENT":
                add("S15", f"backup {rid} verified PRESENT (DEV backups are only blocked)", s.get("step_no"), "soft")
    if row.status in ("COMPLETE", "INCOMPLETE") and not any(
            s.get("operation") == "VERIFY_RECORD_ABSENT" and s.get("system_id") == "account_service" for s in objs):
        add("S13", "no VERIFY_RECORD_ABSENT on account_service (22 of 22 DEV cases have one)", severity="soft")
    return v


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
