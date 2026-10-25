"""The runtime reads no stored output file (developer ruling T120, WP1); the approved files live with
the evaluation record.

* Nothing under ``code/`` outside ``code/evaluation/`` holds an approved output or names the
  approved-output record: the pipeline compares model-derived changes with model-free rows it
  computes itself.
* The workspace record ``notes/approved_output.json`` (read by ``code/evaluation/freeze_check.py`` and
  ``code/evaluation/regression_check.py``) names the root ``output.csv`` (a00ba71a..., T120) and the
  per-split files under ``notes/approved/``, each with its recorded sha256. ``notes/`` is not shipped,
  so those tests skip without it.
"""

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from evaluation.regression_check import load_approved

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / "code" / "deletion_audit"
RECORD = ROOT / "notes" / "approved_output.json"
TEST_SHA = "cf2a90b070db785456b2cb26398add0eba95a69ae8a763eb838a367f135751fc"
DEV_SHA = "641dbc8d921186efbf92514b2c71fe25a3b133d412515dd952da19f8ac85b15c"
SHIPPED_SHA = "a00ba71a756736cc09a3ef5119b5575d871a2db2c9482d9829333181d5676967"  # T120: the root output.csv


class TestRuntimeReadsNoStoredOutput(unittest.TestCase):
    def test_no_approved_file_in_the_runtime_tree(self) -> None:
        self.assertFalse((ROOT / "code" / "approved").exists())
        self.assertEqual(sorted(p.name for p in PACKAGE.rglob("*.csv")), [])

    def test_runtime_source_names_no_approved_record_or_file(self) -> None:
        for p in sorted(PACKAGE.rglob("*.py")):
            text = p.read_text(encoding="utf-8")
            for needle in ("approved_output", "code/approved", "APPROVED_OUTPUT_RECORD", "load_baseline"):
                self.assertNotIn(needle, text, f"{p.relative_to(ROOT)} names {needle}")


class TestWorkspaceRecord(unittest.TestCase):
    def setUp(self) -> None:
        if not RECORD.is_file():
            self.skipTest("notes/ is not shipped (code.zip holds README.md and code/ only)")
        self.body = json.loads(RECORD.read_text(encoding="utf-8"))

    def test_approved_output_is_the_shipped_root_output(self) -> None:
        """T120: the approved output is the root output.csv."""
        self.assertEqual((self.body["approved_output"]["path"], self.body["approved_output"]["sha256"]),
                         ("output.csv", SHIPPED_SHA))

    def test_each_split_file_loads_with_its_recorded_sha256(self) -> None:
        got = {}
        for split, entry in sorted(self.body["approved_outputs"].items()):
            self.assertEqual(Path(entry["path"]).parts[:2], ("notes", "approved"), entry["path"])
            a = load_approved(RECORD, ROOT, f"approved_outputs.{split}", entry)
            self.assertEqual(hashlib.sha256((ROOT / a.path).read_bytes()).hexdigest(), a.sha256)
            got[split] = (a.sha256, len(a.rows))
        self.assertEqual(got, {"dev": (DEV_SHA, 22), "test": (TEST_SHA, 518)})

    def test_freeze_acceptance_names_a_listed_file(self) -> None:
        """T118 step 4: the freeze check finds the cf2a90b0 file through the record's entries."""
        want = self.body["freeze_accepts_failed_closed_identical_to"]["sha256"]
        self.assertIn(want, [e["sha256"] for e in self.body["approved_outputs"].values()])


if __name__ == "__main__":
    unittest.main()
