"""Model-derived changes (T100, T101, T118, T119): causes by recompiling, the two allowed changes,
fallback to the engine's model-free row computed in the same run, and stops.

Unit tests use synthetic rows; end-to-end tests run the wired pipeline on a made-up dataset whose
reply caches are seeded through GM's FakeTransport. The model-free rows are computed inside the run;
a replay-only run with an empty cache writes exactly those rows, so it serves as the reference.
(The file keeps its old name: the improvement ledger cites one of its tests by path.)
"""

from __future__ import annotations

import random
import unittest
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest import mock

from deletion_audit import pipeline
from deletion_audit.agent.model_changes import (
    CaseEvidence,
    Derivation,
    IdFacts,
    ImageFacts,
    RecordView,
    Row,
    SingleReadingCheck,
    classify,
    judge_changes,
    judge_single_readings,
    verdict,
)
from deletion_audit.pipeline import ModelSetup, RunSummary, run, run_vision

from ..agent._support import C1, C2, DELETE_TEXT, KEEP_TEXT, PNG, answer, dataset, final_reply, tmpdir
from ..engine_fixtures import case
from ._wiring import cases_jsonl, paid_setup, read_json, reading, seed_turn1, shown

BASE = Row("INCOMPLETE", '[{"step_no":1}]')
NA = Row("NOT_APPLICABLE", "[]")
IMG = Row("INCOMPLETE", '[{"step_no":1},{"step_no":2}]')
BOTH = Row("COMPLETE", '[{"step_no":1,"x":1}]')
GOOD_IMAGE = ImageFacts("ev_img", True, True, (IdFacts("data_flow_9", "data_flow_9", "shape", True, True),))


def ev(after: Row, intent_only: Row, image_only: Row, both: Row, *, intent: bool = False,
       images: tuple[ImageFacts, ...] = (), labels: tuple[str | None, ...] = ("NOT_DELETION", "NOT_DELETION"),
       intake: bool = True, waiting: tuple[str, ...] = (), supplied: tuple[str, ...] = (),
       loop: str | None = "OK") -> CaseEvidence:
    return CaseEvidence("c", after, intent_only, image_only, both, intent, "NOT_DELETION" if intent else None,
                        "MODEL" if intent else "FAILED_CLOSED", labels, intake, images, waiting, supplied, loop)


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
        self.assertEqual(verdict("intent+image", e)[0], "fell_back")  # T118: never allowed, never a stop

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
    def test_intent_change_kept_approved_when_the_agent_loop_failed(self) -> None:
        """T109 (b): a FAILED loop (or an unknown loop status) never allows an intent change, even with
        two agreeing NOT_DELETION turn-1 readings and an agreeing intake cross-check (T118: kept as approved)."""
        for loop in ("FAILED", None):
            got, why = verdict("intent", ev(NA, NA, BASE, NA, intent=True, loop=loop))
            self.assertEqual(got, "fell_back", loop)
            self.assertIn(f"agent loop status {loop} is not FAILED: False", why)
        self.assertEqual(verdict("intent", ev(NA, NA, BASE, NA, intent=True, loop="FINALIZED_AT_CAP"))[0], "allowed")

    def test_intent_to_na_with_agreeing_replicates_and_crosscheck_is_allowed(self) -> None:
        self.assertEqual(verdict("intent", ev(NA, NA, BASE, NA, intent=True))[0], "allowed")

    def test_intent_kept_approved_on_an_uncertain_replicate_a_disagreeing_crosscheck_or_one_reading(self) -> None:
        """T118 (2c): an intent change failing T101 condition (1), e.g. no agreeing intake row, stays as approved."""
        for labels, intake in ((("NOT_DELETION", "UNCERTAIN"), True), (("NOT_DELETION", None), True),
                               (("NOT_DELETION",), True), (("NOT_DELETION", "NOT_DELETION"), False)):
            got, why = verdict("intent", ev(NA, NA, BASE, NA, intent=True, labels=labels, intake=intake))
            self.assertEqual(got, "fell_back", (labels, intake))
            self.assertIn("intake_non_deletion", why)

    def test_intent_change_that_is_not_na_with_no_steps_is_kept_approved(self) -> None:
        self.assertEqual(verdict("intent", ev(IMG, IMG, BASE, IMG, intent=True))[0], "fell_back")

    def test_image_with_agreeing_readings_and_confirmed_ids_is_allowed(self) -> None:
        e = ev(IMG, BASE, IMG, IMG, images=(GOOD_IMAGE,), waiting=("data_flow_9",), supplied=("data_flow_9",))
        self.assertEqual(verdict("image", e)[0], "allowed")

    def test_image_kept_approved_on_disagreeing_or_failed_readings(self) -> None:
        for facts in (ImageFacts("ev_img", True, False, GOOD_IMAGE.ids), ImageFacts("ev_img", False, None)):
            got, why = verdict("image", ev(IMG, BASE, IMG, IMG, images=(facts,)))
            self.assertEqual(got, "fell_back")
            self.assertIn("ev_img", why)

    def test_image_kept_approved_on_an_id_named_nowhere_else_or_malformed(self) -> None:
        for bad in (IdFacts("data_flow_7", "data_flow_7", "shape", True, False),
                    IdFacts("data_flow_x", None, "malformed", False, False)):
            facts = ImageFacts("ev_img", True, True, (*GOOD_IMAGE.ids, bad))
            got, why = verdict("image", ev(IMG, BASE, IMG, IMG, images=(facts,)))
            self.assertEqual(got, "fell_back", bad)
            self.assertIn("not:", why)

    def test_image_kept_approved_when_a_waiting_record_got_no_image_state(self) -> None:
        e = ev(IMG, BASE, IMG, IMG, images=(GOOD_IMAGE,), waiting=("data_flow_9", "object_4"),
               supplied=("data_flow_9",))
        got, why = verdict("image", e)
        self.assertEqual(got, "fell_back")
        self.assertIn("object_4", why)


