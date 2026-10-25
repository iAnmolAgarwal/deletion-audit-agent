"""Step and citation-plan types shared by the steps package, the record and the validator."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

CitationRule = Literal["R14_linked", "R14_fallback_same_system", "none"]


@dataclass(frozen=True)
class Step:
    """One output step. ``evidence_id`` is ``""`` where the contract says so (G1 F19)."""

    step_no: int
    phase: str
    system_id: str
    resource_id: str
    operation: str
    state: str
    evidence_id: str

    def as_json(self) -> dict[str, object]:
        """The step in the README key order (matches 17/22 DEV gold rows byte for byte, G1)."""
        return {
            "step_no": self.step_no,
            "phase": self.phase,
            "system_id": self.system_id,
            "resource_id": self.resource_id,
            "operation": self.operation,
            "state": self.state,
            "evidence_id": self.evidence_id,
        }


@dataclass(frozen=True)
class CitationPlan:
    """The one file a case cites (R14), and which branch of the rule chose it."""

    file_id: str | None
    rule: CitationRule
