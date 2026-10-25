"""The model-on regression gate (T100, T101): causes by recompiling, the two allowed changes, and refusals.

Unit tests use synthetic rows; end-to-end tests run the wired pipeline on a made-up dataset whose
reply caches are seeded through GM's FakeTransport, against a baseline written by a replay-only run.
"""

from __future__ import annotations

import hashlib
import json
import random
import unittest
from pathlib import Path
from typing import Any

from deletion_audit.agent.regression import (
    Baseline,
    BaselineRefused,
    CaseEvidence,
    IdFacts,
    ImageFacts,
    Row,
    classify,
    load_baseline,
    run_gate,
    verdict,
)
from deletion_audit.pipeline import ModelSetup, RunSummary, run, run_vision

from ..agent._support import C1, C2, DELETE_TEXT, KEEP_TEXT, PNG, answer, dataset, final_reply, tmpdir
from ..engine_fixtures import case
from ._wiring import approve, paid_setup, read_json, reading, seed_turn1, shown

BASE = Row("INCOMPLETE", '[{"step_no":1}]')
NA = Row("NOT_APPLICABLE", "[]")
IMG = Row("INCOMPLETE", '[{"step_no":1},{"step_no":2}]')
BOTH = Row("COMPLETE", '[{"step_no":1,"x":1}]')
GOOD_IMAGE = ImageFacts("ev_img", True, True, (IdFacts("data_flow_9", "data_flow_9", "shape", True, True),))


def ev(after: Row, intent_only: Row, image_only: Row, both: Row, *, intent: bool = False,
       images: tuple[ImageFacts, ...] = (), labels: tuple[str | None, ...] = ("NOT_DELETION", "NOT_DELETION"),
       intake: bool = True, waiting: tuple[str, ...] = (), supplied: tuple[str, ...] = ()) -> CaseEvidence:
    return CaseEvidence("c", after, intent_only, image_only, both, intent, "NOT_DELETION" if intent else None,
                        "MODEL" if intent else "FAILED_CLOSED", labels, intake, images, waiting, supplied)


class TestClassify(unittest.TestCase):
    def test_changed_by_intent_only(self) -> None:
        e = ev(NA, NA, BASE, NA, intent=True)
        self.assertEqual(classify(e)[0], "intent")

    def test_changed_by_an_image_only(self) -> None:
        e = ev(IMG, BASE, IMG, IMG, images=(GOOD_IMAGE,))
        self.assertEqual(classify(e)[0], "image")

    def test_changed_only_by_both_together(self) -> None:
        e = ev(BOTH, NA, IMG, BOTH, intent=True, images=(GOOD_IMAGE,))
        self.assertEqual(classify(e)[0], "intent+image")
        self.assertEqual(verdict("intent+image", e)[0], "stop")

    def test_each_alone_reproducing_is_not_put_on_one_input(self) -> None:
        e = ev(IMG, IMG, IMG, IMG, intent=True, images=(GOOD_IMAGE,))
        self.assertEqual(classify(e)[0], "intent+image")

    def test_planted_change_with_no_cause_is_unexplained(self) -> None:
        cause, how = classify(ev(IMG, IMG, BASE, IMG))  # neither input changed, though a recompile reproduces it
        self.assertEqual(cause, "unexplained")
        self.assertTrue(how.startswith("neither input changed"), how)
        self.assertEqual(classify(ev(IMG, BASE, BASE, BASE, intent=True, images=(GOOD_IMAGE,)))[0], "unexplained")
        self.assertEqual(verdict("unexplained", ev(IMG, BASE, BASE, IMG))[0], "stop")

    def test_a_cause_whose_input_did_not_change_is_unexplained(self) -> None:
        self.assertEqual(classify(ev(NA, NA, BASE, NA, intent=False, images=(GOOD_IMAGE,)))[0], "unexplained")
        self.assertEqual(classify(ev(IMG, BASE, IMG, IMG, intent=True))[0], "unexplained")


