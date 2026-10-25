"""regression_check: a finished run against the approved file for its case set; every differing row is
reported with its cause, and the check passes only when no row differs. Synthetic rows and made-up
case IDs only; every file is in a temporary directory."""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import random
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from evaluation import regression_check as rc
from evaluation.regression_check import CheckRefused, parse_rows, regression_check

HEADER = "case_id,deletion_status,steps_json\n"
ROWS = {"case_902": ("COMPLETE", '[{"step_no":1}]'), "case_910": ("NOT_APPLICABLE", "[]"),
        "case_903": ("INCOMPLETE", '[{"step_no":1},{"step_no":2}]')}


def render(rows: dict[str, tuple[str, str]]) -> bytes:
    """output.csv bytes (numeric case order, CSV quoting as the writer does)."""
    import csv

    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["case_id", "deletion_status", "steps_json"])
    for cid in sorted(rows, key=lambda c: int(c.rpartition("_")[2])):
        w.writerow([cid, *rows[cid]])
    return buf.getvalue().encode("utf-8")


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="regcheck-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.runs = self.tmp / "runs"

    def approve(self, rows: dict[str, tuple[str, str]], *, name: str = "approved.csv",
                extra: dict[str, Any] | None = None, sha: str | None = None) -> Path:
        data = render(rows)
        (self.tmp / name).write_bytes(data)
        body: dict[str, Any] = {"approved_output": {"path": name, "sha256": sha or hashlib.sha256(data).hexdigest(),
                                                    "run_id": "synthetic"}}
        body.update(extra or {})
        rec = self.tmp / "record.json"
        rec.write_text(json.dumps(body), encoding="utf-8")
        return rec

    def run_dir(self, rows: dict[str, tuple[str, str]], changes: list[dict[str, Any]] | None = None,
                run_id: str = "r1") -> str:
        d = self.runs / run_id
        d.mkdir(parents=True)
        (d / "output.csv").write_bytes(render(rows))
        if changes is not None:
            (d / rc.CHANGES_FILE).write_text(json.dumps({"rows": changes}), encoding="utf-8")
        return run_id

    def check(self, run_id: str, record: Path) -> rc.CheckResult:
        return regression_check(run_id, runs_root=self.runs, approved_record=record, repo_root=self.tmp)


class TestPassAndDiffer(Base):
    def test_identical_run_passes(self) -> None:
        res = self.check(self.run_dir(ROWS, []), self.approve(ROWS))
        self.assertTrue(res.passed)
        self.assertEqual((res.rows_compared, res.differing, res.approved["entry"]), (3, [], "approved_output"))

    def test_every_differing_row_is_reported_with_its_cause(self) -> None:
        mine = dict(ROWS)
        mine["case_903"] = ("NOT_APPLICABLE", "[]")  # judged by the run: an allowed intent change
        mine["case_902"] = ("COMPLETE", '[{"step_no":1,"x":1}]')  # steps text only, not judged: engine
        changes = [{"case_id": "case_903", "cause": "intent", "verdict": "allowed"}]
        res = self.check(self.run_dir(mine, changes), self.approve(ROWS))
        self.assertFalse(res.passed)
        got = [(r["case_id"], r["cause"], r["status_differs"]) for r in res.differing]
        self.assertEqual(got, [("case_902", "engine", False), ("case_903", "intent", True)])
        self.assertEqual(res.differing[1]["verdict"], "allowed")

    def test_an_unreadable_change_report_leaves_causes_not_recorded(self) -> None:
        """A failed read is never "nothing found": the cause is not recorded, never ``engine``."""
        mine = dict(ROWS, case_910=("COMPLETE", "[]"))
        res = self.check(self.run_dir(mine, None), self.approve(ROWS))
        self.assertEqual([r["cause"] for r in res.differing], [rc.NOT_RECORDED])
        self.assertTrue(res.errors)
        self.assertFalse(res.passed)

    def test_random_runs_report_exactly_the_differing_rows(self) -> None:
        """Seeded property test: the reported cases are exactly those whose status or steps text differs,
        in numeric case order, and the check passes exactly when there is none."""
        choices = (("COMPLETE", "[]"), ("INCOMPLETE", '[{"step_no":1}]'), ("NOT_APPLICABLE", "[]"))
        for seed in range(60):
            rng = random.Random(seed)
            ids = [f"case_{9000 + i}" for i in rng.sample(range(40), 6)]
            base = {c: rng.choice(choices) for c in ids}
            mine = {c: rng.choice(choices) for c in ids}
            rec = self.approve(base, name=f"a{seed}.csv")
            res = self.check(self.run_dir(mine, [], run_id=f"s{seed}"), rec)
            want = sorted((c for c in ids if base[c] != mine[c]), key=lambda c: int(c[5:]))
            self.assertEqual([r["case_id"] for r in res.differing], want, seed)
            self.assertEqual(res.passed, not want, seed)


class TestRefusals(Base):
    def test_wrong_sha256_is_refused(self) -> None:
        res = self.check(self.run_dir(ROWS, []), self.approve(ROWS, sha="0" * 64))
        self.assertIsNotNone(res.refusal)
        self.assertFalse(res.passed)

    def test_no_entry_with_the_run_s_case_set_is_refused(self) -> None:
        res = self.check(self.run_dir({"case_902": ROWS["case_902"]}, []), self.approve(ROWS))
        self.assertIn("no approved file has the run's case set", str(res.refusal))
        self.assertFalse(res.passed)

    def test_unreadable_record_or_run_is_refused(self) -> None:
        bad = self.tmp / "bad.json"
        bad.write_text("not json", encoding="utf-8")
        self.assertIsNotNone(self.check(self.run_dir(ROWS, []), bad).refusal)
        self.assertIsNotNone(self.check("missing", self.approve(ROWS)).refusal)

    def test_a_split_entry_is_used_when_its_case_set_matches(self) -> None:
        """T117 B2: one approved file per split; the entry whose case set equals the run's is used."""
        dev = {"case_911": ("COMPLETE", "[]")}
        data = render(dev)
        (self.tmp / "dev.csv").write_bytes(data)
        extra = {"approved_outputs": {"dev": {"path": "dev.csv", "sha256": hashlib.sha256(data).hexdigest()}}}
        res = self.check(self.run_dir(dev, []), self.approve(ROWS, extra=extra))
        self.assertTrue(res.passed)
        self.assertEqual(res.approved["entry"], "approved_outputs.dev")

    def test_bad_output_rows_are_refused(self) -> None:
        bad = (b"a,b\n", (HEADER + "case_1,COMPLETE\n").encode(), (HEADER + "case_1,A,[]\ncase_1,A,[]\n").encode())
        for data in bad:
            with self.assertRaises(CheckRefused):
                parse_rows(data)


class TestCli(Base):
    def test_exit_codes(self) -> None:
        rec = self.approve(ROWS)
        self.run_dir(ROWS, [], run_id="same")
        self.run_dir(dict(ROWS, case_910=("COMPLETE", "[]")), [], run_id="diff")
        for name, value in (("RUNS", self.runs), ("REPO_ROOT", self.tmp)):
            patcher = mock.patch.object(rc, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        codes = []
        for rid, record in (("same", rec), ("diff", rec), ("same", self.tmp / "nowhere.json")):
            with contextlib.redirect_stdout(io.StringIO()):
                codes.append(rc.main(["--run-id", rid, "--record", str(record)]))
        self.assertEqual(codes, [rc.EXIT_PASS, rc.EXIT_DIFFERS, rc.EXIT_REFUSED])


if __name__ == "__main__":
    unittest.main()
