"""Answer validation, the intent decision, and the two compilations (answers applied and withheld).

Basis:

* **A rejected answer is recorded with its reason, never applied silently** (G7a brief item 6;
  T10/T42: the model answers only open questions and never changes a settled fact). The checks,
  in order: the question was posed; one answer per question; the choice is allowed; every cited
  evidence ID exists in the evidence index, was captured at or before ``audit_at``, and was shown
  by a tool in this conversation (IDs are copied, never composed: ``../CLAUDE.md`` section 3); an
  image question cites its image; an intent answer equals the final intent and its quote is in
  the request text; an answer is not also declared unanswerable.
* **The intent** (T63, T71 Q2): the committed turn-1 label, unless a posed intent question got a
  validated answer, which then decides (source ``MODEL_AFTER_TOOLS``). An undecided label fails
  closed; a call failure before any commit gives ``FAILED_CLOSED`` or ``FAILED_BUDGET``.
* **Compiled twice** (G3 section 9 item 2): the engine compiles the case with the validated answers
  applied and with them withheld, at no API cost; ``steps_differ`` says whether the answers
  changed the row.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from types import MappingProxyType

from .. import timeutil
from ..engine import OpenQuestion, World
from ..engine import audit_case as engine_audit_case
from ..evidence.model import Observation
from ..record import CaseRecord, IntentDecision
from ..validate.prewrite import ValidationContext
from .intent import answer_is_valid, decision, failed_source
from .loop import AgentOutcome, FixedIntent
from .questions import INTENT_TYPES


@dataclass(frozen=True)
class ValidatedAnswer:
    """An accepted answer: it may fill only its question's slot (None: recorded, changes nothing)."""

    oq_id: str
    type: str
    slot: str | None
    choice: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class Rejection:
    """A refused answer and why."""

    oq_id: str
    reason: str


@dataclass(frozen=True)
class AnswerCheck:
    """The validation result for one case."""

    validated: tuple[ValidatedAnswer, ...]
    rejected: tuple[Rejection, ...]

    def applied(self) -> tuple[str, ...]:
        """IDs of validated answers that fill a slot."""
        return tuple(v.oq_id for v in self.validated if v.slot is not None)

    def noted(self) -> tuple[str, ...]:
        """IDs of validated answers whose question has no slot (recorded only)."""
        return tuple(v.oq_id for v in self.validated if v.slot is None)


def _evidence_problem(ids: Sequence[str], q: OpenQuestion, outcome: AgentOutcome, ctx: ValidationContext,
                      audit_at: str) -> str | None:
    """The first evidence problem of one answer, or None."""
    for eid in ids:
        if eid not in ctx.citable_time:
            return "EVIDENCE_UNKNOWN"
        if not timeutil.le(ctx.citable_time[eid], audit_at):
            return "EVIDENCE_AFTER_AUDIT"
        if eid not in outcome.seen_evidence:
            return "EVIDENCE_NOT_SEEN"
    if q.type.startswith("IMAGE_"):
        if not ids:
            return "NO_EVIDENCE"
        if q.type == "IMAGE_FIELD_UNREADABLE" and q.subject.split(":", 1)[0] not in ids:
            return "EVIDENCE_NOT_SUBJECT"
    return None


