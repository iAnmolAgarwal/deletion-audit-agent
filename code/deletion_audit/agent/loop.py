"""The agent loop for one case: turn 1, then (mode permitting) at most 4 tool calls and a final answer.

Modes run in the same code (developer ruling T70; G3 sections 1.1-1.3, 3, 9):

* ``A+`` (ship): the model routes every case. A deletion commit through ``audit_case`` always gets
  the engine's brief back and the model finishes with a final answer. A final answer of
  ``DELETION_REQUEST`` without an ``audit_case`` call gets one nudge, then ``NO_AUDIT_CALL``
  (G3 section 1.2 rule 2).
* ``A``: the same turn 1. Code continues the conversation only when the case has an open
  question; a deletion commit with no question stops after turn 1.
* ``tools_off``: the same turn 1, and nothing after it: no tool runs, no question is posed; an
  ``UNCERTAIN`` commit fails closed.

All three share the turn-1 request, so they route identically and A vs A+ costs only the extra
turns (G3 section 3 item 3). Routing rules, each tested:

* **Commit before evidence** (G3 section 1.2): until the intent is committed, every tool but
  ``audit_case`` returns an error; ``audit_case`` with a bad input or a quote not in the text is
  refused, not committed.
* ``UNCERTAIN`` gets one ``INTENT_UNCERTAIN`` question that names ``get_request_context`` (rule 3);
  a cross-check disagreement gets ``INTENT_CROSSCHECK`` (T71 Q10). Both A and A+.
* **Caps** (:class:`~.params.LoopCaps`; ``../CLAUDE.md`` section 5): at most ``max_tool_calls``
  tool calls, ``audit_case`` included; then one request with ``tool_choice: {"type": "none"}`` and
  the schema-constrained answer. The same final turn is forced by the request and wall-clock
  caps. A call past the cap is refused with an error result and never runs.
* **No repeats**: an identical call (name and canonical arguments) is refused.
* **Drift** (rule 1): without an intent question the final intent must equal the commit; one
  repair turn, then the commit stands, flagged ``INTENT_DRIFT``.
* **Failure** (T71 Q2; ``../CLAUDE.md`` section 3): a failed call ends the case with status
  ``FAILED`` and the failure reason; the intent is then whatever was committed before the failure
  (nothing committed: fail closed). Nothing is defaulted from the input.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from ..discovery.accounts import Flag
from ..engine import EngineBrief, IntentProvider, OpenQuestion, World
from ..engine import audit_case as engine_audit_case
from ..inputs.requests import DeletionRequest
from ..model import ModelCallFailed, ModelClient, ModelReply, ModelRequest, reply_text, tool_uses
from ..record import CaseRecord, CrossCheck, IntentDecision
from .crosscheck import compare, intake_crosscheck
from .injection import InstructionSignal, detect_in_json, detect_instruction_like
from .intent import Turn1, answer_is_valid, base_body, decision, run_turn1, turn1_user_message
from .params import MAX_TOKENS_LOOP, LoopCaps, Mode
from .questions import intent_question, record_questions
from .schemas import FinalAnswer, SchemaError, parse_audit_case_input, parse_final
from .tools import CaseTools, ToolResult, args_hash, tool_definitions
from .vision import VisionRun

LoopStatus = Literal["OK", "FINALIZED_AT_CAP", "FAILED"]


class FixedIntent(IntentProvider):
    """An intent provider for :func:`deletion_audit.engine.audit_case` that returns one decision."""

    def __init__(self, decided: IntentDecision) -> None:
        """Hold ``decided``."""
        self.decided = decided

    def __call__(self, req: DeletionRequest, crosscheck: CrossCheck) -> IntentDecision:
        """The held decision, whatever the request."""
        return self.decided


@dataclass(frozen=True)
class ToolCallRecord:
    """One tool call: name, arguments hash, whether it errored or was refused, evidence IDs shown."""

    name: str
    args_hash: str
    is_error: bool
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class AgentOutcome:
    """Everything one case's conversation produced (G3 section 5, extended for the report)."""

    case_id: str
    mode: Mode
    request_text: str
    crosscheck: CrossCheck
    committed_label: str | None
    committed_key: str | None
    turn1: Turn1
    final: FinalAnswer | None
    final_key: str | None
    questions: tuple[OpenQuestion, ...]
    tool_calls: tuple[ToolCallRecord, ...]
    reply_keys: tuple[str, ...]
    status: LoopStatus
    flags: tuple[Flag, ...]
    seen_evidence: frozenset[str]
    replicates: tuple[str | None, ...] = ()
    failure: str | None = None
    instruction: InstructionSignal = InstructionSignal((), False)


