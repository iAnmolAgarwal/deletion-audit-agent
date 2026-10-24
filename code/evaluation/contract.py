"""The output contract as data: statuses, phases, the operation table and step keys.

Source: the operation table in ``problem_statement.md`` (organiser text, untrusted). It is
used here because G1 confirmed it on DEV (``notes/CONTRACT_DRAFT.md`` F05, F07-F12, F26:
all 15 operations carry their tabled phase and state in 134 of 134 DEV steps, and the
phase-then-operation-table order holds in 22 of 22 DEV cases).
"""
from __future__ import annotations

from typing import Any, Mapping

STATUSES: tuple[str, ...] = ("COMPLETE", "INCOMPLETE", "NOT_APPLICABLE")
PHASES: tuple[str, ...] = ("FINDING", "REMEDIATION", "VERIFICATION")
PHASE_RANK: dict[str, int] = {p: i for i, p in enumerate(PHASES)}

STEP_KEYS: tuple[str, ...] = (
    "step_no", "phase", "system_id", "resource_id", "operation", "state", "evidence_id",
)

# operation -> (phase, state), in the table's order; that order is the within-phase sort.
OPERATIONS: dict[str, tuple[str, str]] = {
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
OP_INDEX: dict[str, int] = {op: i for i, op in enumerate(OPERATIONS)}
STATES: frozenset[str] = frozenset(state for _, state in OPERATIONS.values())

# G1 invariant 8 (CONTRACT_DRAFT.md section 3): finding -> allowed remediations,
# remediation -> its verification.
FINDING_TO_REMEDIATION: dict[str, frozenset[str]] = {
    "REPORT_REMAINING_RECORD": frozenset({"DELETE_RECORD"}),
    "REPORT_EXPOSED_PII": frozenset({"REDACT_RECORD", "ANONYMIZE_RECORD"}),
    "REPORT_ACTIVE_DATA_FLOW": frozenset({"DISABLE_DATA_FLOW"}),
    "REPORT_RESTORE_RISK": frozenset({"BLOCK_RESTORE"}),
}
REMEDIATION_TO_VERIFICATION: dict[str, str] = {
    "DELETE_RECORD": "VERIFY_RECORD_ABSENT",
    "REDACT_RECORD": "VERIFY_RECORD_REDACTED",
    "ANONYMIZE_RECORD": "VERIFY_RECORD_ANONYMIZED",
    "DISABLE_DATA_FLOW": "VERIFY_DATA_FLOW_DISABLED",
    "BLOCK_RESTORE": "VERIFY_RESTORE_BLOCKED",
}

# G1 soft invariant 12 (CONTRACT_DRAFT.md section 2): resource prefix -> DEV gold system_id.
PREFIX_SYSTEM: dict[str, str] = {
    "account": "account_service",
    "audit_record": "security_service",
    "export": "export_service",
    "support": "support_platform",
    "data_flow": "integration_service",
    "search": "search_service",
    "analytics": "analytics_platform",
    "backup": "backup_service",
    "tombstone": "identity_service",
}


def step_key(step: Any) -> tuple[Any, ...]:
    """The step-matching key: (phase, operation, system_id, resource_id).

    A non-dict step gets a key that can never match a real step.
    """
    if not isinstance(step, Mapping):
        return ("<not-an-object>", repr(step), "", "")
    return (step.get("phase"), step.get("operation"), step.get("system_id"), step.get("resource_id"))


def sort_key(step: Mapping[str, Any]) -> tuple[int, int, str, str]:
    """The spec order: phase rank, operation-table index, system_id, resource_id (plain string).

    ``resource_id`` uses plain string order: G1 ambiguity A3, reading (a). The alternative,
    numeric-suffix order, is ill-defined for zero-padded IDs and untestable on DEV.
    """
    return (
        PHASE_RANK.get(str(step.get("phase")), 99),
        OP_INDEX.get(str(step.get("operation")), 99),
        str(step.get("system_id")),
        str(step.get("resource_id")),
    )


def resource_prefix(resource_id: str) -> str:
    """``audit_record_6645`` -> ``audit_record``; ``account_005`` -> ``account``."""
    head, _, tail = resource_id.rpartition("_")
    return head if head and tail.isdigit() else resource_id