def validate_answers(outcome: AgentOutcome, ctx: ValidationContext, audit_at: str) -> AnswerCheck:
    """Check every answer of the final reply (module docstring); keep each refusal with its reason."""
    final = outcome.final
    if final is None:
        return AnswerCheck((), ())
    posed = {q.oq_id: q for q in outcome.questions}
    declined = {c.oq_id for c in final.cannot_answer}
    done: set[str] = set()
    validated: list[ValidatedAnswer] = []
    rejected: list[Rejection] = []
    for a in final.answers:
        q = posed.get(a.oq_id)
        reason: str | None = None
        if q is None:
            reason = "UNKNOWN_QUESTION"
        elif a.oq_id in done:
            reason = "DUPLICATE_ANSWER"
        elif a.choice not in q.allowed_choices:
            reason = "CHOICE_NOT_ALLOWED"
        elif a.oq_id in declined:
            reason = "CONTRADICTS_CANNOT_ANSWER"
        else:
            reason = _evidence_problem(a.evidence_ids, q, outcome, ctx, audit_at)
        if reason is None and q is not None and q.type in INTENT_TYPES:
            if a.choice != final.intent.intent:
                reason = "INCONSISTENT_WITH_FINAL_INTENT"
            elif not answer_is_valid(final.intent, outcome.request_text):
                reason = "BASIS_QUOTE_INVALID"
        if reason is not None or q is None:
            rejected.append(Rejection(a.oq_id, reason or "UNKNOWN_QUESTION"))
            continue
        done.add(a.oq_id)
        validated.append(ValidatedAnswer(a.oq_id, q.type, q.slot, a.choice, tuple(a.evidence_ids)))
    return AnswerCheck(tuple(validated), tuple(rejected))


def resolve_intent(outcome: AgentOutcome, check: AnswerCheck) -> tuple[IntentDecision, IntentDecision]:
    """``(applied, withheld)`` intent decisions for one case (module docstring)."""
    cc = outcome.crosscheck
    if outcome.committed_label is None:
        source = failed_source(outcome.failure) if outcome.status == "FAILED" else "FAILED_CLOSED"
        failed = decision(None, source, cc, None, None)
        return failed, failed
    key = outcome.committed_key
    withheld = decision(outcome.committed_label, "MODEL", cc, key, key)
    answers = [v for v in check.validated if v.type in INTENT_TYPES]
    if not answers:
        return withheld, withheld
    applied = decision(answers[0].choice, "MODEL_AFTER_TOOLS", cc, key, outcome.final_key or key)
    return applied, withheld


_FIELD_ATTR = {"sync_enabled": "enabled", "restore_allowed": "restore_allowed",
               "download_available": "download_available"}


def patch_image_observations(observations: Sequence[Observation],
                             validated: Sequence[ValidatedAnswer]) -> tuple[Observation, ...]:
    """Image observations with validated ``IMAGE_FIELD_UNREADABLE`` answers filled in.

    The slot ``image_field:<file>:<resource>:<field>`` names exactly one observation and one
    attribute (the same names :func:`.vision.record_attrs` writes); nothing else changes.
    """
    patches: dict[tuple[str, str], dict[str, str]] = {}
    for v in validated:
        if v.type != "IMAGE_FIELD_UNREADABLE" or v.slot is None:
            continue
        _, file_id, rid, name = v.slot.split(":", 3)
        tri = {"yes": "true", "no": "false"}[v.choice]
        if name == "marked_deleted":
            attr, value = "account_status", ("DELETED" if v.choice == "yes" else "ACTIVE")
        else:
            attr, value = _FIELD_ATTR[name], tri
        patches.setdefault((file_id, rid), {})[attr] = value
    out = []
    for o in observations:
        extra = patches.get((o.file_id, o.resource_id or ""))
        out.append(replace(o, attrs=MappingProxyType({**o.attrs, **extra})) if extra else o)
    return tuple(out)


@dataclass(frozen=True)
class Compiled:
    """The case compiled with the answers applied and withheld."""

    applied: CaseRecord
    withheld: CaseRecord

    @property
    def steps_differ(self) -> bool:
        """Whether the validated answers changed the row (status or any step)."""
        return self.applied.status != self.withheld.status or self.applied.steps != self.withheld.steps


def compile_twice(case_id: str, world: World, applied: IntentDecision, withheld: IntentDecision,
                  world_applied: World | None = None) -> Compiled:
    """Compile the case twice: answers applied (``world_applied`` carries image patches) and withheld."""
    return Compiled(
        engine_audit_case(case_id, world_applied or world, FixedIntent(applied)),
        engine_audit_case(case_id, world, FixedIntent(withheld)),
    )
