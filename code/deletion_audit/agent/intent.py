"""Turn 1: the model commits the request's intent from the request text alone.

Basis (each rule is a developer ruling or G3 design, not organiser text):

* **Text only** (G3 section 1.2; T70). The turn-1 request holds the system prompt, the tool
  definitions and the fenced request text, and nothing case-specific: no email, no case ID, no
  evidence. Identical texts therefore give identical requests, so the reply cache routes them
  identically, and evidence cannot sway the intent.
* **The model decides** (T63 pin 1; T7). The label is the model's answer; code never overrides it
  with a phrase table. ``UNCERTAIN`` is a legal answer.
* **basis_quote is checked in code** (G7a brief item 1): it must be a substring of the request
  text (exactly, or after Unicode NFC and whitespace collapsing). A failed check means the answer
  is not a validated model answer: a final answer's label is read as ``UNCERTAIN`` (flag
  ``BASIS_QUOTE_INVALID``), which routes to a tool or to the fail-closed row (T71 Q2), and an
  ``audit_case`` commit with a bad quote is refused and not committed. An
  ``UNCERTAIN`` answer may carry an empty quote.
* **Failures are explicit** (``../CLAUDE.md`` section 3): a failed call gives an
  :class:`~deletion_audit.record.IntentDecision` with ``source`` ``FAILED_CLOSED`` or
  ``FAILED_BUDGET`` and no label, which the engine turns into its deletion-path row, flagged
  ``INTENT_FAILED_CLOSED`` / ``INTENT_FAILED_BUDGET`` (T71 Q2, T87). Never NOT_APPLICABLE, and never
  a value copied from the input.
"""

from __future__ import annotations

import json
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from ..model import ModelCallFailed, ModelClient, ModelReply, ModelRequest, reply_text, tool_uses
from ..record import CrossCheck, IntentDecision
from .params import EFFORT_ROUTING, MAX_TOKENS_TURN1, MODEL
from .prompting import fence, load_prompt
from .schemas import FINAL_ANSWER_SCHEMA, FinalAnswer, IntentAnswer, SchemaError, parse_audit_case_input, parse_final

REQUEST_TAG = "request_text"
BUDGET_REASONS: frozenset[str] = frozenset({"BUDGET", "CALL_CAP"})
CommitVia = Literal["audit_case", "final_answer", "failed"]


def _squash(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).split())


def quote_in_text(quote: str, text: str) -> bool:
    """Whether ``quote`` (non-empty) occurs in ``text`` exactly, or after NFC and whitespace collapse."""
    if not quote.strip():
        return False
    return quote in text or _squash(quote) in _squash(text)


def answer_is_valid(answer: IntentAnswer, text: str) -> bool:
    """A committed intent counts only when its quote is in the text (an UNCERTAIN may quote nothing)."""
    if answer.intent == "UNCERTAIN" and not answer.basis_quote.strip():
        return True
    return quote_in_text(answer.basis_quote, text)


def turn1_user_message(text: str) -> dict[str, Any]:
    """The one user message of turn 1: the fenced, defanged request text."""
    return {"role": "user", "content": [{"type": "text", "text": fence(text, REQUEST_TAG)}]}


def base_body(tools: Sequence[dict[str, Any]], messages: list[dict[str, Any]], *, max_tokens: int,
              tool_choice: str = "auto") -> dict[str, Any]:
    """A conversation request body: fixed model, system prompt, tools, answer schema and effort."""
    return {
        "model": MODEL,
        "max_tokens": max_tokens,
        "system": load_prompt("system"),
        "tools": [dict(t) for t in tools],
        "tool_choice": {"type": tool_choice},
        "messages": messages,
        "output_config": {"effort": EFFORT_ROUTING, "format": {"type": "json_schema", "schema": FINAL_ANSWER_SCHEMA}},
    }


def turn1_request(text: str, tools: Sequence[dict[str, Any]]) -> ModelRequest:
    """The turn-1 request for ``text``: identical for identical texts, in every mode."""
    return ModelRequest(base_body(tools, [turn1_user_message(text)], max_tokens=MAX_TOKENS_TURN1))