class TestVerdict(unittest.TestCase):
    def test_intent_to_na_with_agreeing_replicates_and_crosscheck_is_allowed(self) -> None:
        self.assertEqual(verdict("intent", ev(NA, NA, BASE, NA, intent=True))[0], "allowed")

    def test_intent_stops_on_an_uncertain_replicate_a_disagreeing_crosscheck_or_one_reading(self) -> None:
        for labels, intake in ((("NOT_DELETION", "UNCERTAIN"), True), (("NOT_DELETION", None), True),
                               (("NOT_DELETION",), True), (("NOT_DELETION", "NOT_DELETION"), False)):
            got, why = verdict("intent", ev(NA, NA, BASE, NA, intent=True, labels=labels, intake=intake))
            self.assertEqual(got, "stop", (labels, intake))
            self.assertIn("intake_non_deletion", why)

    def test_intent_change_that_is_not_na_with_no_steps_stops(self) -> None:
        self.assertEqual(verdict("intent", ev(IMG, IMG, BASE, IMG, intent=True))[0], "stop")

    def test_image_with_agreeing_readings_and_confirmed_ids_is_allowed(self) -> None:
        e = ev(IMG, BASE, IMG, IMG, images=(GOOD_IMAGE,), waiting=("data_flow_9",), supplied=("data_flow_9",))
        self.assertEqual(verdict("image", e)[0], "allowed")

    def test_image_stops_on_disagreeing_or_failed_readings(self) -> None:
        for facts in (ImageFacts("ev_img", True, False, GOOD_IMAGE.ids), ImageFacts("ev_img", False, None)):
            got, why = verdict("image", ev(IMG, BASE, IMG, IMG, images=(facts,)))
            self.assertEqual(got, "stop")
            self.assertIn("ev_img", why)

    def test_image_stops_on_an_id_named_nowhere_else_or_malformed(self) -> None:
        for bad in (IdFacts("data_flow_7", "data_flow_7", "shape", True, False),
                    IdFacts("data_flow_x", None, "malformed", False, False)):
            facts = ImageFacts("ev_img", True, True, (*GOOD_IMAGE.ids, bad))
            got, why = verdict("image", ev(IMG, BASE, IMG, IMG, images=(facts,)))
            self.assertEqual(got, "stop", bad)
            self.assertIn("not:", why)

    def test_image_stops_when_a_waiting_record_got_no_image_state(self) -> None:
        e = ev(IMG, BASE, IMG, IMG, images=(GOOD_IMAGE,), waiting=("data_flow_9", "object_4"),
               supplied=("data_flow_9",))
        got, why = verdict("image", e)
        self.assertEqual(got, "stop")
        self.assertIn("object_4", why)


class TestGateProperties(unittest.TestCase):
    def test_random_evidence_never_allows_outside_the_two_changes(self) -> None:
        """Seeded property test (Hypothesis is not installed): ``allowed`` only for intent or image with
        their conditions; every unexplained and intent+image row stops; rows come out in case order."""
        rows = (BASE, NA, IMG, BOTH)
        for seed in range(300):
            rng = random.Random(seed)
            after = rng.choice(rows)
            e = ev(after, rng.choice(rows), rng.choice(rows), rng.choice((after, *rows)), intent=rng.random() < 0.5,
                   images=(GOOD_IMAGE,) if rng.random() < 0.5 else (),
                   labels=tuple(rng.choice(["NOT_DELETION", "UNCERTAIN", None]) for _ in range(rng.randrange(1, 3))),
                   intake=rng.random() < 0.5)
            cause, _ = classify(e)
            got, _ = verdict(cause, e)
            if got == "allowed":
                self.assertIn(cause, ("intent", "image"), seed)
            if cause == "intent" and got == "allowed":
                self.assertEqual((after, e.intake_non_deletion), (NA, True), seed)
                self.assertTrue(len(e.turn1_labels) >= 2 and set(e.turn1_labels) == {"NOT_DELETION"}, seed)
            if cause in ("unexplained", "intent+image"):
                self.assertEqual(got, "stop", seed)

    def test_gate_rows_in_numeric_case_order_and_only_changed_rows(self) -> None:
        ids = [C2, C1, case(9010)]
        baseline = Baseline("r", "p", "s", None, dict.fromkeys(ids, BASE))
        after = {ids[0]: NA, ids[1]: NA, ids[2]: BASE}
        result = run_gate(baseline, after, lambda cid: ev(NA, NA, BASE, NA, intent=True))
        self.assertEqual([r["case_id"] for r in result.changed], sorted(ids[:2], key=lambda c: int(c.split("_")[1])))
        self.assertTrue(result.passed)