class TestGateProperties(unittest.TestCase):
    def test_random_evidence_never_allows_outside_the_two_changes(self) -> None:
        """Seeded property test (Hypothesis is not installed): ``allowed`` only for intent or image with
        their conditions; ``stop`` exactly for unexplained rows; every other explained row is kept as
        approved (T118)."""
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
            self.assertEqual(got == "stop", cause == "unexplained", seed)
            if cause == "intent+image":
                self.assertEqual(got, "fell_back", seed)

    def test_gate_rows_in_numeric_case_order_and_only_changed_rows(self) -> None:
        ids = [C2, C1, case(9010)]
        model_free = dict.fromkeys(ids, BASE)
        after = {ids[0]: NA, ids[1]: NA, ids[2]: BASE}
        result = judge_changes(model_free, after, lambda cid: ev(NA, NA, BASE, NA, intent=True))
        self.assertEqual([r["case_id"] for r in result.changed], sorted(ids[:2], key=lambda c: int(c.split("_")[1])))
        self.assertTrue(result.passed)


def _deriv(state: str | None, cited: tuple[str, ...] = ("ev_1",), fc: str | None = None) -> Derivation:
    return Derivation(fc, (RecordView("sys", "res_1", state, cited),))


class TestRuleA(unittest.TestCase):
    """T118 (2a): a disagreeing image is accepted only if each reading alone derives the same per record."""

    def test_same_derivation_under_each_reading_and_the_merge_is_accepted(self) -> None:
        d = _deriv("PRESENT")
        [c] = judge_single_readings(["ev_img"], {(0,): d, (1,): d}, d)
        self.assertTrue(c.accepted, c.reason)

    def test_a_different_state_or_cited_id_or_row_class_is_not_accepted(self) -> None:
        for other in (_deriv("ABSENT"), _deriv("PRESENT", ("ev_2",)), _deriv("PRESENT", fc="NOTHING_FOUND")):
            [c] = judge_single_readings(["ev_img"], {(0,): _deriv("PRESENT"), (1,): other}, _deriv("PRESENT"))
            self.assertFalse(c.accepted, other)
            self.assertIn("different", c.reason)

    def test_merged_reading_deriving_differently_is_not_accepted(self) -> None:
        d = _deriv("PRESENT")
        [c] = judge_single_readings(["ev_img"], {(0,): d, (1,): d}, _deriv("ABSENT"))
        self.assertFalse(c.accepted)
        self.assertIn("merged", c.reason)

    def test_a_missing_combination_is_a_failure_not_agreement(self) -> None:
        d = _deriv("PRESENT")
        [c] = judge_single_readings(["ev_img"], {(0,): d}, d)
        self.assertFalse(c.accepted)
        self.assertEqual(judge_single_readings([], {}, d), ())

    def test_two_images_judged_per_image(self) -> None:
        a, b = _deriv("PRESENT"), _deriv("ABSENT")
        # image 1's reading changes the derivation, image 2's does not
        got = judge_single_readings(["ev_a", "ev_b"], {(0, 0): a, (0, 1): a, (1, 0): b, (1, 1): b}, a)
        self.assertEqual([(c.file_id, c.accepted) for c in got], [("ev_a", False), ("ev_b", False)])
        self.assertIn("different", got[0].reason)
        self.assertIn("merged", got[1].reason)
        same = judge_single_readings(["ev_a", "ev_b"], dict.fromkeys([(0, 0), (0, 1), (1, 0), (1, 1)], a), a)
        self.assertTrue(all(c.accepted for c in same))

    def test_accepted_disagreeing_image_satisfies_the_image_condition_only_when_accepted(self) -> None:
        ok = SingleReadingCheck("ev_img", True, "same")
        bad = SingleReadingCheck("ev_img", False, "different")
        for single, want in ((ok, "allowed"), (bad, "fell_back"), (None, "fell_back")):
            facts = ImageFacts("ev_img", True, False, GOOD_IMAGE.ids, single)
            e = ev(IMG, BASE, IMG, IMG, images=(facts,), waiting=("data_flow_9",), supplied=("data_flow_9",))
            self.assertEqual(verdict("image", e)[0], want, single)
        failed = ImageFacts("ev_img", False, None, (), ok)  # a failed read is never rescued by rule (a)
        self.assertEqual(verdict("image", ev(IMG, BASE, IMG, IMG, images=(failed,)))[0], "fell_back")


