"""freeze_check: refuses on each of its four counts separately, passes only when all are 0."""
from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from evaluation import freeze_check as fc_mod
from evaluation.freeze_check import COUNTS, freeze_check

from .run_dirs import ABSENT, agent, case, image, intent, step, write_run

IDS = ["case_901", "case_902", "case_903"]
AGREE = image("evidence_04", {"state": "DELETED"}, {"state": "DELETED"}, True, [])
DISAGREE = image("evidence_09", {"state": "ACTIVE"}, {"state": "DELETED"}, False, ["state"])


def rows() -> dict[str, tuple[str, list[dict[str, Any]]]]:
    return {c: ("COMPLETE", [step("account_" + c[5:])]) for c in IDS}


class TestFreezeCheck(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.runs = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def check(self, cases: list[dict[str, Any]] | None = None, **kw: Any) -> dict[str, Any]:
        write_run(self.runs, "r1", rows(), cases or [case(c) for c in IDS], vision=kw.pop("vision", [AGREE]), **kw)
        return freeze_check("r1", runs_root=self.runs)

    def failing(self, res: dict[str, Any]) -> list[str]:
        return [r.split(" ")[0].rstrip(":") for r in res["refusals"]]

    def test_passes_when_all_zero(self) -> None:
        res = self.check()
        self.assertTrue(res["passed"], res["refusals"])
        self.assertEqual(res["counts"], {k: 0 for k in COUNTS})

    def test_refuses_on_failed_closed_row_only(self) -> None:
        cases = [case(c) for c in IDS]
        cases[1] = case("case_902", row_state="FAILED_CLOSED", failed_closed="NOTHING_FOUND")
        res = self.check(cases)
        self.assertFalse(res["passed"])
        self.assertEqual(self.failing(res), ["failed_closed_rows"])
        self.assertEqual(res["counts"]["failed_closed_rows"], 1)
        self.assertEqual(res["ids"]["failed_closed_rows"], ["case_902"])

    def test_refuses_on_intent_failed_closed_flag_only(self) -> None:
        cases = [case(c) for c in IDS]
        cases[2] = case("case_903", flags=["INTENT_FAILED_CLOSED"])
        res = self.check(cases)
        self.assertEqual(self.failing(res), ["intent_failed_closed"])
        self.assertEqual(res["counts"]["intent_failed_closed"], 1)

    def test_intent_failed_budget_source_counts(self) -> None:
        cases = [case(c) for c in IDS]
        cases[0] = case("case_901", agent(intent=intent(None, "FAILED_BUDGET", agrees=None)))
        res = self.check(cases)
        self.assertEqual(self.failing(res), ["intent_failed_closed"])
        self.assertEqual(res["ids"]["intent_failed_closed"], ["case_901"])

    def test_refuses_on_evidence_skip_only(self) -> None:
        res = self.check(skips=["evidence_04:png-model-needed"])
        self.assertEqual(res["producer_check"], "ok")  # the allow-list passes the score check...
        self.assertEqual(self.failing(res), ["evidence_skips"])  # ...but not the freeze check
        self.assertEqual(res["counts"]["evidence_skips"], 1)

    def test_refuses_on_vision_disagreement_only(self) -> None:
        res = self.check(vision=[AGREE, DISAGREE])
        self.assertEqual(self.failing(res), ["vision_unresolved_disagreements"])
        self.assertEqual(res["ids"]["vision_unresolved_disagreements"], ["evidence_09"])

    def test_refuses_unchecked_run(self) -> None:
        res = self.check(bad_hash=True)
        self.assertFalse(res["passed"])
        self.assertEqual(res["producer_check"], "output-mismatch")
        self.assertTrue(any(r.startswith("error: producer check output-mismatch") for r in res["refusals"]))

    def test_refuses_missing_agent_field(self) -> None:
        cases = [case(c) for c in IDS]
        cases[0] = case("case_901", ABSENT)
        res = self.check(cases)
        self.assertFalse(res["passed"])
        self.assertIsNone(res["counts"]["intent_failed_closed"])
        self.assertIn("intent_failed_closed: not computed (see errors)", res["refusals"])

    def test_refuses_missing_vision_artifact(self) -> None:
        res = self.check(vision=ABSENT)
        self.assertIsNone(res["counts"]["vision_unresolved_disagreements"])
        self.assertFalse(res["passed"])

    def test_metrics_count_disagreement_is_error(self) -> None:
        res = self.check(fc_count=2)
        self.assertFalse(res["passed"])
        self.assertTrue(any("failed_closed.count disagrees" in r for r in res["refusals"]))

    def test_cli_exit_status_names_counts(self) -> None:
        write_run(self.runs, "r1", rows(), [case(c) for c in IDS], vision=[AGREE, DISAGREE])
        out = io.StringIO()
        with mock.patch.object(fc_mod, "RUNS", self.runs), contextlib.redirect_stdout(out):
            status = fc_mod.main(["--run-id", "r1"])
        self.assertEqual(status, 1)
        self.assertIn("vision_unresolved_disagreements = 1", out.getvalue())
        write_run(self.runs, "r2", rows(), [case(c) for c in IDS], vision=[AGREE])
        with mock.patch.object(fc_mod, "RUNS", self.runs), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(fc_mod.main(["--run-id", "r2"]), 0)

    def test_bad_run_id_refused(self) -> None:
        with self.assertRaises(ValueError):
            freeze_check("bad id", runs_root=self.runs)


if __name__ == "__main__":
    unittest.main()