def _plain(value: Any) -> Any:
    return json.loads(json.dumps(value, default=dict))


def _assistant(reply: ModelReply) -> dict[str, Any]:
    """The reply's content blocks replayed unchanged as the assistant turn (thinking included)."""
    return {"role": "assistant", "content": _plain(reply.raw["content"])}


def _questions_text(questions: Sequence[OpenQuestion], note: str) -> dict[str, Any]:
    body = {"open_questions": [{"oq_id": q.oq_id, "type": q.type, "subject": q.subject,
                                "allowed_choices": list(q.allowed_choices)} for q in questions], "note": note}
    return {"type": "text", "text": json.dumps(body, sort_keys=True)}


@dataclass
class _State:
    """Mutable loop state for one case (private to :func:`run_case`)."""

    messages: list[dict[str, Any]]
    committed_label: str | None
    committed_key: str | None
    tool_count: int = 0
    requests: int = 1
    reply_keys: list[str] = field(default_factory=list)
    calls: list[ToolCallRecord] = field(default_factory=list)
    hashes: set[str] = field(default_factory=set)
    seen: set[str] = field(default_factory=set)
    flags: list[Flag] = field(default_factory=list)
    questions: list[OpenQuestion] = field(default_factory=list)
    nudged: bool = False
    drift_repaired: bool = False
    forced_by: str | None = None
    model_injection: bool = False
    code_hits: list[tuple[str, tuple[str, ...]]] = field(default_factory=list)


