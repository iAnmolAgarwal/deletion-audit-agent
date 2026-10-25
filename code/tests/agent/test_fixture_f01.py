"""Wiring check on the committed G5b fixture F01 (negation traps; made-up people), on the fake transport.

The replies are scripted, so this tests the harness, not the model's judgement: a validated
NOT_DELETION gives NOT_APPLICABLE with ``[]`` even though every person has live records; the
intake row is compared, flagged on disagreement, and never overrides (T63, T71 Q10). The model's
own reading of F01 is measured in the paid turn-1 routing check, not here.
"""

from __future__ import annotations

import unittest

from deletion_audit.agent import audit_with_agent

from ._support import Rig, answer, final_reply, fixture_world

F01 = "F01_non_deletion_negation_traps"


class TestF01(unittest.TestCase):
    def test_not_deletion_gives_not_applicable_and_the_intake_row_only_flags(self) -> None:
        w = fixture_world(F01)
        cases = sorted(r.case_id for r in w.ctx.requests if r.source == "test")
        self.assertEqual(len(cases), 3)
        agrees = []
        for cid in cases:
            text = next(r.request_text for r in w.ctx.requests if r.case_id == cid)
            rig = Rig([final_reply(answer("NOT_DELETION", text[:24]))])
            result = audit_with_agent(cid, w, rig.client, mode="tools_off")
            self.assertEqual((result.applied.status, result.applied.steps), ("NOT_APPLICABLE", ()), cid)
            agrees.append(result.intent.agrees)
        self.assertEqual(sorted(agrees), [False, False, True])  # one person has the intake row

    def test_deletion_misread_is_not_overridden_but_flagged(self) -> None:
        w = fixture_world(F01)
        flagged = []
        for cid in sorted(r.case_id for r in w.ctx.requests if r.source == "test"):
            text = next(r.request_text for r in w.ctx.requests if r.case_id == cid)
            rig = Rig([final_reply(answer("DELETION_REQUEST", text[:24], kind="full_deletion"))])
            result = audit_with_agent(cid, w, rig.client, mode="tools_off")
            self.assertEqual(result.intent.label, "DELETION_REQUEST")
            self.assertEqual(result.applied.status, "INCOMPLETE")
            flagged.append("INTENT_CROSSCHECK_DISAGREES" in result.report["flags"])
        self.assertEqual(sorted(flagged), [False, False, True])


if __name__ == "__main__":
    unittest.main()
