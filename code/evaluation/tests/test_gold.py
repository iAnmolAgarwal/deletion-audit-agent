"""Holdout lock: the default load holds no holdout ID, and no holdout row reaches json.loads."""
from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from evaluation import gold as gold_mod
from evaluation.gold import UNLOCK_PHRASE, HoldoutLockedError, load_gold, load_requests
from evaluation.outputs import read_output
from evaluation.paths import SAMPLE_OUTPUT
from evaluation.split import DEV_IDS, HOLDOUT_IDS

SENTINEL = "HOLDOUT-SENTINEL {{{ not json"


def write_fixture(path: Path, *, holdout_raw: str = SENTINEL) -> None:
    """22 DEV rows with valid JSON, 10 holdout rows whose steps_json is invalid JSON."""
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["case_id", "deletion_status", "steps_json"])
        for cid in sorted(DEV_IDS | HOLDOUT_IDS):
            if cid in HOLDOUT_IDS:
                w.writerow([cid, "COMPLETE", f"{holdout_raw} {cid}"])
            else:
                w.writerow([cid, "NOT_APPLICABLE", "[]"])


class TestDevGoldLoader(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.fixture = Path(self.tmp.name) / "gold.csv"
        write_fixture(self.fixture)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_fixture_with_invalid_holdout_json_loads(self) -> None:
        g = load_gold(self.fixture)
        self.assertEqual(set(g), set(DEV_IDS))

    def test_no_holdout_row_reaches_json_parser(self) -> None:
        seen: list[str] = []
        real = json.loads

        def spy(s, *a, **k):  # type: ignore[no-untyped-def]
            seen.append(s)
            return real(s, *a, **k)

        with mock.patch.object(gold_mod.json, "loads", side_effect=spy):
            load_gold(self.fixture)
        self.assertEqual(len(seen), len(DEV_IDS))
        self.assertFalse([s for s in seen if "SENTINEL" in s])

    def test_real_default_load_has_no_holdout_id(self) -> None:
        g = load_gold()
        self.assertEqual(set(g), set(DEV_IDS))
        self.assertFalse(set(g) & HOLDOUT_IDS)

    def test_unknown_case_id_rejected(self) -> None:
        with self.fixture.open("a", encoding="utf-8") as f:
            f.write("case_99,COMPLETE,[]\n")
        with self.assertRaises(ValueError):
            load_gold(self.fixture)

    def test_incomplete_dev_rejected(self) -> None:
        lines = self.fixture.read_text(encoding="utf-8").splitlines(keepends=True)
        self.fixture.write_text("".join(l for l in lines if not l.startswith("case_01,")), encoding="utf-8")
        with self.assertRaises(ValueError):
            load_gold(self.fixture)


class TestHoldoutLocked(unittest.TestCase):
    """The holdout path refuses before any I/O. The unlocked path is never exercised."""

    MISSING = Path("/nonexistent/never-opened.csv")

    def test_refuses_without_phrase(self) -> None:
        with self.assertRaises(HoldoutLockedError):
            load_gold(self.MISSING, holdout=True)

    def test_refuses_wrong_phrase(self) -> None:
        for phrase in ("", "holdout evaluation run", "HOLDOUT EVALUATION RUN ", "yes"):
            with self.assertRaises(HoldoutLockedError):
                load_gold(self.MISSING, holdout=True, unlock_phrase=phrase)

    def test_refusal_happens_before_open(self) -> None:
        with mock.patch.object(Path, "open", side_effect=AssertionError("opened")):
            with self.assertRaises(HoldoutLockedError):
                load_gold(SAMPLE_OUTPUT, holdout=True)

    def test_requests_holdout_locked(self) -> None:
        with self.assertRaises(HoldoutLockedError):
            load_requests(include_holdout=True)

    def test_phrase_constant(self) -> None:
        self.assertEqual(UNLOCK_PHRASE, "HOLDOUT EVALUATION RUN")


class TestRequestsAndGuard(unittest.TestCase):
    def test_default_requests_drop_holdout(self) -> None:
        r = load_requests()
        self.assertEqual(set(r), set(DEV_IDS))

    def test_read_output_refuses_gold_file(self) -> None:
        with self.assertRaises(PermissionError):
            read_output(SAMPLE_OUTPUT)


if __name__ == "__main__":
    unittest.main()
