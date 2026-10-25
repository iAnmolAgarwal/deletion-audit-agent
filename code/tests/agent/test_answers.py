"""Answer validation (G7a brief item 6), settled facts untouched (T10/T42), the two compilations."""

from __future__ import annotations

import unittest
from dataclasses import replace
from typing import Any

from deletion_audit.agent import audit_with_agent, validate_answers
from deletion_audit.agent.answers import ValidatedAnswer, patch_image_observations
from deletion_audit.agent.questions import oq_id
from deletion_audit.agent.schemas import VisionRecord
from deletion_audit.agent.vision import image_observation
from deletion_audit.evidence.model import FileRef

from ._support import ADA, C1, PNG, Rig, answer, answer_for, audit_input, dataset, final_reply, tool_reply, world_of

DONE_ARGS = {"intent": "DELETION_REQUEST", "quote": "delete my account", "kind": "full_deletion"}


def done(*answers: dict[str, Any], cannot: tuple[dict[str, Any], ...] = ()) -> dict[str, Any]:
    return final_reply(answer(DONE_ARGS["intent"], DONE_ARGS["quote"], kind=DONE_ARGS["kind"], answers=answers,
                              cannot=cannot))


class TestValidation(unittest.TestCase):
    """Every rejected answer is recorded with its reason, never applied."""

    def setUp(self) -> None:
        self.w = world_of(dataset(intake_for_ada=True))
        self.qid = oq_id(C1, "INTENT_CROSSCHECK", "request")

    def run_with(self, *answers: dict[str, Any], cannot: tuple[dict[str, Any], ...] = (),
                 extra: tuple[dict[str, Any], ...] = ()) -> dict[str, Any]:
        rig = Rig([tool_reply(("audit_case", audit_input())), *extra, done(*answers, cannot=cannot)])
        return audit_with_agent(C1, self.w, rig.client, mode="A+").report

    def test_unknown_question(self) -> None:
        r = self.run_with(answer_for("q_000000000000", "DELETION_REQUEST"))
        self.assertEqual(r["answers_rejected"], [{"oq_id": "q_000000000000", "reason": "UNKNOWN_QUESTION"}])

    def test_choice_not_allowed(self) -> None:
        r = self.run_with(answer_for(self.qid, "UNCERTAIN"))
        self.assertEqual(r["answers_rejected"][0]["reason"], "CHOICE_NOT_ALLOWED")

    def test_evidence_must_exist_be_before_audit_and_have_been_shown(self) -> None:
        cases = {"no_such_file": "EVIDENCE_UNKNOWN", "a_9": "EVIDENCE_AFTER_AUDIT", "a_3": "EVIDENCE_NOT_SEEN"}
        for eid, reason in cases.items():
            r = self.run_with(answer_for(self.qid, "DELETION_REQUEST", [eid]))
            self.assertEqual(r["answers_rejected"], [{"oq_id": self.qid, "reason": reason}], eid)
            self.assertEqual(r["answers_applied"], [])

    def test_intent_answer_must_match_the_final_intent(self) -> None:
        r = self.run_with(answer_for(self.qid, "NOT_DELETION"))
        self.assertEqual(r["answers_rejected"][0]["reason"], "INCONSISTENT_WITH_FINAL_INTENT")

    def test_duplicate_and_contradicting_answers(self) -> None:
        a = answer_for(self.qid, "DELETION_REQUEST")
        r = self.run_with(a, a)
        self.assertEqual(r["answers_applied"], [self.qid])
        self.assertEqual(r["answers_rejected"], [{"oq_id": self.qid, "reason": "DUPLICATE_ANSWER"}])
        r2 = self.run_with(a, cannot=({"oq_id": self.qid, "reason": "NO_EVIDENCE"},))
        self.assertEqual(r2["answers_rejected"][0]["reason"], "CONTRADICTS_CANNOT_ANSWER")

    def test_seen_evidence_answer_is_applied(self) -> None:
        extra = (tool_reply(("get_request_context", {})),)
        r = self.run_with(answer_for(self.qid, "DELETION_REQUEST", ["a_3"]), extra=extra)
        self.assertEqual((r["answers_applied"], r["answers_rejected"]), ([self.qid], []))
        self.assertFalse(r["steps_differ_when_applied"])  # it confirmed the commit

    def test_no_final_answer_means_no_answers(self) -> None:
        w = world_of(dataset())
        rig = Rig([tool_reply(("audit_case", audit_input()))])
        result = audit_with_agent(C1, w, rig.client, mode="A")
        self.assertEqual(validate_answers(result.outcome, w.validation, "2026-05-04T12:00:00Z").validated, ())