class _Case:
    """One case's conversation (private; :func:`run_case` is the entry point)."""

    def __init__(self, case_id: str, world: World, client: ModelClient, mode: Mode, caps: LoopCaps,
                 vision: VisionRun | None, clock: Callable[[], float]) -> None:
        self.case_id = case_id
        self.world = world
        self.client = client
        self.mode = mode
        self.caps = caps
        self.clock = clock
        self.start = clock()
        self.request = next(r for r in world.ctx.requests if r.case_id == case_id)
        self.text = self.request.request_text
        self.cc = intake_crosscheck(case_id, world)
        self.vision = vision
        self.tool_defs = tool_definitions()
        self._brief: EngineBrief | None = None
        self.st = _State([], None, None)
        self.tools = CaseTools(case_id, world, self.cc, vision.by_file() if vision else {}, self.brief)

    # ------------------------------------------------------------------ engine brief
    def deletion_record(self) -> CaseRecord:
        """The engine's record for this case on the deletion path (the brief's facts)."""
        decided = decision("DELETION_REQUEST", "MODEL", self.cc, None, None)
        return engine_audit_case(self.case_id, self.world, FixedIntent(decided))

    def brief(self) -> EngineBrief:
        """The engine brief with every open question (memoized; questions recorded once)."""
        if self._brief is None:
            record = self.deletion_record()
            unreadable: dict[str, list[tuple[str, str]]] = {}
            images: frozenset[str] = frozenset()
            if self.vision is not None:
                images = frozenset(r.file_id for r in self.vision.records)
                for r in self.vision.records:
                    unreadable[r.file_id] = list(r.unreadable_fields())
            qs = list(self.st.questions) + list(record_questions(record, unreadable, images))
            self.st.questions = list(dict.fromkeys(qs))
            self._brief = EngineBrief(record.case_id, record.resources, record.citation, tuple(self.st.questions),
                                      record.flags)
        return self._brief

    # ------------------------------------------------------------------ helpers
    def _flag(self, code: str, detail: str) -> None:
        self.st.flags.append(Flag(code, detail))

    def _model_flag(self) -> None:
        """The model's own ``instruction_like_text`` flag (merged with the code check; T95 item 1)."""
        self.st.model_injection = True
        self._flag("INSTRUCTION_LIKE_TEXT_MODEL", "the model saw instruction-like text")

    def _code_check(self, source: str, patterns: tuple[str, ...]) -> None:
        """Record a code-side match (flag only: never changes a label, step or status; T95 item 1)."""
        if patterns:
            self.st.code_hits.append((source, patterns))
            self._flag("INSTRUCTION_LIKE_TEXT_CODE", f"{source}: {','.join(patterns)}")

    def _intent_questions(self, label: str | None) -> list[OpenQuestion]:
        """INTENT_UNCERTAIN for an uncertain commit; INTENT_CROSSCHECK for a disagreement (flag always)."""
        if label == "UNCERTAIN":
            return [intent_question(self.case_id, "INTENT_UNCERTAIN")]
        result = compare(label, self.cc)
        if result.flag is not None:
            self.st.flags.append(result.flag)
            return [intent_question(self.case_id, "INTENT_CROSSCHECK")]
        return []

    def _send(self, *, force_final: bool) -> ModelReply:
        choice = "none" if force_final else "auto"
        req = ModelRequest(base_body(self.tool_defs, self.st.messages, max_tokens=MAX_TOKENS_LOOP, tool_choice=choice))
        self.st.requests += 1
        reply = self.client.call(req)
        self.st.reply_keys.append(req.key())
        return reply

    def _force_reason(self) -> str | None:
        if self.st.tool_count >= self.caps.max_tool_calls:
            return "CAP_REACHED"
        if self.st.requests >= self.caps.max_requests - 1:
            return "REQUEST_CAP"
        if self.clock() - self.start >= self.caps.max_wall_s:
            return "WALL_CAP"
        return None

    def _record(self, name: str, args: Any, result: ToolResult) -> ToolResult:
        if not result.is_error:
            source = "evidence:" + (",".join(result.evidence_ids) or name)
            self._code_check(source, detect_in_json(result.content).patterns)
        self.st.calls.append(ToolCallRecord(name, args_hash(name, args), result.is_error, result.evidence_ids))
        self.st.seen.update(result.evidence_ids)
        return result

    def _commit_via_audit_case(self, args: Any, key: str) -> ToolResult | None:
        """Validate an ``audit_case`` input; commit on the first valid one. Error result if invalid."""
        try:
            answer = parse_audit_case_input(args)
        except SchemaError as exc:
            return ToolResult(json.dumps({"error": f"input does not match the schema: {exc}"}), True, ())
        if not answer_is_valid(answer, self.text):
            return ToolResult(json.dumps({"error": "basis_quote must be copied exactly from the request text"}),
                              True, ())
        if answer.instruction_like_text:
            self._model_flag()
        if self.st.committed_label is None:
            self.st.committed_label, self.st.committed_key = "DELETION_REQUEST", key
            self.st.questions.extend(self._intent_questions("DELETION_REQUEST"))
        return None

    def _run_tool(self, use: Mapping[str, Any], key: str) -> ToolResult:
        """Run one tool_use block under the cap, no-repeat and commit-first rules."""
        name, args = str(use.get("name")), use.get("input")
        if self.st.tool_count >= self.caps.max_tool_calls:
            self._flag("CALL_PAST_CAP_REFUSED", name)
            return self._record(name, args, ToolResult(json.dumps({"error": "tool budget used; answer now"}), True, ()))
        self.st.tool_count += 1
        h = args_hash(name, args)
        if self.caps.no_repeat and h in self.st.hashes:
            self._flag("REPEATED_TOOL_CALL", name)
            return self._record(name, args, ToolResult(json.dumps({"error": "repeated call refused"}), True, ()))
        self.st.hashes.add(h)
        if name == "audit_case":
            refused = self._commit_via_audit_case(args, key)
            if refused is not None:
                return self._record(name, args, refused)
        elif self.st.committed_label is None:
            self._flag("TOOL_BEFORE_COMMIT", name)
            msg = "commit your intent first: call audit_case for a deletion request, or give the JSON answer"
            return self._record(name, args, ToolResult(json.dumps({"error": msg}), True, ()))
        return self._record(name, args, self.tools.run(name, args))

    def _tool_results(self, reply: ModelReply, key: str) -> list[dict[str, Any]]:
        blocks = []
        for use in tool_uses(reply.raw):
            result = self._run_tool(use, key)
            blocks.append({"type": "tool_result", "tool_use_id": use.get("id"), "content": result.content,
                           "is_error": result.is_error})
        return blocks

    # ------------------------------------------------------------------ the conversation
    def run(self, replicate_clients: Sequence[ModelClient]) -> AgentOutcome:
        """Run turn 1 and, by mode, the loop (module docstring)."""
        t1 = run_turn1(self.text, self.tool_defs, self.client)
        replicates = tuple(run_turn1(self.text, self.tool_defs, c).label for c in replicate_clients)
        committed = t1.label
        self.st = _State([turn1_user_message(self.text)], committed,
                         t1.request_key if committed is not None else None, reply_keys=[t1.request_key])
        self._code_check("request", detect_instruction_like(self.text).patterns)
        if t1.via == "failed":
            self._flag("AGENT_CALL_FAILED", f"turn 1: {t1.failure} ({t1.error_class})")
            return self._outcome(t1, None, None, "FAILED", replicates, t1.failure)
        assert t1.reply is not None
        if t1.quote_valid is False:
            self._flag("BASIS_QUOTE_INVALID", f"turn 1 via {t1.via}")
        if t1.answer is not None and t1.answer.intent == "UNCERTAIN" and not t1.answer.uncertain_reason.strip():
            self._flag("UNCERTAIN_WITHOUT_REASON", "turn 1")
        if t1.answer is not None and t1.answer.instruction_like_text:
            self._model_flag()
        if len(set(replicates) | {committed}) > 1 and replicates:
            self._flag("TURN1_REPLICATES_DISAGREE", f"{len(replicates) + 1} readings")
        if self.mode == "tools_off":
            if committed is None:
                self._flag("NO_VALID_COMMIT", "turn 1 gave no valid commit; tools are off")
            else:
                compare_flag = compare(committed, self.cc).flag
                if compare_flag is not None:
                    self.st.flags.append(compare_flag)
            return self._outcome(t1, t1.final, t1.request_key if t1.final else None, "OK", replicates, None)
        return self._continue(t1, replicates)

    def _continue(self, t1: Turn1, replicates: tuple[str | None, ...]) -> AgentOutcome:
        """Modes A and A+: route after turn 1, then loop to a final answer when needed."""
        assert t1.reply is not None
        reply, key = t1.reply, t1.request_key
        pending: list[dict[str, Any]] = []
        extra: list[dict[str, Any]] = []
        if t1.via == "audit_case" or tool_uses(reply.raw):
            if self.st.committed_label is not None:  # committed at turn 1, before any tool result
                self.st.questions.extend(self._intent_questions(self.st.committed_label))
            pending = self._tool_results(reply, key)
            if self.mode == "A" and self.st.committed_label == "DELETION_REQUEST" and not self.brief().open_questions:
                return self._outcome(t1, None, None, "OK", replicates, None)
        else:
            label = self.st.committed_label
            qs = self._intent_questions(label)
            self.st.questions.extend(qs)
            if qs:
                note = ("Answer this open question in your final JSON. You may call get_request_context first."
                        if label == "UNCERTAIN" else
                        "The intake record disagrees with your intent. Look again; you may call get_request_context.")
                extra.append(_questions_text(qs, note))
            elif label == "DELETION_REQUEST" and self.mode == "A+":
                self.st.nudged = True
                extra.append({"type": "text", "text": "This is a deletion request: call audit_case to fetch the "
                                                      "engine's brief, then give your final answer."})
            elif label == "DELETION_REQUEST" and self.brief().open_questions:
                extra.append({"type": "text", "text": "Engine brief (read-only):\n" + self.brief().for_model()})
            else:
                return self._outcome(t1, t1.final, key, "OK", replicates, None)
        return self._loop(t1, reply, pending, extra, replicates)

    def _loop(self, t1: Turn1, reply: ModelReply, pending: list[dict[str, Any]], extra: list[dict[str, Any]],
              replicates: tuple[str | None, ...]) -> AgentOutcome:
        """Send results and questions until a final answer arrives, a cap forces one, or a call fails."""
        while True:
            self.st.messages.append(_assistant(reply))
            self.st.messages.append({"role": "user", "content": pending + extra})
            reason = self._force_reason()
            if reason is not None and self.st.forced_by is None:
                self.st.forced_by = reason
                self._flag(reason, "final turn forced with tool_choice none")
            try:
                reply = self._send(force_final=reason is not None)
            except ModelCallFailed as exc:
                self._flag("AGENT_CALL_FAILED", f"loop: {exc.reason} ({exc.error_class})")
                return self._outcome(t1, None, None, "FAILED", replicates, exc.reason)
            key = self.st.reply_keys[-1]
            if tool_uses(reply.raw):
                pending, extra = self._tool_results(reply, key), []
                continue
            try:
                final = parse_final(json.loads(reply_text(reply.raw) or "null"))
            except (SchemaError, ValueError) as exc:
                self._flag("AGENT_CALL_FAILED", f"final answer unparseable ({type(exc).__name__})")
                return self._outcome(t1, None, None, "FAILED", replicates, "UNPARSEABLE")
            redo = self._after_final(final, key)
            if redo is None:
                status: LoopStatus = "FINALIZED_AT_CAP" if self.st.forced_by else "OK"
                return self._outcome(t1, final, key, status, replicates, None)
            pending, extra = [], [redo]

    def _after_final(self, final: FinalAnswer, key: str) -> dict[str, Any] | None:
        """A drift-repair message, or None when the answer stands.

        A final answer that arrives before any valid commit (turn 1 only offered refused tool calls,
        so no evidence was seen) is the commit itself, flagged ``LATE_COMMIT``; its quote is checked.
        """
        label = final.intent.intent
        if final.intent.instruction_like_text:
            self._model_flag()
        if self.st.committed_label is None:
            valid = answer_is_valid(final.intent, self.text)
            self.st.committed_label, self.st.committed_key = (label if valid else "UNCERTAIN"), key
            self._flag("LATE_COMMIT", "first valid commit came in a final answer after refused tool calls")
            if not valid:
                self._flag("BASIS_QUOTE_INVALID", "late commit")
            flag = compare(self.st.committed_label, self.cc).flag
            if flag is not None:
                self.st.flags.append(flag)
            return None
        intent_posed = any(q.type in ("INTENT_UNCERTAIN", "INTENT_CROSSCHECK") for q in self.st.questions)
        spare = self.st.requests < self.caps.max_requests
        if (self.mode == "A+" and self.st.nudged and label == "DELETION_REQUEST"
                and not any(c.name == "audit_case" and not c.is_error for c in self.st.calls)):
            self._flag("NO_AUDIT_CALL", "deletion answer without audit_case after one nudge")
        if intent_posed or label == self.st.committed_label:
            return None
        if not self.st.drift_repaired and spare:
            self.st.drift_repaired = True
            text = (f"Your committed intent was {self.st.committed_label}. Without an intent question it cannot "
                    f"change. Reply again with the JSON answer, intent {self.st.committed_label}.")
            return {"type": "text", "text": text}
        self._flag("INTENT_DRIFT", f"final {label}; committed {self.st.committed_label} stands")
        return None

    def _outcome(self, t1: Turn1, final: FinalAnswer | None, final_key: str | None, status: LoopStatus,
                 replicates: tuple[str | None, ...], failure: str | None) -> AgentOutcome:
        return AgentOutcome(
            case_id=self.case_id, mode=self.mode, request_text=self.text, crosscheck=self.cc,
            committed_label=self.st.committed_label, committed_key=self.st.committed_key, turn1=t1, final=final,
            final_key=final_key, questions=tuple(self.st.questions), tool_calls=tuple(self.st.calls),
            reply_keys=tuple(self.st.reply_keys), status=status,
            flags=tuple(sorted(set(self.st.flags), key=lambda f: (f.code, f.detail))),
            seen_evidence=frozenset(self.st.seen), replicates=replicates, failure=failure,
            instruction=InstructionSignal(tuple(self.st.code_hits), self.st.model_injection),
        )


def run_case(case_id: str, world: World, client: ModelClient, *, mode: Mode, caps: LoopCaps | None = None,
             vision: VisionRun | None = None, replicate_clients: Sequence[ModelClient] = (),
             clock: Callable[[], float] = time.monotonic) -> AgentOutcome:
    """Run one case's conversation in ``mode`` (module docstring). Never raises ModelCallFailed."""
    if mode not in ("A+", "A", "tools_off"):
        raise ValueError(f"unknown mode {mode!r}")
    return _Case(case_id, world, client, mode, caps or LoopCaps(), vision, clock).run(replicate_clients)
