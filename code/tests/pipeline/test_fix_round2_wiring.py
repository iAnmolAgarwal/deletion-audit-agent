"""G5 fix round 2 in the wired pipeline (developer ruling T112): items 10, 11 and 4 (b).

All on GM's FakeTransport with temporary caches, run directories and (for the root file) a temporary
``REPO_ROOT``, as the G7 verifier's probe ``p5_writeroot.py`` does. Made-up people and IDs.
"""

from __future__ import annotations

import unittest
from unittest import mock

from deletion_audit import pipeline
from deletion_audit.pipeline import ModelSetup, run, run_vision

from ..agent._support import PNG, answer, dataset, final_reply, tmpdir
from ._wiring import approve, cases_jsonl, paid_setup, read_json, reading, seed_turn1, shown


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tmpdir()
        self.runs = self.tmp / "rundirs"
        (self.tmp / "ds").mkdir()
        self.root = dataset().write(self.tmp / "ds")
        run(self.root, run_id="base", cases="test", runs_dir=self.runs, model=ModelSetup.replay(self.tmp / "c0"))


class RootWrittenOnlyAfterTheGate(Base):
    """Item 10 (verifier finding 5): a stopped run leaves the root output.csv untouched."""

    def test_stopped_run_leaves_the_root_file_untouched(self) -> None:
        """Before: the root file was written before the gate ran (``root output.csv written: True``)."""
        record = approve(
            self.runs / "base" / "output.csv", plant=(sorted(cases_jsonl(self.runs / "base"))[0], "COMPLETE")
        )
        with mock.patch.object(pipeline, "REPO_ROOT", self.tmp):
            s = run(
                self.root,
                run_id="gated",
                cases="test",
                runs_dir=self.runs,
                model=ModelSetup.replay(self.tmp / "c1"),
                approved_record=record,
                write_root=True,
            )
        self.assertFalse(s.passed)
        self.assertFalse((self.tmp / "output.csv").exists())
        producer = read_json(self.runs / "gated" / "producer.json")
        self.assertEqual(producer["root_output"], {"requested": True, "written": False})

    def test_an_existing_root_file_is_not_overwritten_by_a_stopped_run(self) -> None:
        (self.tmp / "output.csv").write_text("kept\n", encoding="utf-8")
        record = approve(
            self.runs / "base" / "output.csv", plant=(sorted(cases_jsonl(self.runs / "base"))[0], "COMPLETE")
        )
        with mock.patch.object(pipeline, "REPO_ROOT", self.tmp):
            run(
                self.root,
                run_id="gated2",
                cases="test",
                runs_dir=self.runs,
                model=ModelSetup.replay(self.tmp / "c1"),
                approved_record=record,
                write_root=True,
            )
        self.assertEqual((self.tmp / "output.csv").read_text(encoding="utf-8"), "kept\n")

    def test_passing_run_writes_the_root_file(self) -> None:
        record = approve(self.runs / "base" / "output.csv")
        with mock.patch.object(pipeline, "REPO_ROOT", self.tmp):
            s = run(
                self.root,
                run_id="ok",
                cases="test",
                runs_dir=self.runs,
                model=ModelSetup.replay(self.tmp / "c1"),
                approved_record=record,
                write_root=True,
            )
        self.assertTrue(s.passed)
        self.assertEqual((self.tmp / "output.csv").read_bytes(), s.output_path.read_bytes())
        self.assertTrue(read_json(self.runs / "ok" / "producer.json")["regression_gate"]["mandatory"])


class GateMandatoryWhenTheModelIsOn(Base):
    """Item 11 (verifier MINOR 7): no opt-out of the gate for a paid run or a replay with model replies."""

    def test_replay_with_model_replies_is_gated_without_asking(self) -> None:
        """Before: ``regression_gate`` defaulted to False, so this run had no T101 stop."""
        record = approve(self.runs / "base" / "output.csv")
        cache = self.tmp / "replies"
        nd = final_reply(answer("NOT_DELETION", "Send me a copy of my data"))
        from ..agent._support import KEEP_TEXT

        seed_turn1(cache, KEEP_TEXT, [nd, nd])
        s = run(
            self.root,
            run_id="m",
            cases="test",
            runs_dir=self.runs,
            model=ModelSetup.replay(cache),
            approved_record=record,
        )
        producer = read_json(self.runs / "m" / "producer.json")
        self.assertTrue(producer["model_on"])
        self.assertTrue(producer["regression_gate"]["mandatory"])
        self.assertTrue((self.runs / "m" / "regression_vs_engine.json").is_file())
        self.assertIsNotNone(s.gate)

    def test_paid_run_is_gated_and_regression_gate_false_does_not_turn_it_off(self) -> None:
        dr = final_reply(answer("DELETION_REQUEST", "delete my account", kind="full_deletion"))
        s = run(
            self.root,
            run_id="p",
            cases="test",
            runs_dir=self.runs,
            replay_only=False,
            model=paid_setup(self.tmp / "replies2", [dr, dr]),
            mode="tools_off",
            regression_gate=False,
            approved_record=approve(self.runs / "base" / "output.csv"),
        )
        self.assertIsNotNone(s.gate)
        self.assertTrue(read_json(self.runs / "p" / "producer.json")["regression_gate"]["mandatory"])

    def test_engine_only_replay_is_not_gated_unless_asked(self) -> None:
        s = run(self.root, run_id="e", cases="test", runs_dir=self.runs, model=ModelSetup.replay(self.tmp / "c2"))
        producer = read_json(self.runs / "e" / "producer.json")
        self.assertEqual((s.gate, producer["model_on"], producer["regression_gate"]), (None, False, {"run": False}))