class TestAssembly(unittest.TestCase):
    """T118: rows that fall back are the model-free rows byte for byte; only unexplained rows stop."""

    def test_fallback_rows_are_replaced_and_the_check_passes(self) -> None:
        ids = [C1, C2, case(9010)]
        before = {C1: BASE, C2: BASE, ids[2]: BASE}
        after = {C1: NA, C2: IMG, ids[2]: BASE}
        evs = {C1: ev(NA, NA, BASE, NA, intent=True, intake=False),  # intent, condition fails
               C2: ev(IMG, BASE, IMG, IMG, images=(ImageFacts("ev_img", True, False),))}  # image, disagreeing
        result = judge_changes(before, after, evs.__getitem__)
        self.assertTrue(result.passed)
        self.assertEqual(result.assembled, before)
        self.assertEqual([r["case_id"] for r in result.fell_back],
                         sorted([C1, C2], key=lambda c: int(c.split("_")[1])))
        self.assertTrue(all(r["fell_back"] for r in result.changed))
        self.assertEqual(result.as_json()["fell_back_cases"], [r["case_id"] for r in result.fell_back])

    def test_allowed_rows_stay_and_unexplained_rows_stop(self) -> None:
        evs = {C1: ev(NA, NA, BASE, NA, intent=True), C2: ev(IMG, IMG, BASE, IMG)}
        result = judge_changes({C1: BASE, C2: BASE}, {C1: NA, C2: IMG}, evs.__getitem__)
        self.assertEqual(result.assembled, {C1: NA, C2: IMG})
        self.assertEqual([r["case_id"] for r in result.stops], [C2])
        self.assertEqual(result.as_json()["stop_cases"], [C2])
        self.assertFalse(result.passed)

    def test_a_different_case_set_is_a_bug_not_a_comparison(self) -> None:
        """Both row sets come from the same run, so a mismatch raises instead of judging anything."""
        with self.assertRaises(ValueError):
            judge_changes({C1: BASE}, {C2: BASE}, lambda c: ev(NA, NA, NA, NA))

    def test_unchanged_rows_are_never_judged(self) -> None:
        def boom(cid: str) -> CaseEvidence:
            raise AssertionError(f"evidence asked for unchanged {cid}")
        result = judge_changes({C1: BASE, C2: NA}, {C1: BASE, C2: NA}, boom)
        self.assertEqual((result.changed, result.passed, result.assembled), ([], True, {C1: BASE, C2: NA}))

    def test_random_checks_assemble_only_model_free_or_computed_rows(self) -> None:
        """Seeded property test: every assembled row is the model-free row (fell back) or the computed
        one (unchanged, allowed or stop), and the check passes exactly when no unexplained row exists."""
        rows = (BASE, NA, IMG, BOTH)
        for seed in range(200):
            rng = random.Random(seed)
            ids = [case(9000 + i) for i in range(6)]
            before = {c: rng.choice(rows) for c in ids}
            after = {c: rng.choice(rows) for c in ids}
            evs = {c: ev(after[c], rng.choice(rows), rng.choice(rows), rng.choice(rows), intent=rng.random() < 0.5,
                         images=(GOOD_IMAGE,) if rng.random() < 0.5 else ()) for c in ids}
            result = judge_changes(before, after, evs.__getitem__)
            by = {r["case_id"]: r for r in result.changed}
            for c in ids:
                want = before[c] if by.get(c, {}).get("verdict") == "fell_back" else after[c]
                self.assertEqual(result.assembled[c], want, seed)
            self.assertEqual(set(by), {c for c in ids if before[c] != after[c]}, seed)
            self.assertEqual(result.passed, not any(r["cause"] == "unexplained" for r in result.changed), seed)


