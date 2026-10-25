"""B1: ``read_output`` refuses the gold file by identity, proven on SYNTHETIC gold only.

Developer rule (T47): lock bypasses are proven with synthetic files. Each test writes a fake
gold file into a temp directory and points ``paths.SAMPLE_OUTPUT`` at it; the real
``dataset/sample_output.csv`` is never opened here.
"""
from __future__ import annotations

import csv
import io
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from evaluation import gold as gold_mod
from evaluation import paths
from evaluation.gold import UNLOCK_PHRASE, HoldoutLockedError
from evaluation.outputs import is_gold_file, read_output
from evaluation.paths import SAMPLE_OUTPUT as REAL_SAMPLE_OUTPUT  # bound at import, before any patch

from .test_gold import write_fixture


class TestIdentityGuard(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.gold = self.dir / "sample_output.csv"
        write_fixture(self.gold)  # synthetic: 22 DEV rows, 10 holdout rows of invalid JSON
        self.patch = mock.patch.object(paths, "SAMPLE_OUTPUT", self.gold)
        self.patch.start()
        self.real_gold = Path(REAL_SAMPLE_OUTPUT)

    def tearDown(self) -> None:
        self.patch.stop()
        self.tmp.cleanup()

    def assertRefused(self, p: Path) -> None:
        self.assertTrue(is_gold_file(p))
        with mock.patch.object(csv, "reader", side_effect=AssertionError("gold rows were parsed")):  # outputs' csv
            with self.assertRaises(HoldoutLockedError):
                read_output(p)

    def test_patched_path_is_synthetic(self) -> None:
        self.assertNotEqual(paths.SAMPLE_OUTPUT.resolve(), self.real_gold.resolve())

    def test_same_path_refused(self) -> None:
        self.assertRefused(self.gold)

    def test_case_variant_path_refused(self) -> None:
        variant = self.dir / "Sample_OUTPUT.CSV"
        if not variant.exists():
            self.skipTest("temp filesystem is case-sensitive: a case-variant path names no file, so there is "
                          "nothing to bypass with")
        self.assertNotEqual(str(variant), str(self.gold))
        self.assertRefused(variant)

    def test_copy_refused(self) -> None:
        copy = self.dir / "elsewhere" / "pred.csv"
        copy.parent.mkdir()
        shutil.copyfile(self.gold, copy)
        self.assertFalse(os.path.samefile(copy, self.gold))
        self.assertRefused(copy)

    def test_hard_link_refused(self) -> None:
        link = self.dir / "hard_link.csv"
        os.link(self.gold, link)
        self.assertRefused(link)

    def test_symlink_refused(self) -> None:
        link = self.dir / "sym.csv"
        link.symlink_to(self.gold)
        self.assertRefused(link)

    def test_relative_dotdot_path_refused(self) -> None:
        sub = self.dir / "a"
        sub.mkdir()
        self.assertRefused(sub / ".." / "sample_output.csv")

    def test_other_file_same_size_accepted(self) -> None:
        other = self.dir / "pred.csv"
        data = bytearray(self.gold.read_bytes())
        data[-2] = ord("X") if data[-2] != ord("X") else ord("Y")  # one byte differs, same size
        other.write_bytes(bytes(data))
        self.assertFalse(is_gold_file(other))
        read_output(other)  # a prediction file reads normally

    def test_wrong_phrase_still_refused(self) -> None:
        with self.assertRaises(HoldoutLockedError):
            read_output(self.gold, unlock_phrase="yes")

    def test_unlock_reads_and_logs(self) -> None:
        log = self.dir / "HOLDOUT_ACCESS.log"
        with mock.patch.object(gold_mod, "HOLDOUT_ACCESS_LOG", log), \
                mock.patch("sys.stderr", new_callable=io.StringIO):
            out = read_output(self.gold, unlock_phrase=UNLOCK_PHRASE, run_id="synthetic-test")
        self.assertEqual(len(out.rows), 32)
        self.assertIn("gold via outputs.read_output", log.read_text(encoding="utf-8"))
        self.assertIn("synthetic-test", log.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
