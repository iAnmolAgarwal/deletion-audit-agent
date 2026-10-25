"""The canonical per-case record: every output field derives from it (``notes/ARCHITECTURE_OPTIONS.md`` section 6).

* ``steps`` is the source of truth; ``status`` is derived from it, never stored (``../CLAUDE.md`` section 3).
* ``FAILED_CLOSED`` (developer ruling T71 Q5) is an enumerated row class: status INCOMPLETE,
  never COMPLETE and never NOT_APPLICABLE, with its reason counted in the run artifacts. It is
  used when no schema-valid honest row exists: an unparsed dependency (T8), a missing evidence
  file or a malformed request row (T86), an unresolved identity (T63), a linked record whose
  evidence gives no step (UNINTERPRETED_RECORD, ``engine`` module docstring), a finding whose
  record only post-audit files hold (POST_AUDIT_ONLY_FINDING, developer ruling T101), nothing
  found, or a row the validator refuses.
* ``IntentDecision`` lives here until the model gate (G7) exists; G5's intent stage returns the
  fail-closed decision of T71 Q2: the engine's deletion-path row, flagged, never NOT_APPLICABLE.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from .discovery.accounts import AccountAssignment, Flag
from .identity.resolve import IdentityResolution
from .inputs.requests import DeletionRequest
from .policy.rules import Categorization, PolicyDecision
from .state.reconstruct import ResourceKey, ResourceState
from .steps.model import CitationPlan, Step

if TYPE_CHECKING:  # the validator imports this module, so its type is imported for checking only
    from .validate.prewrite import CheckResult

IntentLabel = Literal["DELETION_REQUEST", "NOT_DELETION", "UNCERTAIN"]
IntentSource = Literal["MODEL", "MODEL_AFTER_TOOLS", "FAILED_CLOSED", "FAILED_BUDGET"]
FailedClosedReason = Literal[
    "UNPARSED_DEPENDENCY",
    "UNINTERPRETED_RECORD",
    "POST_AUDIT_ONLY_FINDING",
    "MISSING_EVIDENCE_FILE",
    "IDENTITY_UNRESOLVED",
    "NOTHING_FOUND",
    "MALFORMED_REQUEST",
    "VALIDATOR_REFUSED",
]
Status = Literal["COMPLETE", "INCOMPLETE", "NOT_APPLICABLE"]


@dataclass(frozen=True)
class CrossCheck:
    """The intake cross-check (Q10): CLASSIFY_REQUEST rows on the person's own records."""

    intake_non_deletion: bool
    activity_ids: tuple[str, ...]


@dataclass(frozen=True)
class IntentDecision:
    """Whether the request authorizes deletion, and who decided."""

    label: IntentLabel | None
    source: IntentSource
    committed_key: str | None
    final_key: str | None
    crosscheck: CrossCheck
    agrees: bool | None

    @property
    def not_applicable(self) -> bool:
        """True only for a validated model answer of NOT_DELETION (section 6 derivation)."""
        return self.label == "NOT_DELETION" and self.source in ("MODEL", "MODEL_AFTER_TOOLS")


def fail_closed_intent(crosscheck: CrossCheck) -> IntentDecision:
    """T71 Q2: no model answer -> the engine's deletion-path row, flagged; never NOT_APPLICABLE."""
    return IntentDecision(
        label=None, source="FAILED_CLOSED", committed_key=None, final_key=None, crosscheck=crosscheck, agrees=None
    )


@dataclass(frozen=True)
class ResourceFinding:
    """One record of a case with its link, state, category and decision."""

    key: ResourceKey
    link_basis: (
        str  # identifier | trace | link_row | alias | image | timed_account | fingerprint | slot_band | tie_pick | t27
    )
    state: ResourceState
    category: Categorization
    decision: PolicyDecision
    answered_by: str | None = None
    cite: str = ""  # the evidence a FINDING step cites (R14: the case file when it shows the state)
    flags: tuple[Flag, ...] = ()


def derive_status(
    intent: IntentDecision, steps: tuple[Step, ...] | list[Step], failed_closed: str | None = None
) -> Status:
    """NOT_APPLICABLE <=> a validated NOT_DELETION; else INCOMPLETE <=> a FINDING (or a FAILED_CLOSED
    row); else COMPLETE. Basis: research/15 R13 (DEV 22/22); T71 Q5."""
    if intent.not_applicable:
        return "NOT_APPLICABLE"
    if failed_closed is not None:
        return "INCOMPLETE"
    return "INCOMPLETE" if any(s.phase == "FINDING" for s in steps) else "COMPLETE"


@dataclass(frozen=True)
class CaseRecord:
    """Everything the engine decided for one case."""

    case_id: str
    request: DeletionRequest | None  # None only for a request row that could not be loaded (T86 item 2)
    intent: IntentDecision
    identity: IdentityResolution
    account: AccountAssignment | None
    resources: tuple[ResourceFinding, ...]  # sorted by (system_id, resource_id)
    citation: CitationPlan
    open_questions: tuple[str, ...]
    answers: tuple[str, ...]
    rejected: tuple[str, ...]
    failed_dependencies: frozenset[str]
    steps: tuple[Step, ...]
    checks: tuple[CheckResult, ...]
    flags: tuple[Flag, ...]
    failed_closed: FailedClosedReason | None = None

    @property
    def status(self) -> Status:
        """Derived from the steps, never stored."""
        return derive_status(self.intent, self.steps, self.failed_closed)

    @property
    def row_state(self) -> Literal["VALID", "FAILED_CLOSED"]:
        """``FAILED_CLOSED`` when the row is the enumerated fail-closed class (T71 Q5)."""
        return "FAILED_CLOSED" if self.failed_closed is not None else "VALID"