class TestSettledFacts(unittest.TestCase):
    """T10/T42: an answer never changes a settled fact."""

    def test_answer_never_changes_settled_fact(self) -> None:
        """An answer to no posed question is rejected and the row is identical to the one without it."""
        w = world_of(dataset())
        plain = Rig([tool_reply(("audit_case", audit_input())), done()])
        base = audit_with_agent(C1, w, plain.client, mode="A+")
        # No question is posed, so even a well-formed answer naming a settled resource is rejected,
        # and the row is unchanged.
        rig = Rig([tool_reply(("audit_case", audit_input())),
                   done(answer_for("q_settledfact", "ABSENT", ["ev_1"]))])
        tried = audit_with_agent(C1, w, rig.client, mode="A+")
        self.assertEqual(tried.report["answers_rejected"], [{"oq_id": "q_settledfact", "reason": "UNKNOWN_QUESTION"}])
        self.assertEqual(tried.applied.steps, base.applied.steps)
        self.assertEqual(tried.applied.resources, base.applied.resources)
        self.assertFalse(tried.report["steps_differ_when_applied"])

    def test_subject_conflict_answer_is_noted_and_changes_nothing(self) -> None:
        w0 = world_of(dataset(image=PNG))
        other = VisionRecord("data_flow_900000003", ("someone.else@example.test",), (), ("Someone Else",), (),
                             "yes", "not_shown", "not_shown", "not_shown")
        ref = FileRef("ev_img", "images/console.png", "fixture", "2026-05-02T11:00:00Z")
        obs = image_observation(ref, "data_flow_900000003", "integration_service", other)
        w = world_of(dataset(image=PNG), image_observations=[obs])
        self.assertIsNotNone(w0)
        qid = oq_id(C1, "IMAGE_SUBJECT_CONFLICT", "data_flow_900000003")
        rig = Rig([tool_reply(("audit_case", audit_input())), tool_reply(("inspect_evidence", {"file_id": "ev_img",
                                                                                              "focus": "identity"})),
                   done(answer_for(qid, "SUBJECT_DIFFERS", ["ev_img"]))])
        result = audit_with_agent(C1, w, rig.client, mode="A+")
        self.assertIn(qid, [q.oq_id for q in result.outcome.questions])
        self.assertEqual((result.report["answers_noted"], result.report["answers_applied"]), ([qid], []))
        self.assertFalse(result.report["steps_differ_when_applied"])
        self.assertIn("data_flow_900000003", [r.key.resource_id for r in result.applied.resources])  # T71 Q11


class TestImagePatches(unittest.TestCase):
    """An IMAGE_FIELD_UNREADABLE answer fills exactly its slot and nothing else."""

    def test_patch_fills_one_attribute(self) -> None:
        ref = FileRef("ev_img", "images/console.png", "fixture", "2026-05-02T11:00:00Z")
        rec = VisionRecord("data_flow_900000003", (ADA,), (), (), (), "unreadable", "not_shown", "not_shown",
                           "not_shown")
        obs = image_observation(ref, "data_flow_900000003", "integration_service", rec)
        self.assertNotIn("enabled", obs.attrs)
        slot = "image_field:ev_img:data_flow_900000003:sync_enabled"
        patched = patch_image_observations([obs], [ValidatedAnswer("q_x", "IMAGE_FIELD_UNREADABLE", slot, "yes",
                                                                   ("ev_img",))])
        self.assertEqual(dict(patched[0].attrs)["enabled"], "true")
        self.assertEqual(replace(patched[0], attrs=obs.attrs), obs)  # nothing else changed
        ignored = patch_image_observations([obs], [ValidatedAnswer("q_y", "IMAGE_SUBJECT_CONFLICT", None,
                                                                   "SUBJECT_DIFFERS", ("ev_img",))])
        self.assertEqual(ignored, (obs,))


if __name__ == "__main__":
    unittest.main()
