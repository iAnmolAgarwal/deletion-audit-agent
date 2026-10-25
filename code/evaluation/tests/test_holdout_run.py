"""holdout_run, behavioural (T96): every refusal reads no gold and logs nothing; the good path is exact.

Synthetic only (T48): a temporary git repo, synthetic runs, split, gold and access log, a
fake engine and GM's FakeTransport behind a real ModelClient (``holdout_fixtures``). The real
``runs/HOLDOUT_ACCESS.log`` and ``dataset/sample_output.csv`` are never opened.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from evaluation import gold as gold_mod
from evaluation import holdout_run as hr
from evaluation import paths

from .holdout_fixtures import (
    CAVEAT,
    FREEZE_RUN,
    HOLD,
    RUN_ID,
    TAG,
    OpenSpy,
    World,
    argv,
    git,
)
from .run_dirs import case

PHRASE = gold_mod.UNLOCK_PHRASE
REAL_ACCESS_LOG = paths.HOLDOUT_ACCESS_LOG
REAL_GOLD = paths.SAMPLE_OUTPUT  # bound at import, before any patch


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.w = World().start()

    def tearDown(self) -> None:
        self.w.stop()

    def assertRefusedClean(self, args: list[str], **kw: Any) -> str:
        """Exit 3, no access log, the gold and dataset never opened, the engine never run, no phrase shown."""
        spy = OpenSpy()
        with spy.active():
            status, err = self.w.main(args, **kw)
        self.assertEqual(status, hr.EXIT_REFUSED, err)
        self.assertIn("HOLDOUT RUN REFUSED", err)
        self.assertNotIn(PHRASE, err)
        self.assertNotIn(PHRASE.lower(), err.lower())
        self.assertFalse(self.w.access_log.exists(), "a refusal wrote the access log")
        self.assertEqual(spy.touched(self.w.gold_dir), [], "a refusal opened the gold")
        self.assertEqual(spy.touched(self.w.dataset), [], "a refusal opened a holdout input")
        self.assertEqual(self.w.runner_calls, [], "a refusal ran the engine")
        self.assertEqual(self.w.factory_budgets, [], "a refusal built a paid client")
        self.assertFalse((self.w.runs / RUN_ID).exists(), "a refusal wrote a run directory")
        return err


class TestPhraseRefusals(Base):
    def test_no_phrase(self) -> None:
        self.assertRefusedClean(argv())

    def test_wrong_phrase(self) -> None:
        self.assertRefusedClean(argv(phrase="yes, go ahead"))

    def test_lower_case(self) -> None:
        self.assertRefusedClean(argv(phrase=PHRASE.lower()))

    def test_trailing_and_leading_space(self) -> None:
        self.assertRefusedClean(argv(phrase=PHRASE + " "))
        self.assertRefusedClean(argv(phrase=" " + PHRASE))

    def test_empty_phrase(self) -> None:
        self.assertRefusedClean(argv(phrase=""))

    def test_phrase_in_environment_only(self) -> None:
        env = {"HOLDOUT_UNLOCK": PHRASE, "UNLOCK_PHRASE": PHRASE, "HOLDOUT_EVALUATION_RUN": PHRASE, "UNLOCK": PHRASE}
        with mock.patch.dict(os.environ, env):
            self.assertRefusedClean(argv())

    def test_abbreviated_option_is_not_accepted(self) -> None:
        with self.assertRaises(SystemExit):  # allow_abbrev=False: "--unl" is an unknown option
            self.w.main(["--unl", PHRASE, *argv()])
        self.assertFalse(self.w.access_log.exists())


class TestFrozenCodeRefusals(Base):
    def test_missing_tag(self) -> None:
        self.assertRefusedClean(argv(phrase=PHRASE, tag="freeze-20991231"))

    def test_tag_wrong_shape(self) -> None:
        self.assertRefusedClean(argv(phrase=PHRASE, tag="v1"))

    def test_tag_not_at_head(self) -> None:
        (self.w.repo / "later.txt").write_text("later\n", encoding="utf-8")
        git(self.w.repo, "add", "later.txt")
        git(self.w.repo, "commit", "-q", "-m", "after the freeze")
        err = self.assertRefusedClean(argv(phrase=PHRASE))
        self.assertIn("HEAD is not the commit", err)

    def test_dirty_tracked_file(self) -> None:
        (self.w.repo / "frozen.txt").write_text("edited after the freeze\n", encoding="utf-8")
        err = self.assertRefusedClean(argv(phrase=PHRASE))
        self.assertIn("not clean", err)

    def test_staged_change(self) -> None:
        (self.w.repo / "new.txt").write_text("x\n", encoding="utf-8")
        git(self.w.repo, "add", "new.txt")
        self.assertRefusedClean(argv(phrase=PHRASE))

    def test_untracked_outside_runs_and_cache(self) -> None:
        (self.w.repo / "stray.py").write_text("x = 1\n", encoding="utf-8")
        err = self.assertRefusedClean(argv(phrase=PHRASE))
        self.assertIn("stray.py", err)

    def test_untracked_under_runs_and_cache_allowed(self) -> None:
        self.assertEqual(hr.dirty_paths("?? runs/a/b.json\0?? cache/x\0"), [])
        self.assertEqual(hr.dirty_paths("?? runsx/a\0"), ["runsx/a"])
        self.assertEqual(hr.dirty_paths(" M code/a.py\0R  new.py\0old.py\0?? runs/z\0"), ["code/a.py", "new.py"])

    def test_freeze_check_fails(self) -> None:
        self.w.remove_runs_file(FREEZE_RUN)
        self.w.write_freeze_run(cases=[case("case_701", row_state="FAILED_CLOSED", failed_closed="NOTHING_FOUND"),
                                       case("case_702")])
        err = self.assertRefusedClean(argv(phrase=PHRASE))
        self.assertIn("freeze check refuses", err)

    def test_freeze_run_missing(self) -> None:
        self.assertRefusedClean(argv(phrase=PHRASE, freeze_run="no-such-run"))

    def test_producer_without_commit(self) -> None:
        self.w.remove_runs_file(FREEZE_RUN)
        self.w.write_freeze_run(git_head=None)
        self.assertRefusedClean(argv(phrase=PHRASE))

    def test_producer_names_another_commit(self) -> None:
        self.w.remove_runs_file(FREEZE_RUN)
        self.w.write_freeze_run(git_head="0" * 40)
        err = self.assertRefusedClean(argv(phrase=PHRASE))
        self.assertIn("does not name the frozen commit", err)

    def test_bad_run_ids(self) -> None:
        for rid in ("final-run-x", "holdout-a b", FREEZE_RUN):
            self.assertRefusedClean(argv(phrase=PHRASE, run_id=rid))


class TestGoodPath(Base):
    def run_ok(self, run_id: str = RUN_ID) -> tuple[int, str]:
        spy = OpenSpy()
        with spy.active():
            status, err = self.w.main(argv(phrase=PHRASE, run_id=run_id))
        self.assertEqual(status, hr.EXIT_OK, err)
        self.assertTrue(spy.touched(self.w.gold_dir), "the spy must see the gold opened on the good path")
        return status, err

    def test_access_lines_exact(self) -> None:
        self.run_ok()
        lines = self.w.access_lines()
        ours = {"run_id": RUN_ID, "git_head": self.w.commit, "freeze_tag": TAG, "freeze_run": FREEZE_RUN,
                "argv": argv(phrase=PHRASE), "attempt": 1, "by": "holdout_run"}
        d = self.w.runs / RUN_ID
        expected = [
            {**ours, "what": "engine run"},
            {"what": "engine run", "run_id": RUN_ID},  # the engine's own check_unlock line
            {**ours, "what": "gold"},
            {"what": "gold", "run_id": RUN_ID},  # load_gold's check_unlock line
            {**ours, "what": "complete",
             "output_sha256": hashlib.sha256((d / "output.csv").read_bytes()).hexdigest(),
             "score_sha256": hashlib.sha256((d / "score.json").read_bytes()).hexdigest()},
        ]
        self.assertEqual([{k: v for k, v in x.items() if k != "at"} for x in lines], expected)
        self.assertTrue(all(isinstance(x["at"], str) and x["at"] for x in lines))

    def test_record_and_score(self) -> None:
        self.run_ok()
        rec = self.w.record()
        self.assertEqual(rec["status"], "complete")
        self.assertEqual(rec["caveat"], CAVEAT)
        self.assertEqual(rec["freeze_commit"], self.w.commit)
        self.assertEqual(rec["headline"]["status_accuracy"], {"n": 2, "of": 3, "rate": 2 / 3})
        self.assertEqual(rec["budget"]["dollar_cap"], 1.0)
        self.assertEqual(rec["budget"]["call_cap"], 60)
        self.assertEqual(rec["budget"]["paid_sends"], 1)
        self.assertGreater(rec["budget"]["spent_usd"], 0)
        self.assertEqual(len(rec["attempts"]), 1)
        self.assertTrue(rec["freeze_check"]["passed"])
        score = json.loads((self.w.runs / RUN_ID / "score.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(c["case_id"] for c in score["cases"]), list(HOLD))
        self.assertEqual(score["aggregate"]["published"]["status_accuracy"]["n"], 2)
        self.assertEqual(score["caveat"], CAVEAT)

    def test_engine_called_with_holdout_cases_and_caps(self) -> None:
        self.run_ok()
        self.assertEqual(len(self.w.runner_calls), 1)
        call = self.w.runner_calls[0]
        self.assertEqual(call["cases"], sorted(HOLD))
        self.assertTrue(call["phrase_ok"])
        self.assertEqual(call["dataset_dir"], self.w.dataset)
        (budget,) = self.w.factory_budgets
        self.assertEqual((budget.dollar_cap, budget.call_cap), (hr.HOLDOUT_DOLLAR_CAP, hr.HOLDOUT_CALL_CAP))
        self.assertEqual((budget.dollar_cap, budget.call_cap), (1.0, 60))
        self.assertEqual(budget.ledger, self.w.cache / "ledger.jsonl")
        self.assertFalse(budget.holds_run_lock, "the paid-run lock must be released after the run")

    def test_second_run_refused_after_completion(self) -> None:
        self.run_ok()
        before = self.w.access_log.read_bytes()
        spy = OpenSpy()
        with spy.active():
            status, err = self.w.main(argv(phrase=PHRASE, run_id="holdout-20261025T1600"))
        self.assertEqual(status, hr.EXIT_REFUSED, err)
        self.assertEqual(self.w.access_log.read_bytes(), before)
        self.assertEqual(spy.touched(self.w.gold_dir), [])
        self.assertEqual(len(self.w.runner_calls), 1)

    def test_same_run_id_refused_after_completion(self) -> None:
        self.run_ok()
        before = self.w.access_log.read_bytes()
        status, _ = self.w.main(argv(phrase=PHRASE))
        self.assertEqual(status, hr.EXIT_REFUSED)
        self.assertEqual(self.w.access_log.read_bytes(), before)

    def test_completed_record_alone_refuses(self) -> None:
        """A completed record refuses even if the access log was lost (runs/ is not committed)."""
        self.run_ok()
        self.w.access_log.unlink()
        status, _ = self.w.main(argv(phrase=PHRASE, run_id="holdout-20261025T1700"))
        self.assertEqual(status, hr.EXIT_REFUSED)
        self.assertFalse(self.w.access_log.exists())

    def test_complete_line_alone_refuses(self) -> None:
        """A complete line refuses even if the record was deleted."""
        self.run_ok()
        self.w.remove_runs_file(RUN_ID)
        status, _ = self.w.main(argv(phrase=PHRASE, run_id="holdout-20261025T1700"))
        self.assertEqual(status, hr.EXIT_REFUSED)


class TestRetry(Base):
    def test_retry_same_run_id_after_crash(self) -> None:
        status, err = self.w.main(argv(phrase=PHRASE), crash=True)
        self.assertEqual(status, hr.EXIT_FAILED, err)
        rec = self.w.record()
        self.assertEqual(rec["status"], "started")
        self.assertIn("simulated engine crash", rec["attempts"][0]["failed"])
        self.assertFalse((self.w.runs / RUN_ID / "score.json").exists())
        self.assertNotIn("gold", [x["what"] for x in self.w.access_lines()], "the crash came before the gold")
        status, err = self.w.main(argv(phrase=PHRASE))
        self.assertEqual(status, hr.EXIT_OK, err)
        rec = self.w.record()
        self.assertEqual(rec["status"], "complete")
        self.assertEqual([a["attempt"] for a in rec["attempts"]], [1, 2])
        self.assertTrue(rec["attempts"][1]["retry"])
        self.assertEqual(rec["attempts"][1]["paid_sends"], 0, "the retry replays the crashed attempt's reply")
        whats = [(x["what"], x.get("attempt")) for x in self.w.access_lines()]
        self.assertEqual(whats, [("engine run", 1), ("engine run", None), ("engine run", 2), ("engine run", None),
                                 ("gold", 2), ("gold", None), ("complete", 2)])

    def test_other_run_id_after_crash_refused(self) -> None:
        self.w.main(argv(phrase=PHRASE), crash=True)
        before = self.w.access_log.read_bytes()
        status, err = self.w.main(argv(phrase=PHRASE, run_id="holdout-20261025T1600"))
        self.assertEqual(status, hr.EXIT_REFUSED, err)
        self.assertEqual(self.w.access_log.read_bytes(), before)

    def test_other_run_id_refused_when_only_the_log_remains(self) -> None:
        self.w.main(argv(phrase=PHRASE), crash=True)
        self.w.remove_runs_file(RUN_ID)
        status, _ = self.w.main(argv(phrase=PHRASE, run_id="holdout-20261025T1600"))
        self.assertEqual(status, hr.EXIT_REFUSED)

    def test_factory_without_the_holdout_budget_fails_before_gold(self) -> None:
        from deletion_audit.model import BudgetGuard

        def rogue(run_id: str, budget: Any, settings: hr.Settings) -> Any:
            return self.w.client_factory(run_id, BudgetGuard(100.0, 10_000, settings.ledger), settings)

        status, err = self.w.main(argv(phrase=PHRASE), client_factory=rogue)
        self.assertEqual(status, hr.EXIT_FAILED, err)
        self.assertEqual(self.w.runner_calls, [])
        self.assertEqual(self.w.access_lines(), [])

    def test_output_not_covering_the_holdout_fails_before_gold(self) -> None:
        def short_runner(**kw: Any) -> Any:
            from .run_dirs import step, write_run
            write_run(kw["runs_dir"], kw["run_id"], {"case_951": ("COMPLETE", [step("account_951")])},
                      [case("case_951")])
            return None

        spy = OpenSpy()
        with spy.active():
            status, err = self.w.main(argv(phrase=PHRASE), runner=short_runner)
        self.assertEqual(status, hr.EXIT_FAILED, err)
        self.assertEqual(spy.touched(self.w.gold_dir), [])
        self.assertNotIn("gold", [x["what"] for x in self.w.access_lines()])


class TestHoldoutSection(Base):
    """The report section renders from a completed record, caveat first (T96 (5))."""

    def completed(self) -> dict[str, Any]:
        status, err = self.w.main(argv(phrase=PHRASE))
        self.assertEqual(status, hr.EXIT_OK, err)
        return self.w.record()

    def test_section_carries_the_caveat_verbatim_before_any_number(self) -> None:
        text = hr.holdout_section(self.completed())
        self.assertIn(CAVEAT, text)
        self.assertLess(text.index(CAVEAT), text.index("Status accuracy"))
        self.assertIn(f"## Holdout evaluation (run {RUN_ID})", text)
        self.assertIn("| Status accuracy | 2/3 (0.6667) |", text)
        self.assertIn(self.w.commit, text)
        self.assertIn(TAG, text)
        self.assertIn("T48", text)
        self.assertNotIn("Pre-change", text)

    def test_pre_change_marker(self) -> None:
        rec = self.completed()
        self.assertNotIn("Pre-change", hr.holdout_section(rec, current_head=self.w.commit))
        self.assertIn("Pre-change", hr.holdout_section(rec, current_head="f" * 40))

    def test_pre_change_states_whether_the_package_moved(self) -> None:
        """T127 B6: the pre-change line says whether code/deletion_audit differs, from the caller's git result."""
        rec, other = self.completed(), "f" * 40
        same = hr.holdout_section(rec, current_head=other, package_changed=False)
        moved = hr.holdout_section(rec, current_head=other, package_changed=True)
        unknown = hr.holdout_section(rec, current_head=other, package_changed=None)
        self.assertIn("is identical in the two commits", same)
        self.assertIn("differs between the two commits", moved)
        self.assertIn("was not computed (git failed)", unknown)
        self.assertNotIn("identical", hr.holdout_section(rec, current_head=rec["freeze_commit"], package_changed=False))

    def test_notes_render_after_the_table_and_before_the_lock_note(self) -> None:
        text = hr.holdout_section(self.completed(), notes=["- note one"])
        self.assertLess(text.index("Sequence pairwise order"), text.index("- note one"))
        self.assertLess(text.index("- note one"), text.index("T48"))

    def test_refuses_without_caveat_or_completion(self) -> None:
        rec = self.completed()
        for bad in ({**rec, "caveat": ""}, {k: v for k, v in rec.items() if k != "caveat"},
                    {**rec, "status": "started"}):
            with self.assertRaises(ValueError):
                hr.holdout_section(bad)