class TestBaseline(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tmpdir()
        self.out = self.tmp / "output.csv"
        self.out.write_text('case_id,deletion_status,steps_json\nc_1,COMPLETE,[]\n', encoding="utf-8")

    def record(self, sha: str, path: str | None = None) -> Path:
        p = self.tmp / "approved.json"
        p.write_text(json.dumps({"approved_output": {"path": path or str(self.out), "sha256": sha, "run_id": "x"}}),
                     encoding="utf-8")
        return p

    def test_wrong_hash_is_refused(self) -> None:
        with self.assertRaises(BaselineRefused):
            load_baseline(self.record("0" * 64), self.tmp)
        result = run_gate(BaselineRefused("x"), {"c_1": NA}, lambda cid: ev(NA, NA, NA, NA))
        self.assertFalse(result.passed)
        self.assertEqual(result.changed, [])

    def test_path_is_read_from_the_record_relative_to_the_repo_root(self) -> None:
        sha = hashlib.sha256(self.out.read_bytes()).hexdigest()
        b = load_baseline(self.record(sha, "output.csv"), self.tmp)
        self.assertEqual((b.sha256, dict(b.rows)), (sha, {"c_1": Row("COMPLETE", "[]")}))

    def test_missing_file_or_unreadable_record_is_refused(self) -> None:
        with self.assertRaises(BaselineRefused):
            load_baseline(self.record("0" * 64, "nowhere.csv"), self.tmp)
        bad = self.tmp / "bad.json"
        bad.write_text("{}", encoding="utf-8")
        with self.assertRaises(BaselineRefused):
            load_baseline(bad, self.tmp)

    def test_case_set_mismatch_is_refused(self) -> None:
        sha = hashlib.sha256(self.out.read_bytes()).hexdigest()
        b = load_baseline(self.record(sha), self.tmp)
        result = run_gate(b, {"c_2": NA}, lambda cid: ev(NA, NA, NA, NA))
        self.assertIsNotNone(result.refusal)
        self.assertFalse(result.passed)


class TestEndToEnd(unittest.TestCase):
    """The gate inside ``pipeline.run``: baseline = a replay-only run with an empty cache."""

    def setUp(self) -> None:
        self.tmp = tmpdir()
        self.runs = self.tmp / "rundirs"
        self.replies = self.tmp / "replycache"

    def baseline(self, **kw: object) -> tuple[Path, Path]:
        d = dataset(**kw)  # type: ignore[arg-type]
        (self.tmp / "ds").mkdir(exist_ok=True)
        root = d.write(self.tmp / "ds")
        run(root, run_id="base", cases="test", runs_dir=self.runs, model=ModelSetup.replay(self.tmp / "emptycache"))
        return root, approve(self.runs / "base" / "output.csv")

    def gated(self, root: Path, record: Path, run_id: str = "gated") -> tuple[RunSummary, dict[str, Any]]:
        s = run(root, run_id=run_id, cases="test", runs_dir=self.runs, model=ModelSetup.replay(self.replies),
                regression_gate=True, approved_record=record)
        return s, read_json(self.runs / run_id / "regression_vs_engine.json")

    def nd(self) -> dict[str, Any]:
        return final_reply(answer("NOT_DELETION", "Send me a copy of my data"))

    def test_intent_change_allowed_when_both_replicates_and_the_crosscheck_agree(self) -> None:
        root, record = self.baseline()
        seed_turn1(self.replies, KEEP_TEXT, [self.nd(), self.nd()])
        s, gate = self.gated(root, record)
        self.assertEqual([(r["case_id"], r["cause"], r["verdict"]) for r in gate["rows"]], [(C2, "intent", "allowed")])
        row = gate["rows"][0]
        self.assertEqual((row["before"]["status"], row["after"]["status"], row["after"]["n_steps"]),
                         ("INCOMPLETE", "NOT_APPLICABLE", 0))
        self.assertTrue(gate["passed"])
        self.assertTrue(s.passed)
        self.assertTrue((self.runs / "gated" / "regression_vs_engine.md").is_file())

    def test_intent_change_stops_when_a_replicate_is_uncertain(self) -> None:
        root, record = self.baseline()
        unsure = final_reply(answer("UNCERTAIN", ""))
        seed_turn1(self.replies, KEEP_TEXT, [self.nd(), unsure])
        s, gate = self.gated(root, record)
        self.assertEqual([(r["cause"], r["verdict"]) for r in gate["rows"]], [("intent", "stop")])
        self.assertFalse(s.passed)
        producer = read_json(self.runs / "gated" / "producer.json")
        self.assertFalse(producer["run_passed"])
        self.assertIn("1 changed row(s) marked stop", producer["refusal"])

    def test_intent_change_stops_when_the_crosscheck_disagrees(self) -> None:
        d = dataset()
        d.activity = [a for a in d.activity if a["activity_id"] != "a_2"]  # Bo has no non-deletion intake row
        (self.tmp / "ds").mkdir(exist_ok=True)
        root = d.write(self.tmp / "ds")
        run(root, run_id="base", cases="test", runs_dir=self.runs, model=ModelSetup.replay(self.tmp / "emptycache"))
        record = approve(self.runs / "base" / "output.csv")
        seed_turn1(self.replies, KEEP_TEXT, [self.nd(), self.nd()])
        # A+ poses INTENT_CROSSCHECK; its extra turn is a replay miss, so the committed label stands (G7a loop)
        s, gate = self.gated(root, record)
        rows = [(r["case_id"], r["cause"], r["verdict"], r["intake_non_deletion"]) for r in gate["rows"]]
        self.assertEqual(rows, [(C2, "intent", "stop", False)])
        self.assertIn("intake_non_deletion: False", gate["rows"][0]["condition"])
        self.assertFalse(s.passed)

    def vision(self, root: Path, r1: dict[str, Any], r2: dict[str, Any]) -> None:
        run_vision(root, run_id="vis", model=paid_setup(self.replies, [final_reply(r1), final_reply(r2)]),
                   runs_dir=self.runs)

    def both_records(self, sync: str = "yes") -> dict[str, Any]:
        return reading([shown("data_flow_900000003", sync_enabled=sync),
                        shown("object_900000004", download_available="yes")])

    def test_image_change_allowed_with_agreeing_readings_and_confirmed_ids(self) -> None:
        root, record = self.baseline(image=PNG)
        self.vision(root, self.both_records(), self.both_records())
        _, gate = self.gated(root, record)
        self.assertEqual([(r["case_id"], r["cause"], r["verdict"]) for r in gate["rows"]], [(C1, "image", "allowed")])
        self.assertEqual(gate["rows"][0]["image_file_ids"], ["ev_img"])

    def test_image_change_stops_on_disagreeing_readings(self) -> None:
        root, record = self.baseline(image=PNG)
        self.vision(root, self.both_records("yes"), self.both_records("no"))
        _, gate = self.gated(root, record)
        self.assertEqual([(r["cause"], r["verdict"]) for r in gate["rows"]], [("image", "stop")])
        self.assertIn("read OK with agreeing readings: False", gate["rows"][0]["condition"])

    def test_image_change_stops_on_an_id_no_other_input_names(self) -> None:
        root, record = self.baseline(image=PNG)
        value = reading([*self.both_records()["records"], shown("data_flow_900000777", sync_enabled="yes")])
        self.vision(root, value, value)
        _, gate = self.gated(root, record)
        self.assertEqual([(r["cause"], r["verdict"]) for r in gate["rows"]], [("image", "stop")])
        self.assertIn("data_flow_900000777", gate["rows"][0]["condition"])

    def test_image_change_stops_when_a_waiting_record_got_no_state(self) -> None:
        root, record = self.baseline(image=PNG)
        value = reading([shown("data_flow_900000003", sync_enabled="yes")])  # object_900000004 not shown
        self.vision(root, value, value)
        _, gate = self.gated(root, record)
        self.assertEqual([(r["cause"], r["verdict"]) for r in gate["rows"]], [("image", "stop")])
        self.assertIn("object_900000004", gate["rows"][0]["condition"])

    def test_planted_baseline_change_with_no_cause_stops(self) -> None:
        root, _ = self.baseline()
        record = approve(self.runs / "base" / "output.csv", plant=(C1, "COMPLETE"))
        s, gate = self.gated(root, record)
        self.assertEqual([(r["case_id"], r["cause"], r["verdict"]) for r in gate["rows"]],
                         [(C1, "unexplained", "stop")])
        self.assertFalse(s.passed)

    def test_baseline_with_the_wrong_hash_is_refused(self) -> None:
        root, record = self.baseline()
        body = json.loads(record.read_text(encoding="utf-8"))
        body["approved_output"]["sha256"] = "0" * 64
        record.write_text(json.dumps(body), encoding="utf-8")
        s, gate = self.gated(root, record)
        self.assertFalse(gate["passed"])
        self.assertIn("refused", gate["refusal"])
        producer = read_json(self.runs / "gated" / "producer.json")
        self.assertFalse(producer["run_passed"])
        self.assertTrue(producer["refusal"].startswith("regression gate:"))
        self.assertFalse(s.passed)

    def test_unchanged_run_passes(self) -> None:
        root, record = self.baseline(image=PNG)
        s, gate = self.gated(root, record)
        self.assertEqual((gate["changed_rows"], gate["passed"]), (0, True))
        self.assertTrue(s.passed)
        self.assertNotIn(DELETE_TEXT[:20], json.dumps(gate))


if __name__ == "__main__":
    unittest.main()
