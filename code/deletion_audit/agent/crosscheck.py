"""The intake cross-check: flags a disagreement with the model's intent, never changes it.

Basis:

* **Source: the CLASSIFY_REQUEST intake rows only** (developer ruling T71 Q10), at or before
  ``audit_at``, on the requester's own records. The rows are found by G5's
  :func:`deletion_audit.engine.crosscheck`, so the agent and the engine read one definition.
* **Flags only** (T63 pin 1; ``notes/SYSTEM.md``, "the code cross-check only flags a
  disagreement; it never overrides"). :func:`compare` returns a flag and, in modes A and A+, an
  ``INTENT_CROSSCHECK`` open question; the label is untouched. The model may change its intent
  only by answering that question (G3 section 1.0 table).
"""

from __future__ import annotations

from dataclasses import dataclass

from ..discovery.accounts import Flag
from ..engine import World
from ..engine import crosscheck as engine_crosscheck
from ..record import CrossCheck
from .intent import agreement


def intake_crosscheck(case_id: str, world: World) -> CrossCheck:
    """The CLASSIFY_REQUEST rows for one case's person, at or before its ``audit_at`` (T71 Q10)."""
    req = next(r for r in world.ctx.requests if r.case_id == case_id)
    asg = world.assignments.get(case_id)
    return engine_crosscheck(req, world, asg.resource_id if asg else None, world.case_links[case_id])


@dataclass(frozen=True)
class CrossCheckResult:
    """The comparison of a label with the intake rows; ``flag`` is set only on disagreement."""

    agrees: bool | None
    flag: Flag | None


def compare(label: str | None, cc: CrossCheck) -> CrossCheckResult:
    """Compare ``label`` with ``cc``. Never returns a label: the model's answer stands (T63)."""
    agrees = agreement(label, cc)
    if agrees is False:
        side = "a non-deletion intake row" if cc.intake_non_deletion else "no non-deletion intake row"
        return CrossCheckResult(False, Flag("INTENT_CROSSCHECK_DISAGREES", f"model {label}; {side}"))
    return CrossCheckResult(agrees, None)
