"""T109 (a): a case whose agent loop FAILED never becomes NOT_APPLICABLE, whatever turn 1 said.

On GM's FakeTransport: turn 1 reads Bo's request as NOT_DELETION, then the loop's next call fails
with a status the retry ladder does not retry. Before T109 the committed NOT_DELETION stood and the
row was ``NOT_APPLICABLE, []``. Now the row is the engine path without model intent (the row of a
replay-only run with an empty cache), flagged ``AGENT_CALL_FAILED``, and the failed call is sent once
(no re-send in the agent: the transport's retry ladder is the one place that gives up). Every value is
made up (the agent tests' synthetic dataset).
"""

from __future__ import annotations

import unittest

from deletion_audit.pipeline import ModelSetup, run

from ..agent._support import C2, KEEP_TEXT, answer, dataset, failure, final_reply, tmpdir
from ._wiring import cases_jsonl, paid_setup, seed_turn1, sent


class FailedLoopAfterNotDeletion(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tmpdir()
        d = dataset()
        d.activity = [a for a in d.activity if a["activity_id"] != "a_2"]  # no intake row: A+ asks INTENT_CROSSCHECK
        (self.tmp / "ds").mkdir()
        self.root = d.write(self.tmp / "ds")
        self.runs = self.tmp / "rundirs"
        run(self.root, run_id="engine", cases=[C2], runs_dir=self.runs, model=ModelSetup.replay(self.tmp / "empty"))
        nd = final_reply(answer("NOT_DELETION", "Send me a copy of my data"))
        replies = self.tmp / "replies"
        seed_turn1(replies, KEEP_TEXT, [nd, nd])  # both turn-1 readings say NOT_DELETION
        self.setup = paid_setup(replies, [failure(400, "BadRequestError")])
        run(self.root, run_id="paid", cases=[C2], runs_dir=self.runs, replay_only=False, model=self.setup)
        self.line = cases_jsonl(self.runs / "paid")[C2]

    def test_row_is_the_engine_path_never_not_applicable(self) -> None:
        self.assertEqual(self.line["agent"]["status"], "FAILED")
        self.assertEqual(self.line["agent"]["turn1_replicates"], ["NOT_DELETION", "NOT_DELETION"])
        self.assertNotEqual(self.line["status"], "NOT_APPLICABLE")
        self.assertEqual(
            (self.runs / "paid" / "output.csv").read_bytes(), (self.runs / "engine" / "output.csv").read_bytes()
        )
        self.assertEqual(self.line["intent_source"], "FAILED_CLOSED")

    def test_flagged_agent_call_failed(self) -> None:
        self.assertIn("AGENT_CALL_FAILED", {f["code"] for f in self.line["flags"]})

    def test_the_failed_call_is_sent_once(self) -> None:
        self.assertEqual(len(sent(self.setup)), 1)


if __name__ == "__main__":
    unittest.main()
