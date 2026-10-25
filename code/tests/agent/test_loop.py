"""The loop: caps, final turn with tool_choice none, modes, routing-consistency rules, failures."""

from __future__ import annotations

import unittest
from unittest import mock

from deletion_audit.agent import LoopCaps, audit_with_agent, run_case
from deletion_audit.agent import loop as loop_mod
from deletion_audit.agent.questions import oq_id

from ._support import (
    C1,
    DELETE_TEXT,
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

DONE = final_reply(answer("DELETION_REQUEST", "delete my account", kind="full_deletion"))
AUDIT = tool_reply(("audit_case", audit_input()))


class TestCaps(unittest.TestCase):
    """At most 4 tool calls, then one request with tool_choice none (../CLAUDE.md section 5)."""

    def test_loop_cap_four_tool_calls_then_tool_choice_none(self) -> None:
        w = world_of(dataset())
        script = [AUDIT, tool_reply(("list_activity", {"identifier_or_resource": "account_900000001"})),
                  tool_reply(("get_request_context", {})),
                  tool_reply(("lookup_identity", {"value": "ada@example.test"}),
                             ("list_activity", {"identifier_or_resource": "ada@example.test"})),
                  DONE]
        rig = Rig(script)
        out = run_case(C1, w, rig.client, mode="A+")
        self.assertEqual(sum(1 for c in out.tool_calls if not c.is_error), 4)
        self.assertEqual(len(out.tool_calls), 5)  # the fifth was refused, never run
        self.assertTrue(out.tool_calls[-1].is_error)
        self.assertIn("CALL_PAST_CAP_REFUSED", {f.code for f in out.flags})
        self.assertEqual(bodies_tool_choice(rig), ["auto", "auto", "auto", "auto", "none"])
        self.assertEqual((out.status, out.final is not None), ("FINALIZED_AT_CAP", True))

    def test_four_calls_in_one_reply_then_none(self) -> None:
        w = world_of(dataset())
        many = tool_reply(("audit_case", audit_input()), ("get_request_context", {}),
                          ("list_activity", {"identifier_or_resource": "account_900000001"}),
                          ("lookup_identity", {"value": "ada@example.test"}),
                          ("list_activity", {"identifier_or_resource": "ada@example.test"}))
        rig = Rig([many, DONE])
        out = run_case(C1, w, rig.client, mode="A+")
        self.assertEqual([c.is_error for c in out.tool_calls], [False, False, False, False, True])
        self.assertEqual(bodies_tool_choice(rig), ["auto", "none"])
        last = rig.sent()[-1]["messages"][-1]["content"]
        self.assertEqual([b["tool_use_id"] for b in last], [f"toolu_{i}" for i in range(1, 6)])  # every use answered

    def test_request_cap_forces_the_final_turn(self) -> None:
        w = world_of(dataset())
        caps = LoopCaps(max_tool_calls=4, max_requests=3)
        rig = Rig([AUDIT, tool_reply(("get_request_context", {})), DONE])
        out = run_case(C1, w, rig.client, mode="A+", caps=caps)
        self.assertEqual(bodies_tool_choice(rig), ["auto", "auto", "none"])
        self.assertIn("REQUEST_CAP", {f.code for f in out.flags})

    def test_wall_clock_cap_forces_the_final_turn(self) -> None:
        w = world_of(dataset())
        ticks = iter([0.0] + [500.0] * 10)  # the case starts at 0 s; every later reading is past 180 s
        rig = Rig([AUDIT, DONE])
        out = run_case(C1, w, rig.client, mode="A+", clock=lambda: next(ticks))
        self.assertEqual(bodies_tool_choice(rig), ["auto", "none"])
        self.assertEqual(out.status, "FINALIZED_AT_CAP")

    def test_hard_bound_ends_the_case_failed_even_if_no_cap_forces_a_final_turn(self) -> None:
        """With every forcing cap disabled, the loop still stops after max_requests + LOOP_SLACK sends."""
        w = world_of(dataset())
        endless = [AUDIT] + [tool_reply(("list_activity", {"identifier_or_resource": f"acct_{i}"})) for i in range(30)]
        rig = Rig(endless)
        caps = LoopCaps(max_tool_calls=4, max_requests=3)
        with mock.patch.object(loop_mod._Case, "_force_reason", return_value=None):
            out = run_case(C1, w, rig.client, mode="A+", caps=caps)
        self.assertEqual((out.status, out.failure), ("FAILED", "LOOP_BOUND"))
        self.assertEqual(len(rig.sent()), 1 + caps.max_requests + loop_mod.LOOP_SLACK)

    def test_no_repeated_identical_tool_call(self) -> None:
        w = world_of(dataset())
        same = ("list_activity", {"identifier_or_resource": "account_900000001"})
        rig = Rig([AUDIT, tool_reply(same), tool_reply(same), DONE])
        out = run_case(C1, w, rig.client, mode="A+")
        self.assertEqual([c.is_error for c in out.tool_calls], [False, False, True])
        self.assertEqual(out.tool_calls[1].args_hash, out.tool_calls[2].args_hash)
        self.assertIn("REPEATED_TOOL_CALL", {f.code for f in out.flags})

    def test_tool_choice_never_any_or_tool_and_no_sampling_parameters_sent(self) -> None:
        w = world_of(dataset())
        rig = Rig([AUDIT, tool_reply(("get_request_context", {})), DONE])
        audit_with_agent(C1, w, rig.client, mode="A+")
        for body in rig.sent():
            self.assertIn(body["tool_choice"]["type"], ("auto", "none"))
            for banned in ("temperature", "top_p", "top_k", "stream"):
                self.assertNotIn(banned, body)
            self.assertEqual(body["output_config"]["effort"], "medium")
            self.assertEqual(body["model"], "claude-sonnet-5-5")


class TestModes(unittest.TestCase):
    """A+, A and tools_off in the same code (T70; G3 sections 1.1-1.3)."""

    def test_a_plus_always_returns_the_brief_and_finishes(self) -> None:
        w = world_of(dataset())
        rig = Rig([AUDIT, DONE])
        result = audit_with_agent(C1, w, rig.client, mode="A+")
        self.assertEqual(rig.transport.calls, 2)
        brief = rig.sent()[1]["messages"][-1]["content"][0]
        self.assertEqual(brief["type"], "tool_result")
        self.assertIn('"read_only": true', brief["content"].replace(" ", "").replace('"read_only":true',
                                                                                      '"read_only": true'))
        self.assertEqual((result.report["audit_case_calls"], result.report["status"]), (1, "OK"))
        self.assertEqual(result.applied.status, "INCOMPLETE")

    def test_a_stops_after_turn1_when_no_question(self) -> None:
        w = world_of(dataset())
        rig = Rig([AUDIT, DONE])
        result = audit_with_agent(C1, w, rig.client, mode="A")
        self.assertEqual(rig.transport.calls, 1)
        self.assertEqual((result.intent.label, result.intent.source), ("DELETION_REQUEST", "MODEL"))
        self.assertEqual(result.applied.status, "INCOMPLETE")

    def test_a_continues_when_a_question_exists(self) -> None:
        w = world_of(dataset(intake_for_ada=True))
        rig = Rig([AUDIT, DONE])
        result = audit_with_agent(C1, w, rig.client, mode="A")
        self.assertEqual(rig.transport.calls, 2)
        self.assertEqual([q.type for q in result.outcome.questions], ["INTENT_CROSSCHECK"])

    def test_tools_off_runs_turn1_only(self) -> None:
        w = world_of(dataset(intake_for_ada=True))
        rig = Rig([AUDIT, DONE])
        result = audit_with_agent(C1, w, rig.client, mode="tools_off")
        self.assertEqual(rig.transport.calls, 1)
        self.assertEqual(result.report["tool_calls"], [])
        self.assertIn("INTENT_CROSSCHECK_DISAGREES", result.report["flags"])
        self.assertEqual(result.intent.label, "DELETION_REQUEST")

    def test_unknown_mode_is_refused(self) -> None:
        w = world_of(dataset())
        with self.assertRaises(ValueError):
            run_case(C1, w, Rig([]).client, mode="B")  # type: ignore[arg-type]


class TestRouting(unittest.TestCase):
    """G3 section 1.2 routing-consistency rules."""

    def test_routing_consistency_drift_and_no_audit_call(self) -> None:
        w = world_of(dataset())
        # Drift: committed deletion, final says not-deletion twice: the commit stands, flagged.
        drift = final_reply(answer("NOT_DELETION", "delete my account", kind="other"))
        rig = Rig([AUDIT, drift, drift])
        result = audit_with_agent(C1, w, rig.client, mode="A+")
        self.assertEqual(rig.transport.calls, 3)  # one repair turn
        self.assertIn("INTENT_DRIFT", result.report["flags"])
        self.assertEqual((result.intent.label, result.applied.status), ("DELETION_REQUEST", "INCOMPLETE"))
        # No audit call: a deletion answer at turn 1 gets one nudge, then NO_AUDIT_CALL; row unaffected.
        rig2 = Rig([DONE, DONE])
        result2 = audit_with_agent(C1, w, rig2.client, mode="A+")
        self.assertIn("audit_case", str(rig2.sent()[1]["messages"][-1]))
        self.assertIn("NO_AUDIT_CALL", result2.report["flags"])
        self.assertEqual((result2.intent.label, result2.applied.status), ("DELETION_REQUEST", "INCOMPLETE"))

    def test_tools_are_refused_before_the_intent_is_committed(self) -> None:
        w = world_of(dataset())
        rig = Rig([tool_reply(("list_activity", {"identifier_or_resource": "account_900000001"})), AUDIT, DONE])
        out = run_case(C1, w, rig.client, mode="A+")
        self.assertEqual([(c.name, c.is_error) for c in out.tool_calls],
                         [("list_activity", True), ("audit_case", False)])
        self.assertEqual(out.tool_calls[0].evidence_ids, ())  # nothing was shown before the commit
        self.assertEqual(out.committed_label, "DELETION_REQUEST")
        self.assertEqual(out.committed_key, out.reply_keys[1])

    def test_audit_case_with_a_made_up_quote_is_refused(self) -> None:
        w = world_of(dataset())
        bad = tool_reply(("audit_case", audit_input("erase all of it")))
        rig = Rig([bad, AUDIT, DONE])
        out = run_case(C1, w, rig.client, mode="A+")
        self.assertEqual([c.is_error for c in out.tool_calls], [True, False])
        self.assertIn("BASIS_QUOTE_INVALID", {f.code for f in out.flags})

    def test_crosscheck_question_lets_the_model_change_its_mind(self) -> None:
        w = world_of(dataset(text_ada="Please send me my data, and also delete my account."))
        w2 = world_of(dataset(text_ada="Please send me my data, and also delete my account.", intake_for_ada=True))
        qid = oq_id(C1, "INTENT_CROSSCHECK", "request")
        keep = final_reply(answer("NOT_DELETION", "Please send me my data", answers=[
            {"oq_id": qid, "choice": "NOT_DELETION", "evidence_ids": ["a_3"], "note": "intake row"}]))
        rig = Rig([AUDIT, tool_reply(("get_request_context", {})), keep])
        result = audit_with_agent(C1, w2, rig.client, mode="A+")
        self.assertEqual((result.intent.label, result.intent.source), ("NOT_DELETION", "MODEL_AFTER_TOOLS"))
        self.assertEqual(result.applied.status, "NOT_APPLICABLE")
        self.assertTrue(result.report["steps_differ_when_applied"])
        self.assertIsNotNone(w)


class TestFailures(unittest.TestCase):
    """T71 Q2: a failed call ends the case explicitly; a commit made before it stands."""

    def test_turn2_failure_keeps_the_commit(self) -> None:
        w = world_of(dataset())
        rig = Rig([AUDIT, failure(400, "BadRequestError")])
        result = audit_with_agent(C1, w, rig.client, mode="A+")
        self.assertEqual((result.outcome.status, result.outcome.failure), ("FAILED", "NON_RETRYABLE"))
        self.assertEqual((result.intent.label, result.intent.source), ("DELETION_REQUEST", "MODEL"))
        self.assertIn("AGENT_CALL_FAILED", result.report["flags"])
        self.assertEqual(result.applied.status, "INCOMPLETE")

    def test_retryable_failures_are_retried_by_gm_not_here(self) -> None:
        w = world_of(dataset())
        rig = Rig([failure(529, "OverloadedError"), AUDIT, DONE])
        result = audit_with_agent(C1, w, rig.client, mode="A+")
        self.assertEqual((result.outcome.status, rig.transport.calls), ("OK", 3))

    def test_call_cap_mid_loop_is_failed_budget_only_without_a_commit(self) -> None:
        w = world_of(dataset())
        rig = Rig([AUDIT, DONE], call_cap=1)
        result = audit_with_agent(C1, w, rig.client, mode="A+")
        self.assertEqual((result.outcome.failure, result.intent.source), ("CALL_CAP", "MODEL"))
        rig2 = Rig([AUDIT], call_cap=0)
        result2 = audit_with_agent(C1, w, rig2.client, mode="A+")
        self.assertEqual(result2.intent.source, "FAILED_BUDGET")

    def test_replay_only_miss_is_a_failure(self) -> None:
        w = world_of(dataset())
        rig = Rig([], replay_only=True)
        result = audit_with_agent(C1, w, rig.client, mode="A+")
        self.assertEqual((result.outcome.failure, result.intent.source), ("REPLAY_MISS", "FAILED_CLOSED"))
        self.assertTrue(DELETE_TEXT)


if __name__ == "__main__":
    unittest.main()
