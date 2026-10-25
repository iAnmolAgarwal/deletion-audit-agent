"""The per-case ``"agent"`` object and the run-level vision list: fixed field names, pure, no cell text."""

from __future__ import annotations

import json
import unittest

from deletion_audit.agent import audit_with_agent, read_images, vision_run_report
from deletion_audit.agent.idshapes import learn_shapes
from deletion_audit.agent.report import agent_case_report

from ._support import ADA, C1, DELETE_TEXT, PNG, Rig, answer, audit_input, dataset, final_reply, tool_reply, world_of

CASE_FIELDS = {"mode", "intent", "turn1_replicates", "tool_calls", "audit_case_calls", "answers_applied",
               "answers_rejected", "steps_differ_when_applied", "status", "flags"}
INTENT_FIELDS = {"label", "source", "committed_key", "final_key", "committed_label", "final_label", "agrees",
                 "crosscheck"}
VISION_FIELDS = {"file_id", "readings", "agree", "disagreements", "flags", "resource_ids"}
ID_FIELDS = {"system_id", "resource_id", "well_formed", "named_elsewhere"}


class TestCaseReport(unittest.TestCase):
    """G7a brief: the names G7b reads."""

    def setUp(self) -> None:
        w = world_of(dataset())
        audit = tool_reply(("audit_case", audit_input()))
        # turn 1, then the replicate's own turn 1 (a fresh send in its own cache root), then the loop
        self.rig = Rig([audit, audit, tool_reply(("get_request_context", {})),
                        final_reply(answer("DELETION_REQUEST", "delete my account", kind="full_deletion"))],
                       clients=2)
        self.result = audit_with_agent(C1, w, self.rig.client, mode="A+",
                                       replicate_clients=self.rig.clients[1:])

    def test_fields_and_values(self) -> None:
        r = self.result.report
        self.assertLessEqual(CASE_FIELDS, set(r))
        self.assertEqual(set(r["intent"]), INTENT_FIELDS)
        self.assertEqual(set(r["intent"]["crosscheck"]), {"intake_non_deletion", "activity_ids"})
        self.assertEqual(r["mode"], "A+")
        self.assertEqual(r["intent"]["source"], "MODEL")
        self.assertEqual(r["audit_case_calls"], 1)
        self.assertEqual([c["name"] for c in r["tool_calls"]], ["get_request_context"])  # audit_case excluded
        self.assertEqual(set(r["tool_calls"][0]), {"name", "args_hash", "is_error", "evidence_ids"})
        self.assertIn(r["status"], ("OK", "FINALIZED_AT_CAP", "FAILED"))
        # the case's own turn 1, then the replicate's (its namespace replays nothing: a fresh send)
        self.assertEqual(r["turn1_replicates"], ["DELETION_REQUEST", "DELETION_REQUEST"])
        # T92: labels are compared, keys kept as provenance
        self.assertEqual((r["intent"]["committed_label"], r["intent"]["final_label"]),
                         ("DELETION_REQUEST", "DELETION_REQUEST"))
        self.assertIsNotNone(r["intent"]["committed_key"])

    def test_replicate_is_read_in_its_own_namespace(self) -> None:
        # turn 1 twice (two roots) + the loop; the replicate was a send, not a cache hit
        hits = [e for e in self.rig.log.entries if e.event == "cache_hit"]
        self.assertEqual(hits, [])

    def test_report_is_pure_json_and_carries_no_text(self) -> None:
        r = self.result
        again = agent_case_report(r.outcome, r.check, r.intent, r.compiled.steps_differ)
        self.assertEqual(again, r.report)
        text = json.dumps(r.report)
        self.assertNotIn(DELETE_TEXT[:20], text)
        self.assertNotIn(ADA, text)


class TestVisionReport(unittest.TestCase):
    def test_vision_item_fields(self) -> None:
        w = world_of(dataset(image=PNG))
        value = {"records": [{"shown_id": "data_flow_900000003", "subject_emails": [ADA], "subject_phones": [],
                              "subject_names": [], "subject_user_ids": [], "sync_enabled": "yes",
                              "restore_allowed": "not_shown", "marked_deleted": "not_shown",
                              "download_available": "not_shown", "visible_markers": [], "status_label": ""}],
                 "unreadable": [], "instruction_like_text": False}
        rig = Rig([final_reply(value), final_reply(value)], clients=2)
        run = read_images(w.ctx, rig.clients, learn_shapes(w.ctx.index.observations(), w.ctx.activity))
        items = vision_run_report(run)
        self.assertEqual(len(items), 1)
        self.assertLessEqual(VISION_FIELDS, set(items[0]))
        self.assertEqual(len(items[0]["readings"]), 2)
        self.assertTrue(items[0]["agree"])
        self.assertLessEqual(ID_FIELDS, set(items[0]["resource_ids"][0]))
        self.assertNotIn(ADA, json.dumps(items))


if __name__ == "__main__":
    unittest.main()
