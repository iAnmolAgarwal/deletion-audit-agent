"""Policy: a record's data category, and what ``deletion_rules.csv`` requires for its state.

Category rules, each with its basis:

* By system: account -> USER_PROFILE (rule_01), search -> SEARCH_INDEX_ENTRY (rule_03), export ->
  USER_EXPORT (rule_09), security -> SECURITY_AUDIT_LOG (rule_12), legal -> LEGAL_HOLD_RECORD
  (rule_13), backup -> BACKUP_ARCHIVE (rule_14), identity -> ACCOUNT_TOMBSTONE (rule_15),
  marketing -> MARKETING_PROFILE (rule_10), object storage -> SUPPORT_ATTACHMENT, integration ->
  DATA_FLOW (no rule row; research/15 R9). Basis: research/15 R9/R10, DEV 29/29 findings.
* R11 content cue: an analytics record seen as a contact lookup or carrying ``email_opt_in`` is a
  marketing record (DELETE, not ANONYMIZE). Basis: research/15 R11 (one DEV case; the worker's own
  row for it is the only analytics DELETE in 4,011 rows).
* T55 support category: an attachment cue visible at or before ``audit_at`` makes a support
  record an attachment (rule_06 DELETE); otherwise the deletion worker's own action decides,
  flagged: only DELETE rows -> attachment, only REDACT rows -> message; otherwise a message
  (rule_05 REDACT). Basis: T55; G2 H4 (184/184 agreement where both are visible).

Decision table (``deletion_rules.csv`` action, mapped as DEV shows; the rule *conditions* are not
gated, G2 Q6):

* DELETE: PRESENT / IDENTIFIABLE -> REPORT_REMAINING_RECORD, DELETE_RECORD, VERIFY_RECORD_ABSENT;
  otherwise VERIFY_RECORD_ABSENT.
* REDACT: IDENTIFIABLE / EXPOSED_PII -> REPORT_EXPOSED_PII, REDACT_RECORD, VERIFY_RECORD_REDACTED;
  otherwise VERIFY_RECORD_REDACTED (rule_15: a clean tombstone in DEV; T9 for a PII one).
* ANONYMIZE: IDENTIFIABLE -> REPORT_EXPOSED_PII, ANONYMIZE_RECORD, VERIFY_RECORD_ANONYMIZED;
  otherwise VERIFY_RECORD_ANONYMIZED.
* RETAIN (audit log, legal hold): never a finding, never a delete -> VERIFY_RECORD_PRESENT
  (rule_12/13; 17 DEV steps; T42 "a legal hold is retained, never deleted").
* RETAIN, BACKUP_ARCHIVE: rule_14's condition is "restore access can be blocked", and DEV shows
  the restore path, never VERIFY_RECORD_PRESENT (4/4 DEV backups): RESTORABLE ->
  REPORT_RESTORE_RISK, BLOCK_RESTORE, VERIFY_RESTORE_BLOCKED; otherwise VERIFY_RESTORE_BLOCKED.
* DATA_FLOW: FLOW_ENABLED -> REPORT_ACTIVE_DATA_FLOW, DISABLE_DATA_FLOW, VERIFY_DATA_FLOW_DISABLED;
  otherwise VERIFY_DATA_FLOW_DISABLED.
* A record with no state gets no step (``NO_STEP``), as does a hold that names no resource (T69).
"""

from __future__ import annotations

import csv
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .. import timeutil
from ..discovery.accounts import Flag
from ..discovery.obstime import at_or_before, observation_time
from ..evidence.model import Observation
from ..inputs.model import ActivityRow
from ..state.observe import is_attachment_listing, leaves
from ..state.reconstruct import ResourceKey, ResourceState

RULES_FILE = "deletion_rules.csv"
RULES_HEADER = ("rule_id", "data_category", "condition", "required_action")
DATA_FLOW = "DATA_FLOW"