class TestPipelineRunnerAndBudget(unittest.TestCase):
    def test_caps_are_the_ruling(self) -> None:
        self.assertEqual(hr.HOLDOUT_DOLLAR_CAP, 1.0)
        self.assertEqual(hr.HOLDOUT_CALL_CAP, 60)
        self.assertEqual(hr.HOLDOUT_MODE, "A+")

    def test_make_budget_uses_the_constants(self) -> None:
        s = hr.Settings(repo_root=Path("/x"), runs_root=Path("/x/runs"), dataset_dir=Path("/x/d"),
                        gold_path=Path("/x/g"), split_json=Path("/x/s"), cache_root=Path("/x/cache"))
        b = hr.make_budget(s)
        self.assertEqual((b.dollar_cap, b.call_cap, b.ledger), (1.0, 60, Path("/x/cache/ledger.jsonl")))

    def test_pipeline_runner_passes_the_intended_keywords(self) -> None:
        from deletion_audit import pipeline
        from deletion_audit.model import FakeTransport, MemoryCallLog, ModelClient, ReplyCache, RetryPolicy

        with tempfile.TemporaryDirectory() as tmp:
            budget = hr.make_budget(hr.Settings(repo_root=Path(tmp), runs_root=Path(tmp) / "runs",
                                                dataset_dir=Path(tmp) / "d", gold_path=Path(tmp) / "g",
                                                split_json=Path(tmp) / "s", cache_root=Path(tmp) / "cache"))
            log = MemoryCallLog()
            client = ModelClient(FakeTransport(), ReplyCache(pipeline.namespace_roots(Path(tmp) / "cache")[0]), budget,
                                 RetryPolicy(), log, replay_only=False, run_id="holdout-x")
            try:
                with mock.patch.object(pipeline, "run", return_value="summary") as run:
                    out = hr.pipeline_runner(dataset_dir=Path("/d"), run_id="holdout-x",
                                             cases=("case_952", "case_951"), phrase=PHRASE, client=client,
                                             runs_dir=Path("/r"), command="c")
            finally:
                client.close()
        self.assertEqual(out, "summary")
        run.assert_called_once()
        args, kw = run.call_args
        self.assertEqual(args, (Path("/d"),))
        setup = kw.pop("model")
        self.assertEqual(kw, {"run_id": "holdout-x", "cases": ["case_952", "case_951"], "mode": "A+",
                              "replay_only": False, "holdout_unlock": PHRASE, "runs_dir": Path("/r"), "command": "c",
                              "vision_ack": hr.HOLDOUT_VISION_ACK})
        # the holdout client's wiring: same transport, the one $1/60 guard, its policy and log; paid
        self.assertIs(setup.transport, client.transport)
        self.assertIs(setup.budget, budget)
        self.assertEqual((setup.budget.dollar_cap, setup.budget.call_cap), (1.0, 60))
        self.assertIs(setup.policy, client.policy)
        self.assertIs(setup.extra_log, log)
        self.assertTrue(setup.paid)
        self.assertEqual(setup.roots, pipeline.namespace_roots(Path(tmp) / "cache"))


class TestRealPathsUntouched(unittest.TestCase):
    def test_world_never_points_at_the_real_access_log_or_gold(self) -> None:
        w = World().start()
        try:
            self.assertNotEqual(Path(vars(gold_mod)["HOLDOUT_ACCESS_LOG"]).resolve(), REAL_ACCESS_LOG.resolve())
            self.assertNotEqual(paths.SAMPLE_OUTPUT.resolve(), REAL_GOLD.resolve())
            self.assertNotEqual(w.settings().gold_path.resolve(), REAL_GOLD.resolve())
        finally:
            w.stop()

    def test_default_caveat_is_split_json_created(self) -> None:
        """The record's caveat is read from the real notes/split.json, never retyped (T96 (5))."""
        if not paths.SPLIT_JSON.exists():
            self.skipTest("notes/split.json is not shipped (code.zip holds README.md and code/ only)")
        created = json.loads(paths.SPLIT_JSON.read_text(encoding="utf-8"))["created"]
        self.assertEqual(hr.read_caveat(hr.default_settings()), created)


if __name__ == "__main__":
    unittest.main()
