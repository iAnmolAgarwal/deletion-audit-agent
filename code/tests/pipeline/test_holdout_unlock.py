"""``pipeline.run``'s one unlock, ``holdout_unlock`` (T96; spec in ``notes/agent_reports/holdout_build.md``).

Synthetic inputs only (T48): the dataset is built in a temporary directory, no gold file exists
and none is read, and the access log is redirected to a temporary file, so the real
``runs/HOLDOUT_ACCESS.log`` is never written. The holdout ID comes from ``split.py`` at run time
(T71 Q8); the phrase comes from ``evaluation.gold``.
"""

from __future__ import annotations

import io
import json
import os
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

from deletion_audit import pipeline
from deletion_audit.pipeline import HoldoutRefused, run
from evaluation import gold as gold_mod
from evaluation.gold import UNLOCK_PHRASE, HoldoutLockedError

from ..engine_fixtures import temp_dir
from .test_holdout_guard import C1, HOLDOUT, dataset

WRONG = ("", "yes", UNLOCK_PHRASE.lower(), UNLOCK_PHRASE + " ", " " + UNLOCK_PHRASE, UNLOCK_PHRASE.replace(" ", "_"))


class Unlock(unittest.TestCase):
    """Refused without the exact phrase, before any input is read; granted once and logged with it."""

    def setUp(self) -> None:
        self.tmp = temp_dir()
        self.base = Path(self.tmp.__enter__())
        self.log = self.base / "HOLDOUT_ACCESS.log"
        patcher = mock.patch.object(gold_mod, "HOLDOUT_ACCESS_LOG", self.log)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.__exit__, None, None, None)
        (self.base / "ds").mkdir()
        self.root = dataset().write(self.base / "ds")
        self.runs = self.base / "run_out"  # a temporary run directory, never the repo's runs/

    def no_read(self) -> mock._patch:  # type: ignore[type-arg]
        """Fail the test if the run reads any input."""
        return mock.patch.object(pipeline, "build_context", side_effect=AssertionError("an input was read"))

    def test_engine_refuses_holdout_without_phrase(self) -> None:
        with self.no_read(), self.assertRaises(HoldoutRefused):
            run(self.root, run_id="h", cases=[HOLDOUT], runs_dir=self.runs)
        self.assertFalse(self.log.exists())
        self.assertFalse((self.runs / "h").exists())

    def test_engine_refuses_wrong_lowercase_trailing_space(self) -> None:
        for phrase in WRONG:
            with self.subTest(phrase=phrase), redirect_stderr(io.StringIO()):
                with self.no_read(), self.assertRaises(HoldoutLockedError):
                    run(self.root, run_id="h", cases=[HOLDOUT], runs_dir=self.runs, holdout_unlock=phrase)
        self.assertFalse(self.log.exists())
        self.assertFalse((self.runs / "h").exists())

    def test_engine_ignores_phrase_in_environment(self) -> None:
        env = {"HOLDOUT_UNLOCK": UNLOCK_PHRASE, "HOLDOUT_EVALUATION_RUN": UNLOCK_PHRASE, "UNLOCK_PHRASE": UNLOCK_PHRASE}
        with mock.patch.dict(os.environ, env), self.no_read(), self.assertRaises(HoldoutRefused):
            run(self.root, run_id="h", cases=[HOLDOUT], runs_dir=self.runs)
        self.assertFalse(self.log.exists())

    def test_engine_unlock_logs_one_line(self) -> None:
        """With the exact phrase the run goes ahead, and the unlock is logged exactly once."""
        with redirect_stderr(io.StringIO()) as err:
            s = run(self.root, run_id="h1", cases=[HOLDOUT], runs_dir=self.runs, holdout_unlock=UNLOCK_PHRASE)
        lines = [json.loads(x) for x in self.log.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([(x["what"], x["run_id"]) for x in lines], [("engine run", "h1")])
        self.assertIn("HOLDOUT ACCESS GRANTED", err.getvalue())
        self.assertEqual(s.rows, 1)
        producer = json.loads((self.runs / "h1" / "producer.json").read_text(encoding="utf-8"))
        self.assertIs(producer["holdout_unlocked"], True)

    def test_dev_cases_need_no_phrase(self) -> None:
        s = run(self.root, run_id="d", cases=[C1], runs_dir=self.runs)
        self.assertEqual(s.rows, 1)
        self.assertFalse(self.log.exists())
        producer = json.loads((self.runs / "d" / "producer.json").read_text(encoding="utf-8"))
        self.assertIs(producer["holdout_unlocked"], False)

    def test_phrase_on_a_run_without_holdout_cases_unlocks_nothing(self) -> None:
        s = run(self.root, run_id="d2", cases=[C1], runs_dir=self.runs, holdout_unlock=UNLOCK_PHRASE)
        self.assertEqual(s.rows, 1)
        self.assertFalse(self.log.exists())

    def test_producer_records_git_head(self) -> None:
        run(self.root, run_id="g", cases=[C1], runs_dir=self.runs)
        producer = json.loads((self.runs / "g" / "producer.json").read_text(encoding="utf-8"))
        self.assertEqual(producer["git_head"], pipeline.git_head())
        self.assertRegex(producer["git_head"] or "", r"^([0-9a-f]{40})?$")

    def test_guard_removed_fails(self) -> None:
        """The refusal tests depend on the guard: with it patched out, a holdout case runs."""
        with mock.patch.object(pipeline, "guard_holdout", lambda cases, unlock, run_id, granted: True):
            s = run(self.root, run_id="x", cases=[HOLDOUT], runs_dir=self.runs)
        self.assertEqual(s.rows, 1)
        self.assertFalse(self.log.exists())


if __name__ == "__main__":
    unittest.main()
