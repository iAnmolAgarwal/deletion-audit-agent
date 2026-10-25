"""The committed approved baselines (developer ruling T117 B2, with main's packaging correction).

* The gate's record and both files it names live under ``code/approved/``, inside the tree code.zip
  ships, so a fresh unzip finds them (``runs/`` is never shipped).
* Each file's sha256 equals the record's: the test file is cf2a90b0... (T101), the DEV file
  641dbc8d... (T117 B2), so no approved byte changed in the move.
* ``notes/approved_output.json``, which the freeze check reads, is byte-identical to the gate's
  record, so the two can never name different approved files.
"""

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from deletion_audit.agent.regression import load_baseline
from deletion_audit.config import APPROVED_OUTPUT_RECORD

ROOT = Path(__file__).resolve().parents[3]
RECORD = ROOT / APPROVED_OUTPUT_RECORD
TEST_SHA = "cf2a90b070db785456b2cb26398add0eba95a69ae8a763eb838a367f135751fc"
DEV_SHA = "641dbc8d921186efbf92514b2c71fe25a3b133d412515dd952da19f8ac85b15c"


class TestApprovedBaselines(unittest.TestCase):
    def test_record_and_files_live_in_the_shipped_code_tree(self) -> None:
        self.assertEqual(Path(APPROVED_OUTPUT_RECORD).parts[0], "code")
        body = json.loads(RECORD.read_text(encoding="utf-8"))
        paths = [body["approved_output"]["path"], *(e["path"] for e in body["approved_outputs"].values())]
        for rel in paths:
            self.assertFalse(Path(rel).is_absolute(), rel)
            self.assertEqual(Path(rel).parts[0], "code", rel)
            self.assertTrue((ROOT / rel).is_file(), rel)

    def test_each_split_loads_with_its_recorded_sha256(self) -> None:
        test = load_baseline(RECORD, ROOT, split="test")
        dev = load_baseline(RECORD, ROOT, split="dev")
        self.assertEqual((test.sha256, len(test.rows)), (TEST_SHA, 518))
        self.assertEqual((dev.sha256, len(dev.rows)), (DEV_SHA, 22))
        self.assertEqual(load_baseline(RECORD, ROOT).sha256, TEST_SHA)  # the legacy key names the test file
        for b in (test, dev):
            self.assertEqual(hashlib.sha256((ROOT / b.path).read_bytes()).hexdigest(), b.sha256)

    def test_freeze_check_record_is_byte_identical(self) -> None:
        if not (ROOT / "notes").is_dir():
            self.skipTest("notes/ is not shipped (code.zip holds README.md and code/ only)")
        self.assertEqual((ROOT / "notes" / "approved_output.json").read_bytes(), RECORD.read_bytes())


if __name__ == "__main__":
    unittest.main()
