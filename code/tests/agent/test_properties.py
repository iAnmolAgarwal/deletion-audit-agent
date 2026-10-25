"""Property tests with seeded random scripts (Hypothesis is not installed; G3 section 11).

For every random script of model replies, in every mode:

* the loop never runs more than 4 tool calls, sends only ``auto``/``none`` tool choices and no
  sampling parameter, and never sends more than ``max_requests`` requests;
* status is derived from the steps: NOT_APPLICABLE only for a validated NOT_DELETION and then
  ``[]``; INCOMPLETE exactly when a FINDING exists or the row failed closed; steps numbered from 1
  and in phase, operation, system, resource order;
* an undecided or failed intent is never NOT_APPLICABLE;
* the same script gives the same report and the same steps (determinism).
"""

from __future__ import annotations

import json
import random
import unittest
from typing import Any

from deletion_audit.agent import audit_with_agent
from deletion_audit.agent.questions import oq_id
from deletion_audit.record import derive_status

from ..steps.test_steps import hand_key
from ._support import (
    C1,
    C2,
    DELETE_TEXT,
    KEEP_TEXT,
    Rig,
    answer,
    audit_input,
    bodies_tool_choice,
    dataset,
    failure,
    final_reply,
    tool_reply,
    world_of,
)

SEEDS = range(60)
TEXTS = {C1: DELETE_TEXT, C2: KEEP_TEXT}


def random_reply(rng: random.Random, case_id: str) -> Any:
    """One random reply or transport failure."""
    text = TEXTS[case_id]
    start = rng.randrange(0, len(text) - 6)
    quote = text[start:start + rng.randrange(5, 20)] if rng.random() < 0.8 else "made-up words"
    label = rng.choice(["DELETION_REQUEST", "NOT_DELETION", "UNCERTAIN"])
    qtype = rng.choice(["INTENT_UNCERTAIN", "INTENT_CROSSCHECK"])
    entry = {"oq_id": oq_id(case_id, qtype, "request"), "choice": rng.choice(["DELETION_REQUEST", "NOT_DELETION"]),
             "evidence_ids": rng.choice([[], ["a_2"], ["ev_1"], ["nope"]]), "note": "n"}
    answers = [entry] if rng.random() < 0.4 else []
    tools: list[tuple[str, dict[str, Any]]] = [
        ("audit_case", audit_input(quote)),
        ("get_request_context", {}),
        ("list_activity", {"identifier_or_resource": rng.choice(["account_900000001", "account_900000002", "ab"])}),
        ("lookup_identity", {"value": rng.choice(["ada@example.test", "bo@example.test", "zzz"])}),
        ("inspect_evidence", {"file_id": rng.choice(["ev_1", "ev_late", "nope"]), "focus": "records"}),
        ("not_a_tool", {}),
    ]
    roll = rng.random()
    if roll < 0.45:
        return tool_reply(*rng.sample(tools, rng.randrange(1, 4)))
    if roll < 0.9:
        return final_reply(answer(label, quote, kind="other", answers=answers))
    if roll < 0.95:
        return final_reply(answer(label, quote), stop_reason=rng.choice(["max_tokens", "refusal"]))
    return failure(rng.choice([400, 529]), "SomeError")


def run_script(seed: int) -> tuple[Any, Rig]:
    rng = random.Random(seed)
    case_id = rng.choice([C1, C2])
    mode = rng.choice(["A+", "A", "tools_off"])
    script = [random_reply(rng, case_id) for _ in range(14)]
    w = world_of(dataset(intake_for_ada=rng.random() < 0.3))
    rig = Rig(script)
    return audit_with_agent(case_id, w, rig.client, mode=mode), rig  # type: ignore[arg-type]


class TestProperties(unittest.TestCase):
    def test_loop_bounds_hold_for_random_scripts(self) -> None:
        for seed in SEEDS:
            result, rig = run_script(seed)
            executed = sum(1 for c in result.outcome.tool_calls if not c.is_error)
            self.assertLessEqual(executed, 4, seed)
            self.assertLessEqual(len(result.outcome.reply_keys), 6, seed)
            self.assertTrue(set(bodies_tool_choice(rig)) <= {"auto", "none"}, seed)
            for body in rig.sent():
                self.assertFalse({"temperature", "top_p", "top_k"} & set(body), seed)

    def test_status_derived_from_steps_for_random_scripts(self) -> None:
        for seed in SEEDS:
            result, _ = run_script(seed)
            rec = result.applied
            self.assertEqual(rec.status, derive_status(rec.intent, rec.steps, rec.failed_closed), seed)
            if rec.status == "NOT_APPLICABLE":
                self.assertEqual(rec.steps, (), seed)
                self.assertEqual(rec.intent.label, "NOT_DELETION", seed)
                self.assertIn(rec.intent.source, ("MODEL", "MODEL_AFTER_TOOLS"), seed)
            has_finding = any(s.phase == "FINDING" for s in rec.steps)
            if rec.status != "NOT_APPLICABLE":
                self.assertEqual(rec.status == "INCOMPLETE", has_finding or rec.failed_closed is not None, seed)
            self.assertEqual([s.step_no for s in rec.steps], list(range(1, len(rec.steps) + 1)), seed)
            # T63 pin 5: the order is checked with the hand-written contract key, never the production one
            keys = [hand_key(s.phase, s.operation, s.system_id, s.resource_id) for s in rec.steps]
            self.assertEqual(keys, sorted(keys), seed)
            if result.intent.label in (None, "UNCERTAIN"):
                self.assertNotEqual(rec.status, "NOT_APPLICABLE", seed)
                self.assertIn(result.intent.source, ("FAILED_CLOSED", "FAILED_BUDGET"), seed)

    def test_same_script_same_report(self) -> None:
        for seed in range(0, 60, 6):
            a, _ = run_script(seed)
            b, _ = run_script(seed)
            self.assertEqual(json.dumps(a.report, sort_keys=True), json.dumps(b.report, sort_keys=True), seed)
            self.assertEqual(a.applied.steps, b.applied.steps, seed)


if __name__ == "__main__":
    unittest.main()
