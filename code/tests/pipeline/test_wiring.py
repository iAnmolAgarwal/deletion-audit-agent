"""The G7 wiring of ``pipeline.run``: replay-only by default, the agent per case, vision, and the artifacts.

All on GM's FakeTransport and temporary caches and run directories (made-up people and IDs).
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from deletion_audit.agent.questions import oq_id
from deletion_audit.engine import audit_all, build_context
from deletion_audit.pipeline import ModelSetup, VisionReviewRequired, run, run_vision
from deletion_audit.steps.serialize import render_output

from ..agent._support import (
    C1,
    C2,
    DELETE_TEXT,
    KEEP_TEXT,
    PNG,
    answer,
    answer_for,
    audit_input,
    dataset,
    final_reply,
    tmpdir,
    tool_reply,
)
from ..steps.test_steps import hand_key
from ._wiring import cases_jsonl, paid_setup, read_json, reading, sent, shown

DELETION = final_reply(answer("DELETION_REQUEST", "delete my account", kind="full_deletion"))
NOT_DELETION = final_reply(answer("NOT_DELETION", "Send me a copy of my data"))


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tmpdir()
        self.runs = self.tmp / "rundirs"
        self.replies = self.tmp / "replycache"

    def write(self, **kw: object) -> Path:
        d = dataset(**kw)  # type: ignore[arg-type]
        (self.tmp / "ds").mkdir(exist_ok=True)
        return d.write(self.tmp / "ds")

    def replay(self, root: Path, run_id: str, cache: Path | None = None, **kw: object) -> object:
        return run(root, run_id=run_id, cases="test", runs_dir=self.runs,
                   model=ModelSetup.replay(cache or self.replies), **kw)  # type: ignore[arg-type]


class TestReplayOnly(Base):
    def test_empty_cache_sends_nothing_and_equals_the_engine_rows(self) -> None:
        """The regression gate in small: every intent fails closed, so the rows are G5's (T71 Q2)."""
        root = self.write()
        s = run(root, run_id="r1", cases="test", runs_dir=self.runs, model=ModelSetup.replay(self.replies))
        ctx = build_context(root)
        engine = audit_all(ctx, sorted(r.case_id for r in ctx.requests))
        expected = render_output([(r.case_id, r.status, r.steps) for r in engine.values()])
        self.assertEqual((self.runs / "r1" / "output.csv").read_bytes(), expected)
        usage = read_json(self.runs / "r1" / "usage.json")
        self.assertEqual((usage["model_calls"], usage["replies_bought"], usage["model_ids"]), (0, 0, []))
        self.assertEqual(usage["replay_misses"], 4)  # 2 cases x (turn 1 + its replicate); no image
        self.assertFalse(self.replies.exists())  # a replay run writes nothing to the cache
        producer = read_json(self.runs / "r1" / "producer.json")
        self.assertEqual((producer["paid_model_calls"], producer["replay_only"]), (0, True))
        self.assertEqual(producer["intent_sources"], {"FAILED_CLOSED": 2})
        self.assertTrue(s.passed)

    def test_paid_flag_and_setup_must_agree(self) -> None:
        root = self.write()
        with self.assertRaises(ValueError):
            run(root, run_id="r", cases="test", runs_dir=self.runs, replay_only=False)
        with self.assertRaises(ValueError):
            run(root, run_id="r", cases="test", runs_dir=self.runs, replay_only=True,
                model=paid_setup(self.replies, []))
        with self.assertRaises(ValueError):
            run(root, run_id="r", cases="test", runs_dir=self.runs, mode="B",  # type: ignore[arg-type]
                model=ModelSetup.replay(self.replies))

    def test_separate_namespaces_are_required(self) -> None:
        setup = ModelSetup.replay(self.replies)
        with self.assertRaises(ValueError):
            ModelSetup(setup.transport, setup.budget, (setup.roots[0], setup.roots[0]), paid=False)

    def test_replay_is_deterministic(self) -> None:
        root = self.write(image=PNG)
        self.replay(root, "a")
        self.replay(root, "b")
        for name in ("output.csv", "cases.jsonl", "vision_readings.json", "vision.json"):
            self.assertEqual((self.runs / "a" / name).read_bytes(), (self.runs / "b" / name).read_bytes(), name)


