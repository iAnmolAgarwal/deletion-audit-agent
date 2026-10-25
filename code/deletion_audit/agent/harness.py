"""One call per case for the pipeline: loop -> answer validation -> intent -> compile twice -> report.

The pipeline wiring (after G5 commits) calls :func:`audit_with_agent` for each case and writes
``result.applied`` (the record whose steps are the output, except that a FAILED loop is replaced
by the engine-path row in ``pipeline.run``, flagged ``AGENT_CALL_FAILED``) and ``result.report`` (the ``"agent"``
object of ``cases.jsonl``). The withheld compilation exists only to measure whether the answers
changed the row (G3 section 9 item 2).

Image answers (G7a wiring proposal 6): a validated ``IMAGE_FIELD_UNREADABLE`` answer fills one
image field, so the applied compilation needs a world built on the patched image observations.
The caller passes ``world_for_answers``, which builds that world from the validated answers; it is
called only when such an answer exists, so a case without one compiles on ``world`` alone.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from ..engine import World
from ..model import ModelClient
from ..record import CaseRecord, IntentDecision
from .answers import AnswerCheck, Compiled, ValidatedAnswer, compile_twice, resolve_intent, validate_answers
from .loop import AgentOutcome, run_case
from .params import LoopCaps, Mode
from .report import agent_case_report
from .vision import VisionRun


@dataclass(frozen=True)
class AgentCaseResult:
    """Everything the agent produced for one case."""

    outcome: AgentOutcome
    check: AnswerCheck
    intent: IntentDecision
    withheld_intent: IntentDecision
    compiled: Compiled
    report: dict[str, Any]

    @property
    def applied(self) -> CaseRecord:
        """The record whose steps are written (answers applied)."""
        return self.compiled.applied


def audit_with_agent(case_id: str, world: World, client: ModelClient, *, mode: Mode,
                     caps: LoopCaps | None = None, vision: VisionRun | None = None,
                     replicate_clients: Sequence[ModelClient] = (), world_applied: World | None = None,
                     clock: Callable[[], float] = time.monotonic,
                     world_for_answers: Callable[[Sequence[ValidatedAnswer]], World] | None = None,
                     ) -> AgentCaseResult:
    """Run the agent on one case and compile its row (module docstring)."""
    outcome = run_case(case_id, world, client, mode=mode, caps=caps, vision=vision,
                       replicate_clients=replicate_clients, clock=clock)
    req = next(r for r in world.ctx.requests if r.case_id == case_id)
    check = validate_answers(outcome, world.validation, req.audit_at)
    applied, withheld = resolve_intent(outcome, check)
    image_answers = [v for v in check.validated if v.type == "IMAGE_FIELD_UNREADABLE" and v.slot is not None]
    if world_applied is None and image_answers and world_for_answers is not None:
        world_applied = world_for_answers(tuple(check.validated))
    compiled = compile_twice(case_id, world, applied, withheld, world_applied)
    report = agent_case_report(outcome, check, applied, compiled.steps_differ)
    return AgentCaseResult(outcome, check, applied, withheld, compiled, report)
