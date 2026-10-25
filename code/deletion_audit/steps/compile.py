"""Compile a case's records into its ordered steps (the source of truth) and derive its status.

Rules, each with its basis:

* A finding gives three steps: FINDING (cited), REMEDIATION (``""``) and VERIFICATION (``""``).
  A compliant record gives one VERIFICATION. Basis: research/15 R9/R10/R15; G1 F15/F19/F26.
* COMPLETE rows (no finding) cite the case file F on every verification; INCOMPLETE rows leave
  every verification and remediation ``""`` (T77 row rules; DEV 53/53, 23/23, 29/29).
* A validated NOT_DELETION intent gives ``[]`` (G1 F16; spec only, 0 DEV examples).
* A FAILED_CLOSED row (T71 Q5) is INCOMPLETE, so it cites nothing on its verifications.
* Order: phase, operation-table order, ``system_id``, ``resource_id`` (``order.step_sort_key``);
  steps are numbered from 1 (G1 F06, F10-F12).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from .model import CitationPlan, Step
from .order import OPERATIONS, step_sort_key

if TYPE_CHECKING:
    from ..record import IntentDecision, ResourceFinding


def compile_steps(
    intent: IntentDecision, resources: Sequence[ResourceFinding], citation: CitationPlan, *, failed_closed: bool = False
) -> tuple[Step, ...]:
    """The ordered, numbered steps of one case (module docstring).

    A FAILED_CLOSED row is INCOMPLETE (T71 Q5), so its verifications carry ``""`` (T77 rule 1).
    """
    if intent.not_applicable:
        return ()
    raw: list[tuple[str, str, str, str, str]] = []  # (phase, system, resource, operation, evidence)
    findings = [r for r in resources if r.decision.outcome == "FINDING"]
    compliant = [r for r in resources if r.decision.outcome == "COMPLIANT"]
    complete = not findings and not failed_closed
    for r in findings:
        d = r.decision
        if not (d.finding_op and d.remediation_op and d.verification_op):
            raise ValueError(f"finding on {r.key.resource_id} has no operation triple")
        raw.append(("FINDING", r.key.system_id, r.key.resource_id, d.finding_op, r.cite))
        raw.append(("REMEDIATION", r.key.system_id, r.key.resource_id, d.remediation_op, ""))
        raw.append(("VERIFICATION", r.key.system_id, r.key.resource_id, d.verification_op, ""))
    for r in compliant:
        if not r.decision.verification_op:
            raise ValueError(f"compliant {r.key.resource_id} has no verification")
        ev = (citation.file_id or "") if complete else ""
        raw.append(("VERIFICATION", r.key.system_id, r.key.resource_id, r.decision.verification_op, ev))
    raw.sort(key=lambda s: step_sort_key(s[0], s[3], s[1], s[2]))
    return tuple(
        Step(i, p, sysid, rid, op, OPERATIONS[op][1], ev) for i, (p, sysid, rid, op, ev) in enumerate(raw, start=1)
    )