@dataclass(frozen=True)
class Turn1:
    """What one turn-1 reply committed.

    ``label`` is the committed intent after the quote check (``UNCERTAIN`` when the quote failed);
    ``answer`` is the parsed answer as given; ``via`` says how it was given; ``tool_use`` is the
    ``audit_case`` block when that was the commit; ``other_tool_uses`` are tool calls made before
    any commit (refused by the harness). ``failure`` holds the ModelCallFailed reason when the call
    failed, and then ``label`` is None.
    """

    label: str | None
    answer: IntentAnswer | None
    via: CommitVia
    quote_valid: bool | None
    request_key: str
    reply: ModelReply | None
    tool_use: dict[str, Any] | None = None
    other_tool_uses: tuple[dict[str, Any], ...] = ()
    final: FinalAnswer | None = None
    failure: str | None = None
    error_class: str | None = None


def _plain(value: Any) -> Any:
    """A plain JSON copy of a (possibly read-only) reply value."""
    return json.loads(json.dumps(value, default=dict))


def read_commit(text: str, req: ModelRequest, reply: ModelReply) -> Turn1:
    """Interpret a structurally valid turn-1 reply (an ``audit_case`` call or a final answer)."""
    uses = [_plain(u) for u in tool_uses(reply.raw)]
    if uses:
        audit = [u for u in uses if u.get("name") == "audit_case"]
        others = tuple(u for u in uses if u.get("name") != "audit_case")
        for use in audit:
            try:
                answer = parse_audit_case_input(use.get("input"))
            except SchemaError:
                continue
            ok = answer_is_valid(answer, text)
            if ok:
                return Turn1("DELETION_REQUEST", answer, "audit_case", True, req.key(), reply, use, others)
        return Turn1(None, None, "audit_case", False, req.key(), reply, None, tuple(uses))
    value = json.loads(reply_text(reply.raw) or "null")
    final = parse_final(value)
    ok = answer_is_valid(final.intent, text)
    label = final.intent.intent if ok else "UNCERTAIN"
    return Turn1(label, final.intent, "final_answer", ok, req.key(), reply, final=final)


def run_turn1(text: str, tools: Sequence[dict[str, Any]], client: ModelClient) -> Turn1:
    """Send turn 1 for ``text`` through ``client``; a failed call is an explicit failure value."""
    req = turn1_request(text, tools)
    try:
        reply = client.call(req)
    except ModelCallFailed as exc:
        return Turn1(None, None, "failed", None, req.key(), None, failure=exc.reason, error_class=exc.error_class)
    try:
        return read_commit(text, req, reply)
    except (SchemaError, ValueError) as exc:
        return Turn1(None, None, "failed", None, req.key(), reply, failure="UNPARSEABLE",
                     error_class=type(exc).__name__)


def failed_source(reason: str | None) -> Literal["FAILED_CLOSED", "FAILED_BUDGET"]:
    """``FAILED_BUDGET`` for a budget or call-cap refusal, else ``FAILED_CLOSED`` (T71 Q2)."""
    return "FAILED_BUDGET" if reason in BUDGET_REASONS else "FAILED_CLOSED"


def agreement(label: str | None, cc: CrossCheck) -> bool | None:
    """Whether a decided label agrees with the intake cross-check (Q10); None when undecided."""
    if label not in ("DELETION_REQUEST", "NOT_DELETION"):
        return None
    return (label == "NOT_DELETION") == cc.intake_non_deletion


def decision(label: str | None, source: str, cc: CrossCheck, committed_key: str | None,
             final_key: str | None) -> IntentDecision:
    """An :class:`IntentDecision`; an undecided label (None or UNCERTAIN) always fails closed.

    A label that is not DELETION_REQUEST or NOT_DELETION can never become NOT_APPLICABLE: the
    source is forced to FAILED_CLOSED unless it is already a failure source (T71 Q2).
    """
    if label not in ("DELETION_REQUEST", "NOT_DELETION") and source not in ("FAILED_CLOSED", "FAILED_BUDGET"):
        source = "FAILED_CLOSED"
    return IntentDecision(
        label=label,  # type: ignore[arg-type]
        source=source,  # type: ignore[arg-type]
        committed_key=committed_key,
        final_key=final_key,
        crosscheck=cc,
        agrees=agreement(label, cc),
    )