class VisionReviewList(unittest.TestCase):
    """Item 4 (b): every image whose reading changes a row is on the review list; the recorded
    acknowledgement lists each image with both reading keys."""

    def test_row_changing_image_needs_review_and_lists_both_keys(self) -> None:
        """Before: an agreeing, successful reading that changed a row was not on the list."""
        tmp = tmpdir()
        (tmp / "ds").mkdir()
        root = dataset(image=PNG).write(tmp / "ds")
        value = reading([shown("data_flow_900000003", sync_enabled="yes")])
        cache = tmp / "replycache"
        rec = run_vision(
            root,
            run_id="vis",
            model=paid_setup(cache, [final_reply(value), final_reply(value)]),
            runs_dir=tmp / "rundirs",
        )
        self.assertEqual(rec["needs_review"], ["ev_img"])
        self.assertEqual(read_json(tmp / "rundirs" / "vis" / "vision_readings.json")["needs_review"], ["ev_img"])
        run(
            root,
            run_id="full",
            cases="test",
            runs_dir=tmp / "rundirs",
            model=ModelSetup.replay(cache),
            vision_ack="vis",
        )
        review = read_json(tmp / "rundirs" / "full" / "producer.json")["vision"]["review"]
        self.assertEqual(review["needs_review"], ["ev_img"])
        self.assertTrue(review["ack_matches"])
        (ack,) = review["acknowledged"]
        self.assertEqual(sorted(ack), ["file_id", "reading_sha256", "reply_keys"])
        self.assertEqual(ack["file_id"], "ev_img")
        self.assertEqual(len(ack["reply_keys"]), 2)
        self.assertEqual(len(ack["reading_sha256"]), 2)
        self.assertTrue(all(isinstance(h, str) and len(h) == 64 for h in ack["reading_sha256"]))

    def test_a_re_read_with_a_different_reply_no_longer_matches(self) -> None:
        """Both readings share one request key, so only the reply hash tells a re-read from the reviewed
        reading: here the re-read parses to the same reading and differs only in its raw reply."""
        tmp = tmpdir()
        (tmp / "ds").mkdir()
        root = dataset(image=PNG).write(tmp / "ds")
        value = reading([shown("data_flow_900000003", sync_enabled="yes")])
        reviewed = final_reply(value)
        reread = final_reply(value)
        reread["content"][0]["signature"] = "a-different-signature"
        run_vision(root, run_id="vis", model=paid_setup(tmp / "c1", [reviewed, reviewed]), runs_dir=tmp / "rundirs")
        run_vision(root, run_id="vis2", model=paid_setup(tmp / "c2", [reviewed, reread]), runs_dir=tmp / "rundirs")
        run(
            root,
            run_id="full",
            cases="test",
            runs_dir=tmp / "rundirs",
            model=ModelSetup.replay(tmp / "c2"),
            vision_ack="vis",
        )
        review = read_json(tmp / "rundirs" / "full" / "producer.json")["vision"]["review"]
        self.assertEqual(review["needs_review"], ["ev_img"])
        self.assertFalse(review["ack_matches"])
        self.assertEqual(review["acknowledged"], [])

    def test_listed_exactly_when_the_reading_changes_a_row(self) -> None:
        """An agreeing, successful reading is on the list exactly when the outputs without and with it differ."""
        for value in (reading([]), reading([shown("object_900000004", download_available="yes")])):
            with self.subTest(records=len(value["records"])):
                tmp = tmpdir()
                (tmp / "ds").mkdir()
                root = dataset(image=PNG).write(tmp / "ds")
                cache = tmp / "replycache"
                rec = run_vision(
                    root, run_id="vis", model=paid_setup(cache, [final_reply(value)] * 2), runs_dir=tmp / "rundirs"
                )
                self.assertEqual(rec["read_ok"], ["ev_img"])
                run(root, run_id="a", cases="test", runs_dir=tmp / "rundirs", model=ModelSetup.replay(tmp / "e"))
                run(
                    root,
                    run_id="b",
                    cases="test",
                    runs_dir=tmp / "rundirs",
                    model=ModelSetup.replay(cache),
                    vision_ack="vis",
                )
                changed = (tmp / "rundirs" / "a" / "output.csv").read_bytes() != (
                    tmp / "rundirs" / "b" / "output.csv"
                ).read_bytes()
                self.assertEqual("ev_img" in rec["needs_review"], changed)


if __name__ == "__main__":
    unittest.main()
