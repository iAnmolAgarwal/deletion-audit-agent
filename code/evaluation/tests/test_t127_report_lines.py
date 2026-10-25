"""Generated report lines added in T127: the holdout replicate note (A7), the package-diff check (B6)
and the per-test-request usage line (B5)."""
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any

from evaluation import evaluation_report as er
from evaluation import usage_report as ur


def _write_run(d: Path, cases: list[dict[str, Any]], calls: list[dict[str, Any]], changed: int) -> None:
    d.mkdir(parents=True)
    (d / "cases.jsonl").write_text("".join(json.dumps(c) + "\n" for c in cases), encoding="utf-8")
    (d / "calls.jsonl").write_text("".join(json.dumps(c) + "\n" for c in calls), encoding="utf-8")
    (d / "regression_vs_engine.json").write_text(json.dumps({"changed_rows": changed, "rows_compared": len(cases)}),
                                                 encoding="utf-8")


class ReplicateNotes(unittest.TestCase):
    def test_missing_replicate_is_counted_and_not_called_a_disagreement(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            d = Path(t) / "holdout-x"
            cases = [{"case_id": "c1", "agent": {"turn1_replicates": ["DELETION_REQUEST", None],
                                                 "flags": ["TURN1_REPLICATES_DISAGREE"]}},
                     {"case_id": "c2", "agent": {"turn1_replicates": ["DELETION_REQUEST", "DELETION_REQUEST"],
                                                 "flags": []}}]
            calls = [{"event": "replay_miss", "outcome": "give_up"}, {"event": "cache_hit", "outcome": "ok"}]
            _write_run(d, cases, calls, 0)
            text = "\n".join(er.replicate_notes(d))
        self.assertIn("1 of 2 cases had no second turn-1 intent reading", text)
        self.assertIn("(1 `replay_miss` events", text)
        self.assertIn("flags 1 cases `TURN1_REPLICATES_DISAGREE`", text)
        self.assertIn("0 cases have two different labels", text)
        self.assertIn("0 of 2 rows differ", text)

    def test_real_disagreement_is_counted(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            d = Path(t) / "r"
            _write_run(d, [{"case_id": "c1", "agent": {"turn1_replicates": ["DELETION_REQUEST", "NOT_DELETION"],
                                                       "flags": ["TURN1_REPLICATES_DISAGREE"]}}], [], 0)
            self.assertIn("1 cases have two different labels", "\n".join(er.replicate_notes(d)))

    def test_unreadable_artifacts_give_an_explicit_line(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            lines = er.replicate_notes(Path(t) / "absent")
        self.assertEqual(len(lines), 1)
        self.assertIn("not reported", lines[0])


class PackageDiffers(unittest.TestCase):
    def test_empty_commit_is_unknown(self) -> None:
        self.assertIsNone(er.package_differs(Path("."), ""))

    def test_identical_and_changed_package(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            repo = Path(t)
            def git(*a: str) -> str:
                return subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True,
                                      check=True).stdout.strip()
            git("init", "-q")
            git("config", "user.email", "t@example.invalid")
            git("config", "user.name", "t")
            (repo / "code" / "deletion_audit").mkdir(parents=True)
            (repo / "code" / "deletion_audit" / "a.py").write_text("x = 1\n")
            git("add", "-A")
            git("commit", "-qm", "one")
            first = git("rev-parse", "HEAD")
            (repo / "README.md").write_text("doc\n")
            git("add", "-A")
            git("commit", "-qm", "docs")
            self.assertIs(er.package_differs(repo, first), False)
            (repo / "code" / "deletion_audit" / "a.py").write_text("x = 2\n")
            git("commit", "-qam", "code")
            self.assertIs(er.package_differs(repo, first), True)
            self.assertIsNone(er.package_differs(repo, "0" * 40))


class PerTestRequest(unittest.TestCase):
    def usage(self, final: Any) -> dict[str, Any]:
        return {"a_replies_used": {"total": {"total_tokens": 1000, "cost_settled_usd": 2.0}}, "final": final}

    def test_divides_the_part_a_totals(self) -> None:
        text = ur._per_test_request(self.usage({"test_requests": 4}))
        self.assertIn("250.0 total tokens (1000 / 4)", text)
        self.assertIn("$0.500000", text)

    def test_no_final_run_is_not_applicable(self) -> None:
        for final in (None, {"test_requests": 0}, {"test_requests": True}):
            self.assertIn("n/a", ur._per_test_request(self.usage(final)))


if __name__ == "__main__":
    unittest.main()
