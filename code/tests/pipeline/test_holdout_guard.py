"""``pipeline.run``'s own holdout guard (``../CLAUDE.md`` section 4; G5 verifier note).

Synthetic inputs only (T48): no gold file exists here and none is read. The holdout IDs come from
``code/evaluation/split.py`` at run time, so no case ID is written in this source (T71 Q8).
"""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from deletion_audit.__main__ import main
from deletion_audit.engine import build_context
from deletion_audit.pipeline import HoldoutRefused, holdout_ids, run
from evaluation.split import HOLDOUT_IDS

from ..engine_fixtures import Dataset, Person, case, kv_line, temp_dir

ADA, BO = "ada@example.test", "bo@example.test"
C1 = case(9501)
HOLDOUT = sorted(HOLDOUT_IDS)[0]


def dataset(test_holdout: bool = False) -> Dataset:
    """Ada (a test case with a live account) and Bo, whose request sits in the sample file under a
    holdout ID; optionally the test file names that holdout ID too."""
    d = Dataset(people=[Person("user_9001", ADA), Person("user_9002", BO)])
    d.add_request(C1, ADA)
    d.add_request(HOLDOUT, BO, sample=True)
    if test_holdout:
        d.add_request(HOLDOUT, BO)
    d.add_file(
        "ev_1",
        "logs/a.log",
        "2026-05-03T00:00:00Z",
        kv_line(
            "2026-05-02T10:00:00Z",
            level="INFO",
            service="account_service",
            trace_id="t1",
            event="profile_lookup_completed",
            resource_id="account_1",
            http_status="200",
            lookup_key=ADA,
        ),
    )
    return d


class Guard(unittest.TestCase):
    """Refused in ``pipeline.run`` itself, for an explicit list and for a resolved ``"test"`` run."""

    def test_guard_list_is_the_split(self) -> None:
        self.assertEqual(holdout_ids(), HOLDOUT_IDS)
        self.assertTrue(HOLDOUT.startswith("case_"))

    def test_explicit_holdout_case_refused_before_any_read(self) -> None:
        with temp_dir() as runs:
            for cases in ([HOLDOUT], [C1, HOLDOUT]):
                with self.subTest(cases=len(cases)):
                    with self.assertRaises(HoldoutRefused) as cm:
                        run(Path("no-such-dataset"), run_id="h", cases=cases, runs_dir=Path(runs))
                    self.assertNotIn(HOLDOUT, str(cm.exception))  # the message names no ID
                    self.assertFalse((Path(runs) / "h").exists())  # nothing written

    def test_test_run_naming_a_holdout_case_refused(self) -> None:
        with temp_dir() as tmp, temp_dir() as runs:
            root = dataset(test_holdout=True).write(Path(tmp))
            with self.assertRaises(HoldoutRefused):
                run(root, run_id="h", cases="test", runs_dir=Path(runs))
            self.assertFalse((Path(runs) / "h").exists())

    def test_holdout_inputs_still_join_the_global_stages(self) -> None:
        """T32/T47: the sample file's holdout request is loaded and competes; only its row is refused."""
        with temp_dir() as tmp, temp_dir() as runs:
            root = dataset().write(Path(tmp))
            self.assertIn(HOLDOUT, {r.case_id for r in build_context(root).requests})
            s = run(root, run_id="ok", cases="test", runs_dir=Path(runs))
            self.assertEqual(s.rows, 1)
            self.assertNotIn(HOLDOUT, s.output_path.read_text())
            s2 = run(root, run_id="ok2", cases=[C1], runs_dir=Path(runs))
            self.assertEqual(s2.output_sha256, s.output_sha256)

    def test_cli_reports_the_refusal_with_exit_code_2(self) -> None:
        err = io.StringIO()
        with temp_dir() as tmp:
            root = dataset().write(Path(tmp))
            with redirect_stderr(err):
                code = main(["--run-id", "h", "--cases", f"{C1},{HOLDOUT}", "--dataset", str(root)])
        self.assertEqual(code, 2)
        self.assertIn("refused", err.getvalue())


if __name__ == "__main__":
    unittest.main()