SYSTEM_CATEGORY: Mapping[str, str] = {
    "account_service": "USER_PROFILE",
    "search_service": "SEARCH_INDEX_ENTRY",
    "export_service": "USER_EXPORT",
    "security_service": "SECURITY_AUDIT_LOG",
    "legal_service": "LEGAL_HOLD_RECORD",
    "backup_service": "BACKUP_ARCHIVE",
    "identity_service": "ACCOUNT_TOMBSTONE",
    "marketing_platform": "MARKETING_PROFILE",
    "object_storage": "SUPPORT_ATTACHMENT",
    "object_store": "SUPPORT_ATTACHMENT",
    "integration_service": DATA_FLOW,
}
DELETE_TRIPLE = ("REPORT_REMAINING_RECORD", "DELETE_RECORD", "VERIFY_RECORD_ABSENT")
REDACT_TRIPLE = ("REPORT_EXPOSED_PII", "REDACT_RECORD", "VERIFY_RECORD_REDACTED")
ANON_TRIPLE = ("REPORT_EXPOSED_PII", "ANONYMIZE_RECORD", "VERIFY_RECORD_ANONYMIZED")
BACKUP_TRIPLE = ("REPORT_RESTORE_RISK", "BLOCK_RESTORE", "VERIFY_RESTORE_BLOCKED")
FLOW_TRIPLE = ("REPORT_ACTIVE_DATA_FLOW", "DISABLE_DATA_FLOW", "VERIFY_DATA_FLOW_DISABLED")


class RulesFormatError(ValueError):
    """``deletion_rules.csv`` is malformed."""


@dataclass(frozen=True)
class Rule:
    """One row of ``deletion_rules.csv``."""

    rule_id: str
    data_category: str
    condition: str
    required_action: str


@dataclass(frozen=True)
class RuleTable:
    """Rules by data category."""

    by_category: Mapping[str, Rule]

    def action(self, category: str) -> str | None:
        """The required action for a category, or None when no rule names it."""
        rule = self.by_category.get(category)
        return rule.required_action if rule else None


@dataclass(frozen=True)
class Categorization:
    """A record's category and how it was decided."""

    category: str
    basis: Literal["content_cue", "worker_action", "resource_type"]
    flag: Flag | None = None


@dataclass(frozen=True)
class PolicyDecision:
    """What the rules require for one record's state."""

    rule_id: str | None
    outcome: Literal["FINDING", "COMPLIANT", "NO_STEP"]
    finding_op: str | None
    remediation_op: str | None
    verification_op: str | None


def load_rules(dataset_dir: Path) -> RuleTable:
    """Read ``deletion_rules.csv``; a malformed file raises :class:`RulesFormatError`."""
    path = Path(dataset_dir) / RULES_FILE
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        if tuple(next(reader, ())) != RULES_HEADER:
            raise RulesFormatError(f"{RULES_FILE}: unexpected header")
        rules: dict[str, Rule] = {}
        for values in reader:
            if len(values) != 4 or not all(values[:2]) or not values[3]:
                raise RulesFormatError(f"{RULES_FILE} line {reader.line_num}: malformed row")
            rule = Rule(*values)
            if rule.data_category in rules:
                raise RulesFormatError(f"{RULES_FILE} line {reader.line_num}: duplicate category")
            rules[rule.data_category] = rule
    return RuleTable(rules)


def violating_states(category: str, rules: RuleTable) -> frozenset[str]:
    """The states that make a finding for a category (the decision table above)."""
    return frozenset(_triple_states(category, rules))


def _triple_states(category: str, rules: RuleTable) -> dict[str, tuple[str, str, str]]:
    if category == DATA_FLOW:
        return {"FLOW_ENABLED": FLOW_TRIPLE}
    action = rules.action(category)
    if action == "DELETE":
        return {"PRESENT": DELETE_TRIPLE, "IDENTIFIABLE": DELETE_TRIPLE}
    if action == "REDACT":
        return {"IDENTIFIABLE": REDACT_TRIPLE, "EXPOSED_PII": REDACT_TRIPLE}
    if action == "ANONYMIZE":
        return {"IDENTIFIABLE": ANON_TRIPLE}
    if action == "RETAIN" and category == "BACKUP_ARCHIVE":
        return {"RESTORABLE": BACKUP_TRIPLE}
    return {}


