"""The output contract as data: operations, their phase and state, and the step order.

Basis: the operation table and order are organiser text confirmed on DEV (``notes/CONTRACT_DRAFT.md``
F07-F12: all 15 operations carry their tabled phase and state in 134/134 DEV steps; phase, then
operation-table order, then ``system_id`` holds in 22/22 DEV cases).

``resource_id`` ties sort as plain strings: ``notes/CONTRACT_DRAFT.md`` A3 reading (a), the same
order as research/15 R16 and ``code/evaluation/contract.sort_key``. DEV has no tie that tests it
(F13), so it is the contract's stated "ascending" read literally; a numeric-suffix order is
ill-defined for zero-padded IDs.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

Phase = Literal["FINDING", "REMEDIATION", "VERIFICATION"]
PHASES: tuple[str, ...] = ("FINDING", "REMEDIATION", "VERIFICATION")
PHASE_RANK: Mapping[str, int] = {p: i for i, p in enumerate(PHASES)}

#: operation -> (phase, state), in the table's order (that order is the within-phase sort).
OPERATIONS: Mapping[str, tuple[str, str]] = {
    "REPORT_REMAINING_RECORD": ("FINDING", "PRESENT"),
    "REPORT_EXPOSED_PII": ("FINDING", "PRESENT"),
    "REPORT_ACTIVE_DATA_FLOW": ("FINDING", "ACTIVE"),
    "REPORT_RESTORE_RISK": ("FINDING", "ACTIVE"),
    "DISABLE_DATA_FLOW": ("REMEDIATION", "DISABLED"),
    "BLOCK_RESTORE": ("REMEDIATION", "BLOCKED"),
    "DELETE_RECORD": ("REMEDIATION", "ABSENT"),
    "REDACT_RECORD": ("REMEDIATION", "REDACTED"),
    "ANONYMIZE_RECORD": ("REMEDIATION", "ANONYMIZED"),
    "VERIFY_RECORD_ABSENT": ("VERIFICATION", "ABSENT"),
    "VERIFY_RECORD_PRESENT": ("VERIFICATION", "PRESENT"),
    "VERIFY_RECORD_REDACTED": ("VERIFICATION", "REDACTED"),
    "VERIFY_RECORD_ANONYMIZED": ("VERIFICATION", "ANONYMIZED"),
    "VERIFY_DATA_FLOW_DISABLED": ("VERIFICATION", "DISABLED"),
    "VERIFY_RESTORE_BLOCKED": ("VERIFICATION", "BLOCKED"),
}
OP_INDEX: Mapping[str, int] = {op: i for i, op in enumerate(OPERATIONS)}

#: G1 invariant 8 (``notes/CONTRACT_DRAFT.md`` section 3, F26: 15/15 INCOMPLETE DEV cases).
FINDING_TO_REMEDIATION: Mapping[str, frozenset[str]] = {
    "REPORT_REMAINING_RECORD": frozenset({"DELETE_RECORD"}),
    "REPORT_EXPOSED_PII": frozenset({"REDACT_RECORD", "ANONYMIZE_RECORD"}),
    "REPORT_ACTIVE_DATA_FLOW": frozenset({"DISABLE_DATA_FLOW"}),
    "REPORT_RESTORE_RISK": frozenset({"BLOCK_RESTORE"}),
}
REMEDIATION_TO_VERIFICATION: Mapping[str, str] = {
    "DELETE_RECORD": "VERIFY_RECORD_ABSENT",
    "REDACT_RECORD": "VERIFY_RECORD_REDACTED",
    "ANONYMIZE_RECORD": "VERIFY_RECORD_ANONYMIZED",
    "DISABLE_DATA_FLOW": "VERIFY_DATA_FLOW_DISABLED",
    "BLOCK_RESTORE": "VERIFY_RESTORE_BLOCKED",
}
#: Verifications that state a record still exists (T66 hard check applies when cited).
EXISTS_VERIFICATIONS: frozenset[str] = frozenset({"VERIFY_RECORD_PRESENT"})
#: Verifications under flag-and-count, not hard (T71 Q4).
FLAG_VERIFICATIONS: frozenset[str] = frozenset(
    {"VERIFY_RECORD_REDACTED", "VERIFY_RECORD_ANONYMIZED", "VERIFY_DATA_FLOW_DISABLED", "VERIFY_RESTORE_BLOCKED"}
)


def step_sort_key(phase: str, operation: str, system_id: str, resource_id: str) -> tuple[int, int, str, str]:
    """Phase rank, operation-table index, ``system_id``, ``resource_id`` (plain string, module docstring)."""
    return (PHASE_RANK[phase], OP_INDEX[operation], system_id, resource_id)
