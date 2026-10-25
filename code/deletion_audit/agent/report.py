"""JSON-ready per-case and run-level agent reports, for ``cases.jsonl`` and the vision artifact.

Field names are fixed by the G7a brief because G7b's ``evaluation/agent_report.py`` reads them.
Three fields are added beside them (additions, no renames): ``answers_noted`` (validated answers to
a question with no slot, which change nothing), ``instruction_like_text`` (the code check, the
model's flag and their merged value; T95 item 1) and ``replies`` (the reply keys, so a report can
be traced to the reply cache). Values are labels, IDs, keys, counts and flag codes only; never request
text or an identifier (``artifacts.py`` rule).

Wiring additions (G7 wiring brief):

* ``intent.committed_label`` and ``intent.final_label`` (developer ruling T92): the intent labels the
  conversation committed and finally answered. ``committed_key`` and ``final_key`` stay as provenance
  (they are reply-cache keys, so their equality says nothing about intent); a report compares labels.
* ``turn1_replicates`` holds the turn-1 label of every reading of the text: the case's own turn 1
  first, then each replicate namespace's (T70 "both replicate runs"; T101 (2a) "in both replicate
  runs"). A failed reading is null. With no replicate client it holds one label.
"""

from __future__ import annotations

from typing import Any

from ..record import IntentDecision
from .answers import AnswerCheck
from .loop import AgentOutcome
from .vision import VisionRun, image_report


def agent_case_report(outcome: AgentOutcome, check: AnswerCheck, intent: IntentDecision,
                      steps_differ: bool) -> dict[str, Any]:
    """The ``"agent"`` object of one ``cases.jsonl`` line (pure; same inputs, same dict)."""
    flags = {f.code for f in outcome.flags}
    flags |= {f"ANSWER_REJECTED_{r.reason}" for r in check.rejected}
    if intent.source in ("FAILED_CLOSED", "FAILED_BUDGET"):
        flags.add("INTENT_" + intent.source)
    return {
        "mode": outcome.mode,
        "intent": {
            "label": intent.label,
            "source": intent.source,
            "committed_key": intent.committed_key,
            "final_key": intent.final_key,
            "committed_label": outcome.committed_label,
            "final_label": outcome.final.intent.intent if outcome.final is not None else None,
            "agrees": intent.agrees,
            "crosscheck": {
                "intake_non_deletion": intent.crosscheck.intake_non_deletion,
                "activity_ids": list(intent.crosscheck.activity_ids),
            },
        },
        "turn1_replicates": [outcome.turn1.label, *outcome.replicates],
        "tool_calls": [
            {"name": c.name, "args_hash": c.args_hash, "is_error": c.is_error, "evidence_ids": list(c.evidence_ids)}
            for c in outcome.tool_calls if c.name != "audit_case"
        ],
        "audit_case_calls": sum(1 for c in outcome.tool_calls if c.name == "audit_case"),
        "answers_applied": list(check.applied()),
        "answers_noted": list(check.noted()),
        "answers_rejected": [{"oq_id": r.oq_id, "reason": r.reason} for r in check.rejected],
        "steps_differ_when_applied": steps_differ,
        "status": outcome.status,
        "flags": sorted(flags),
        "instruction_like_text": outcome.instruction.as_json(),
        "replies": list(outcome.reply_keys),
    }


def vision_run_report(run: VisionRun) -> list[dict[str, Any]]:
    """The run-level vision list: one item per image (fields fixed by the G7a brief)."""
    return [image_report(r) for r in run.records]