class TestEndToEnd(unittest.TestCase):
    """The check inside ``pipeline.run``; the reference is a replay-only run with an empty cache, which
    writes the model-free rows."""

    def setUp(self) -> None:
        self.tmp = tmpdir()
        self.runs = self.tmp / "rundirs"
        self.replies = self.tmp / "replycache"

    def baseline(self, **kw: object) -> tuple[Path, None]:
        d = dataset(**kw)  # type: ignore[arg-type]
        (self.tmp / "ds").mkdir(exist_ok=True)
        root = d.write(self.tmp / "ds")
        run(root, run_id="base", cases="test", runs_dir=self.runs, model=ModelSetup.replay(self.tmp / "emptycache"))
        return root, None

    def gated(self, root: Path, _unused: None = None, run_id: str = "gated") -> tuple[RunSummary, dict[str, Any]]:
        s = run(root, run_id=run_id, cases="test", runs_dir=self.runs, model=ModelSetup.replay(self.replies))
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

    def test_intent_change_falls_back_when_a_replicate_is_uncertain(self) -> None:
        """T118 (2c): the intent change fails T101 condition (1), so the model-free row is kept and the run passes."""
        root, record = self.baseline()
        unsure = final_reply(answer("UNCERTAIN", ""))
        seed_turn1(self.replies, KEEP_TEXT, [self.nd(), unsure])
        s, gate = self.gated(root, record)
        self.assertEqual([(r["cause"], r["verdict"]) for r in gate["rows"]], [("intent", "fell_back")])
        self.assertTrue(s.passed)
        producer = read_json(self.runs / "gated" / "producer.json")
        self.assertTrue(producer["run_passed"])
        self.assertEqual(producer["fell_back_cases"], [C2])
        self.assertEqual((self.runs / "gated" / "output.csv").read_bytes(),
                         (self.runs / "base" / "output.csv").read_bytes())
        raw = (self.runs / "gated" / "output_raw.csv").read_text(encoding="utf-8")
        self.assertIn(f"{C2},NOT_APPLICABLE,[]", raw)

    def test_crosscheck_disagreement_with_a_failed_extra_turn_keeps_the_engine_row(self) -> None:
        """A+ poses INTENT_CROSSCHECK; its extra turn is a replay miss, so the loop FAILED. Before T109 the
        committed NOT_DELETION stood and the row became NOT_APPLICABLE (the gate then stopped it); now
        the row is the engine path without model intent, flagged AGENT_CALL_FAILED, so nothing changed."""
        d = dataset()
        d.activity = [a for a in d.activity if a["activity_id"] != "a_2"]  # Bo has no non-deletion intake row
        (self.tmp / "ds").mkdir(exist_ok=True)
        root = d.write(self.tmp / "ds")
        run(root, run_id="base", cases="test", runs_dir=self.runs, model=ModelSetup.replay(self.tmp / "emptycache"))
        seed_turn1(self.replies, KEEP_TEXT, [self.nd(), self.nd()])
        s, gate = self.gated(root)
        self.assertEqual(gate["rows"], [])
        self.assertTrue(s.passed)
        self.assertEqual((self.runs / "gated" / "output.csv").read_bytes(),
                         (self.runs / "base" / "output.csv").read_bytes())
        bo = cases_jsonl(self.runs / "gated")[C2]
        self.assertEqual(bo["agent"]["status"], "FAILED")
        self.assertNotEqual(bo["status"], "NOT_APPLICABLE")
        self.assertIn("AGENT_CALL_FAILED", {f["code"] for f in bo["flags"]})

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

    def test_image_change_falls_back_on_readings_that_derive_differently(self) -> None:
        """T118 (2a): the readings disagree on a state the engine uses, so the row is the model-free row,
        byte for byte; the computed row goes to output_raw.csv; the run passes; cases.jsonl agrees."""
        root, record = self.baseline(image=PNG)
        self.vision(root, self.both_records("yes"), self.both_records("no"))
        s, gate = self.gated(root, record)
        self.assertEqual([(r["cause"], r["verdict"]) for r in gate["rows"]], [("image", "fell_back")])
        row = gate["rows"][0]
        self.assertIn("read OK with agreeing readings: False", row["condition"])
        [check] = row["single_reading_checks"]
        self.assertEqual((check["file_id"], check["accepted"]), ("ev_img", False))
        self.assertEqual(len(check["by_readings"]), 2)
        self.assertNotEqual(check["by_readings"][0]["records"], check["by_readings"][1]["records"])
        self.assertTrue(s.passed)
        self.assertEqual(gate["fell_back_cases"], [C1])
        d = self.runs / "gated"
        self.assertEqual((d / "output.csv").read_bytes(), (self.runs / "base" / "output.csv").read_bytes())
        self.assertNotEqual((d / "output_raw.csv").read_bytes(), (d / "output.csv").read_bytes())
        producer = read_json(d / "producer.json")
        self.assertEqual((producer["fell_back_cases"], producer["run_passed"]), ([C1], True))
        line = cases_jsonl(d)[C1]
        self.assertIn("MODEL_CHANGE_FELL_BACK", {f["code"] for f in line["flags"]})
        base_line = cases_jsonl(self.runs / "base")[C1]
        self.assertEqual(line["status"], base_line["status"])

    def test_kept_record_carries_the_case_s_own_validated_intent(self) -> None:
        """T118 step 4 fix: a fallen-back image row whose model intent was validated (DELETION_REQUEST) is
        shown in cases.jsonl with that intent, recompiled without the image readings, not as fail-closed;
        the output row is the model-free row byte for byte."""
        root, record = self.baseline(image=PNG)
        self.vision(root, self.both_records("yes"), self.both_records("no"))
        dr = final_reply(answer("DELETION_REQUEST", "delete my account", kind="full_deletion"))
        seed_turn1(self.replies, DELETE_TEXT, [dr, dr])
        s = run(root, run_id="gated", cases="test", runs_dir=self.runs, model=ModelSetup.replay(self.replies),
                mode="tools_off")  # turn 1 only: the loop is OK
        gate = read_json(self.runs / "gated" / "regression_vs_engine.json")
        self.assertEqual([(r["case_id"], r["verdict"]) for r in gate["rows"]], [(C1, "fell_back")])
        self.assertTrue(s.passed)
        d = self.runs / "gated"
        self.assertEqual((d / "output.csv").read_bytes(), (self.runs / "base" / "output.csv").read_bytes())
        line = cases_jsonl(d)[C1]
        self.assertEqual((line["intent_source"], line["agent"]["intent"]["source"]), ("MODEL", "MODEL"))
        kept = [f["detail"] for f in line["flags"] if f["code"] == "MODEL_CHANGE_FELL_BACK"]
        self.assertEqual(len(kept), 1)
        self.assertIn("own intent", kept[0])

    def test_disagreement_only_in_a_review_field_is_accepted_by_rule_a(self) -> None:
        """T118 (2a): the readings differ only in ``status_label`` (review only), so each reading alone
        derives the same state and cited IDs for every record: the image counts as agreeing."""
        root, record = self.baseline(image=PNG)
        r1 = reading([shown("data_flow_900000003", sync_enabled="yes", status_label="Active"),
                      shown("object_900000004", download_available="yes")])
        r2 = reading([shown("data_flow_900000003", sync_enabled="yes", status_label="Syncing"),
                      shown("object_900000004", download_available="yes")])
        self.vision(root, r1, r2)
        s, gate = self.gated(root, record)
        self.assertEqual([(r["case_id"], r["cause"], r["verdict"]) for r in gate["rows"]], [(C1, "image", "allowed")])
        [check] = gate["rows"][0]["single_reading_checks"]
        self.assertTrue(check["accepted"], check)
        self.assertIn("accepted by T118 rule (a)", gate["rows"][0]["condition"])
        self.assertTrue(s.passed)
        self.assertEqual(gate["fell_back_cases"], [])

    def test_image_change_falls_back_on_an_id_no_other_input_names(self) -> None:
        root, record = self.baseline(image=PNG)
        value = reading([*self.both_records()["records"], shown("data_flow_900000777", sync_enabled="yes")])
        self.vision(root, value, value)
        _, gate = self.gated(root, record)
        self.assertEqual([(r["cause"], r["verdict"]) for r in gate["rows"]], [("image", "fell_back")])
        self.assertIn("data_flow_900000777", gate["rows"][0]["condition"])

    def test_image_change_falls_back_when_a_waiting_record_got_no_state(self) -> None:
        root, record = self.baseline(image=PNG)
        value = reading([shown("data_flow_900000003", sync_enabled="yes")])  # object_900000004 not shown
        self.vision(root, value, value)
        _, gate = self.gated(root, record)
        self.assertEqual([(r["cause"], r["verdict"]) for r in gate["rows"]], [("image", "fell_back")])
        self.assertIn("object_900000004", gate["rows"][0]["condition"])

    def test_planted_model_free_change_with_no_cause_stops(self) -> None:
        """T100: an unexplained difference from the model-free row still stops the run (here a planted
        model-free row: no model input explains the computed row's difference from it)."""
        root, _ = self.baseline()
        real = pipeline.model_free_records

        def planted(*args: Any, **kw: Any) -> dict[str, Any]:
            out = real(*args, **kw)
            out[C1] = replace(out[C1], steps=out[C1].steps[:-1])  # one step fewer: a different row
            return out

        with mock.patch.object(pipeline, "model_free_records", planted):
            s, gate = self.gated(root)
        self.assertEqual([(r["case_id"], r["cause"], r["verdict"]) for r in gate["rows"]],
                         [(C1, "unexplained", "stop")])
        self.assertFalse(s.passed)
        producer = read_json(self.runs / "gated" / "producer.json")
        self.assertIn("1 changed row(s) marked stop", producer["refusal"])
        self.assertFalse(producer["run_passed"])
        self.assertEqual((self.runs / "gated" / "output.csv").read_bytes(),
                         (self.runs / "base" / "output.csv").read_bytes())  # a stop row keeps the computed row

    def test_engine_only_run_has_no_model_change(self) -> None:
        """An engine-only replay (empty cache) writes exactly its model-free rows: nothing is judged."""
        root, _ = self.baseline(image=PNG)
        s = run(root, run_id="eng", cases="test", runs_dir=self.runs, model=ModelSetup.replay(self.tmp / "empty2"))
        gate = read_json(self.runs / "eng" / "regression_vs_engine.json")
        self.assertEqual((gate["changed_rows"], gate["passed"], s.passed), (0, True, True))
        d = self.runs / "eng"
        self.assertEqual((d / "output.csv").read_bytes(), (d / "output_raw.csv").read_bytes())


if __name__ == "__main__":
    unittest.main()