class TestPaidRun(Base):
    def test_agent_per_case_and_the_artifacts(self) -> None:
        root = self.write()
        setup = paid_setup(self.replies, [tool_reply(("audit_case", audit_input())), DELETION, NOT_DELETION])
        s = run(root, run_id="p1", cases="test", runs_dir=self.runs, replay_only=False, model=setup)
        d = self.runs / "p1"
        self.assertEqual(len(sent(setup)), 3)  # C1: turn 1 + final; C2: turn 1; replicates replay only
        cases = cases_jsonl(d)
        a1, a2 = cases[C1]["agent"], cases[C2]["agent"]
        self.assertEqual((a1["intent"]["source"], a1["audit_case_calls"]), ("MODEL", 1))
        # C2's NOT_DELETION has one turn-1 reading (the replicate missed), so the intent change fails its
        # condition: the output and cases.jsonl carry the model-free row; output_raw.csv the computed one
        self.assertNotEqual(cases[C2]["status"], "NOT_APPLICABLE")
        self.assertIn("MODEL_CHANGE_FELL_BACK", {f["code"] for f in cases[C2]["flags"]})
        self.assertIn(f"{C2},NOT_APPLICABLE,[]", (d / "output_raw.csv").read_text(encoding="utf-8"))
        self.assertEqual(a2["intent"]["committed_label"], "NOT_DELETION")
        self.assertEqual(a2["turn1_replicates"], ["NOT_DELETION", None])  # replicate namespace: replay miss
        self.assertIsNone(cases[C2]["intent_label"])  # the fallback record is the model-free one (fail-closed)
        self.assertIn("instruction_like_text", cases[C1])
        calls = [json.loads(x) for x in (d / "calls.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(sum(1 for c in calls if c["event"] == "send"), 3)
        usage = read_json(d / "usage.json")
        self.assertEqual((usage["model_calls"], usage["replies_bought"]), (3, 3))
        self.assertEqual(usage["input_tokens"], 3 * 900)
        self.assertEqual(usage["model_ids"], ["claude-sonnet-5-5"])
        self.assertEqual(usage["replies_used"]["bought_by_runs"], {"p1": 3})
        producer = read_json(d / "producer.json")
        self.assertEqual((producer["paid_model_calls"], producer["model_ids"]), (3, ["claude-sonnet-5-5"]))
        self.assertEqual(producer["budget"]["sends"], 3)
        self.assertFalse(setup.budget.holds_run_lock)  # released at the end of the run
        self.assertEqual(s.rows, 2)

    def test_status_and_order_follow_the_steps(self) -> None:
        root = self.write()
        setup = paid_setup(self.replies, [tool_reply(("audit_case", audit_input())), DELETION, NOT_DELETION])
        run(root, run_id="p2", cases="test", runs_dir=self.runs, replay_only=False, model=setup)
        import csv

        with (self.runs / "p2" / "output.csv").open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                steps = json.loads(row["steps_json"])
                if row["deletion_status"] == "NOT_APPLICABLE":
                    self.assertEqual(steps, [])
                else:
                    has_finding = any(s["phase"] == "FINDING" for s in steps)
                    self.assertEqual(row["deletion_status"] == "INCOMPLETE", has_finding)
                self.assertEqual([s["step_no"] for s in steps], list(range(1, len(steps) + 1)))
                keys = [hand_key(s["phase"], s["operation"], s["system_id"], s["resource_id"]) for s in steps]
                self.assertEqual(keys, sorted(keys))

    def test_mode_is_recorded_and_tools_off_sends_turn1_only(self) -> None:
        root = self.write()
        setup = paid_setup(self.replies, [DELETION, NOT_DELETION])
        run(root, run_id="p3", cases="test", runs_dir=self.runs, replay_only=False, model=setup, mode="tools_off")
        cases = cases_jsonl(self.runs / "p3")
        self.assertEqual({c["agent"]["mode"] for c in cases.values()}, {"tools_off"})
        self.assertEqual(len(sent(setup)), 2)
        self.assertTrue(all("tools" in b and b["tool_choice"]["type"] == "auto" for b in sent(setup)))

    def test_budget_refusal_fails_closed_flagged(self) -> None:
        root = self.write()
        setup = paid_setup(self.replies, [], call_cap=0)
        run(root, run_id="p4", cases="test", runs_dir=self.runs, replay_only=False, model=setup)
        cases = cases_jsonl(self.runs / "p4")
        self.assertEqual({c["agent"]["intent"]["source"] for c in cases.values()}, {"FAILED_BUDGET"})
        self.assertTrue(all(c["status"] != "NOT_APPLICABLE" for c in cases.values()))
        self.assertEqual(sent(setup), [])

    def test_calls_file_is_fresh_per_run(self) -> None:
        root = self.write()
        self.replay(root, "same")
        first = (self.runs / "same" / "calls.jsonl").read_text(encoding="utf-8")
        self.replay(root, "same")
        self.assertEqual((self.runs / "same" / "calls.jsonl").read_text(encoding="utf-8"), first)


class TestVisionWiring(Base):
    def vision_run(self, root: Path, r1: dict[str, object], r2: dict[str, object], run_id: str = "vis") -> None:
        setup = paid_setup(self.replies, [final_reply(r1), final_reply(r2)])
        run_vision(root, run_id=run_id, model=setup, runs_dir=self.runs)
        self.assertEqual(len(sent(setup)), 2)

    def test_unread_png_stays_an_unparsed_dependency(self) -> None:
        root = self.write(image=PNG)
        self.replay(root, "nov")
        producer = read_json(self.runs / "nov" / "producer.json")
        self.assertEqual(producer["evidence_skipped"], ["ev_img:png-model-needed"])
        self.assertEqual(producer["evidence_read_by_vision"], [])
        self.assertEqual(cases_jsonl(self.runs / "nov")[C1]["failed_closed"], "UNPARSED_DEPENDENCY")

    def test_png_read_ok_is_neither_pending_nor_skipped(self) -> None:
        root = self.write(image=PNG)
        value = reading([shown("data_flow_900000003", sync_enabled="yes"),
                         shown("object_900000004", download_available="yes")])
        self.vision_run(root, value, value)
        self.replay(root, "withv")
        producer = read_json(self.runs / "withv" / "producer.json")
        self.assertEqual(producer["evidence_skipped"], [])
        self.assertEqual(producer["evidence_skip_count"], 0)
        self.assertEqual(producer["evidence_read_by_vision"], ["ev_img"])
        line = cases_jsonl(self.runs / "withv")[C1]
        self.assertNotEqual(line["failed_closed"], "UNPARSED_DEPENDENCY")
        self.assertEqual(line["failed_dependencies"], [])
        flow = next(r for r in line["resources"] if r["resource_id"] == "data_flow_900000003")
        self.assertEqual(flow["outcome"], "FINDING")
        for name in ("vision_readings.json", "vision_readings.md", "vision.json"):
            self.assertTrue((self.runs / "withv" / name).is_file(), name)

    def test_one_failed_reading_keeps_the_dependency(self) -> None:
        root = self.write(image=PNG)
        value = reading([shown("data_flow_900000003", sync_enabled="yes")])
        setup = paid_setup(self.replies, [final_reply(value), {"not": "a reply"}])
        run_vision(root, run_id="half", model=setup, runs_dir=self.runs)
        self.replay(root, "halfrun")
        producer = read_json(self.runs / "halfrun" / "producer.json")
        self.assertEqual(producer["evidence_skipped"], ["ev_img:png-model-needed"])
        self.assertEqual(cases_jsonl(self.runs / "halfrun")[C1]["failed_closed"], "UNPARSED_DEPENDENCY")

    def test_paid_full_run_never_buys_vision_and_is_refused_without_review(self) -> None:
        root = self.write(image=PNG)
        setup = paid_setup(self.replies, [DELETION, NOT_DELETION])
        with self.assertRaises(VisionReviewRequired):
            run(root, run_id="pv", cases="test", runs_dir=self.runs, replay_only=False, model=setup)
        self.assertEqual(sent(setup), [])  # the vision readings were replayed, not bought
        self.assertTrue((self.runs / "pv" / "refused.json").is_file())
        self.assertFalse((self.runs / "pv" / "output.csv").exists())
        self.assertFalse(setup.budget.holds_run_lock)

    def test_review_acknowledgement_must_name_the_same_readings(self) -> None:
        root = self.write(image=PNG)
        a = reading([shown("data_flow_900000003", sync_enabled="yes")])
        b = reading([shown("data_flow_900000003", sync_enabled="no")])
        self.vision_run(root, a, b)
        review = read_json(self.runs / "vis" / "vision_readings.json")
        self.assertEqual(review["needs_review"], ["ev_img"])
        # an acknowledgement of other readings is refused
        other = self.runs / "other"
        other.mkdir(parents=True)
        changed = json.loads(json.dumps(review))
        changed["images"][0]["agree"] = True
        (other / "vision_readings.json").write_text(json.dumps(changed), encoding="utf-8")
        for ack in (None, "other", "missing-run", "bad id"):
            setup = paid_setup(self.replies, [DELETION, NOT_DELETION], call_cap=10)
            with self.assertRaises(VisionReviewRequired, msg=str(ack)):
                run(root, run_id="pa", cases="test", runs_dir=self.runs, replay_only=False, model=setup,
                    mode="tools_off", vision_ack=ack)
            self.assertEqual(sent(setup), [])
        # the matching acknowledgement lets the paid run go on, and is recorded
        setup = paid_setup(self.replies, [DELETION, NOT_DELETION])
        run(root, run_id="pa", cases="test", runs_dir=self.runs, replay_only=False, model=setup, mode="tools_off",
            vision_ack="vis")
        rev = read_json(self.runs / "pa" / "producer.json")["vision"]["review"]
        self.assertEqual((rev["ack_run_id"], rev["ack_matches"], rev["needs_review"]), ("vis", True, ["ev_img"]))

    def test_image_field_answer_is_applied_through_the_patched_world(self) -> None:
        """G7a proposal 6: a validated IMAGE_FIELD_UNREADABLE answer fills its field for the applied compile."""
        root = self.write(image=PNG)
        r1 = reading([shown("data_flow_900000003", sync_enabled="no")])
        r2 = reading([shown("data_flow_900000003", sync_enabled="not_shown")])  # merged: unreadable
        self.vision_run(root, r1, r2)
        q = oq_id(C1, "IMAGE_FIELD_UNREADABLE", "ev_img:data_flow_900000003:sync_enabled")
        final = final_reply(answer("DELETION_REQUEST", "delete my account", kind="full_deletion",
                                   answers=[answer_for(q, "yes", ["ev_img"])]))
        script = [tool_reply(("audit_case", audit_input())),
                  tool_reply(("inspect_evidence", {"file_id": "ev_img", "focus": "state"})), final, NOT_DELETION]
        setup = paid_setup(self.replies, script)
        run(root, run_id="ans", cases="test", runs_dir=self.runs, replay_only=False, model=setup, vision_ack="vis")
        line = cases_jsonl(self.runs / "ans")[C1]
        self.assertEqual(line["agent"]["answers_applied"], [q])
        self.assertTrue(line["agent"]["steps_differ_when_applied"])
        self.assertIn(q, line["open_questions"])
        self.assertEqual(line["answers"], [q])
        # the answered field (sync enabled) gives a finding in the computed row; the readings disagree on
        # it, so the change falls back to the model-free row (T118 rule (a)) and cases.jsonl says so
        raw = next(x for x in (self.runs / "ans" / "output_raw.csv").read_text(encoding="utf-8").splitlines()
                   if x.startswith(C1 + ","))
        self.assertIn("FINDING", raw)
        changes = read_json(self.runs / "ans" / "regression_vs_engine.json")
        self.assertIn((C1, "image", "fell_back"), [(r["case_id"], r["cause"], r["verdict"]) for r in changes["rows"]])

    def test_texts_never_reach_the_artifacts(self) -> None:
        root = self.write(image=PNG)
        setup = paid_setup(self.replies, [tool_reply(("audit_case", audit_input())), DELETION, NOT_DELETION])
        with self.assertRaises(VisionReviewRequired):
            run(root, run_id="tx", cases="test", runs_dir=self.runs, replay_only=False, model=setup)
        self.replay(root, "tx2")
        for p in sorted((self.runs / "tx2").iterdir()):
            text = p.read_text(encoding="utf-8")
            self.assertNotIn(DELETE_TEXT[:24], text, p.name)
            self.assertNotIn(KEEP_TEXT[:24], text, p.name)


class TestMalformedRows(Base):
    def test_malformed_request_gets_a_not_run_agent_block(self) -> None:
        fixtures = Path(__file__).resolve().parents[1] / "fixtures"
        root = fixtures / "F11b_malformed_request_rows"
        s = run(root, run_id="mal", cases="test", runs_dir=self.runs, model=ModelSetup.replay(self.replies))
        cases = cases_jsonl(self.runs / "mal")
        bad = [c for c in cases.values() if c["failed_closed"] == "MALFORMED_REQUEST"]
        self.assertTrue(bad)
        for c in bad:
            self.assertEqual(c["agent"]["status"], "FAILED")
            self.assertEqual(c["agent"]["not_run_reason"], "MALFORMED_REQUEST")
            self.assertIsNone(c["agent"]["intent"]["label"])
        self.assertEqual(s.rows, len(cases))


if __name__ == "__main__":
    unittest.main()