def _compliant_op(category: str, rules: RuleTable) -> str | None:
    if category == DATA_FLOW:
        return FLOW_TRIPLE[2]
    action = rules.action(category)
    if action == "DELETE":
        return DELETE_TRIPLE[2]
    if action == "REDACT":
        return REDACT_TRIPLE[2]
    if action == "ANONYMIZE":
        return ANON_TRIPLE[2]
    if action == "RETAIN":
        return BACKUP_TRIPLE[2] if category == "BACKUP_ARCHIVE" else "VERIFY_RECORD_PRESENT"
    return None


def decide(state: ResourceState, cat: Categorization, rules: RuleTable) -> PolicyDecision:
    """Apply the decision table (module docstring) to one record's state."""
    rule = rules.by_category.get(cat.category)
    rule_id = rule.rule_id if rule else None
    if state.value is None:
        return PolicyDecision(rule_id, "NO_STEP", None, None, None)
    triples = _triple_states(cat.category, rules)
    if state.value in triples:
        f, r, v = triples[state.value]
        return PolicyDecision(rule_id, "FINDING", f, r, v)
    op = _compliant_op(cat.category, rules)
    if op is None:
        return PolicyDecision(rule_id, "NO_STEP", None, None, None)
    return PolicyDecision(rule_id, "COMPLIANT", None, None, op)


def _attachment_cue(o: Observation, attachment_documents: frozenset[str]) -> bool:
    """A visible attachment cue on one record (research/15 R12). A PDF's cue is document-level: a
    record named on any page of a document that calls itself an attachment (research/15 read the
    whole text layer; in the one DEV attachment the cue is on page 2, the record on page 1)."""
    a = leaves(o)
    if o.event == "attachment_pii_scan" or is_attachment_listing(o):
        return True
    if (a.get("record_type") or "") == "SUPPORT_ATTACHMENT":
        return True
    if any(v.strip().lower() not in ("", "null", "none", "false") for k, v in a.items() if k in ("attachment", "file")):
        return True
    return o.locator.kind == "pdf_page" and o.file_id in attachment_documents


def attachment_documents(observations: Sequence[Observation]) -> frozenset[str]:
    """PDF files whose text layer (any page) says "attachment" (research/15 R12 cue)."""
    return frozenset(
        o.file_id for o in observations if o.locator.kind == "pdf_page" and "attachment" in (o.text or "").lower()
    )


def categorize(
    key: ResourceKey,
    observations: Sequence[Observation],
    activity: Sequence[ActivityRow],
    audit_at: str,
    *,
    catalog_attachment: bool = False,
    attachment_documents: frozenset[str] = frozenset(),
) -> Categorization:
    """The record's data category (module docstring). ``activity`` is the resource's own rows."""
    system = key.system_id
    if system == "analytics_platform":
        if any(o.event == "contact_lookup_completed" or "email_opt_in" in leaves(o) for o in observations):
            return Categorization("MARKETING_PROFILE", "content_cue")
        return Categorization("ANALYTICS_PROFILE", "resource_type")
    if system == "support_platform":
        visible = [o for o in observations if at_or_before(observation_time(o), audit_at)]
        if catalog_attachment or any(_attachment_cue(o, attachment_documents) for o in visible):
            return Categorization("SUPPORT_ATTACHMENT", "content_cue")
        acts = {
            a.event_type
            for a in activity
            if a.source_system == "deletion_worker"
            and a.resource_id == key.resource_id
            and timeutil.le(a.event_time, audit_at)
        }
        if acts == {"DELETE_RECORD"}:
            return Categorization(
                "SUPPORT_ATTACHMENT",
                "worker_action",
                Flag("SUPPORT_CATEGORY_FROM_WORKER", f"{key.resource_id}: no cue; worker DELETE_RECORD"),
            )
        if acts == {"REDACT_RECORD"}:
            return Categorization(
                "SUPPORT_MESSAGE",
                "worker_action",
                Flag("SUPPORT_CATEGORY_FROM_WORKER", f"{key.resource_id}: no cue; worker REDACT_RECORD"),
            )
        return Categorization("SUPPORT_MESSAGE", "resource_type")
    return Categorization(SYSTEM_CATEGORY.get(system, "UNKNOWN"), "resource_type")
