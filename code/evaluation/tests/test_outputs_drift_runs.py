"""output.csv round trip, drift flags, run flips and the NUMBERS.md block replacement."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from evaluation.drift import drift_table
from evaluation.numbers_md import BEGIN, END, regenerate
from evaluation.outputs import read_output, write_output
from evaluation.runs import canonical_hash, flips

from .fixtures import complete_example, gold, incomplete_example, row


class TestOutputs(unittest.TestCase):
    def test_round_trip_and_lf(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "o.csv"
            write_output(p, [("case_01", "COMPLETE", complete_example()), ("case_02", "NOT_APPLICABLE", [])])
            data = p.read_bytes()
            self.assertNotIn(b"\r\n", data)
            self.assertIn(b'case_02,NOT_APPLICABLE,[]\n', data)
            out = read_output(p)
            self.assertEqual(out.issues, [])
            self.assertEqual(out.rows["case_01"].steps, complete_example())
            self.assertEqual(out.order, ["case_01", "case_02"])

    def test_bad_rows_reported(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "o.csv"
            p.write_text("case_id,deletion_status,steps_json\r\ncase_01,COMPLETE,[oops\r\ncase_01,COMPLETE,[]\r\n",
                         encoding="utf-8")
            out = read_output(p)
            self.assertIsNone(out.rows["case_01"].steps)
            self.assertTrue(any("CRLF" in i for i in out.issues))
            self.assertTrue(any("duplicate" in i for i in out.issues))


class TestDrift(unittest.TestCase):
    def test_flags_large_gap_only(self) -> None:
        g = {f"g{i}": gold(f"g{i}", "INCOMPLETE", incomplete_example()) for i in range(4)}
        p = {"p0": row("p0", "COMPLETE", complete_example()), "p1": row("p1", "INCOMPLETE", incomplete_example()),
             "p2": row("p2", "INCOMPLETE", incomplete_example()), "p3": row("p3", "INCOMPLETE", incomplete_example())}
        t = {(r["dimension"], r["label"]): r for r in drift_table(p, g)}
        self.assertEqual(t[("status", "COMPLETE")]["gap_pts"], 25.0)
        self.assertTrue(t[("status", "COMPLETE")]["flag"])
        same = drift_table({k: row(k, "INCOMPLETE", incomplete_example()) for k in p}, g)
        self.assertFalse(any(r["flag"] for r in same))


class TestRuns(unittest.TestCase):
    def test_flips(self) -> None:
        prev = [{"case_id": "a", "status_ok": True, "row_exact": False, "order_exact": False,
                 "citation_set_exact": True}]
        cur = [{"case_id": "a", "status_ok": True, "row_exact": True, "order_exact": False, "citation_set_exact": True},
               {"case_id": "b", "status_ok": True, "row_exact": True, "order_exact": True, "citation_set_exact": True}]
        f = flips(prev, cur)
        self.assertIn({"case_id": "a", "metric": "row_exact", "prev": False, "now": True}, f)
        self.assertEqual(sum(1 for x in f if x["case_id"] == "b"), 1)

    def test_canonical_hash_ignores_key_order(self) -> None:
        self.assertEqual(canonical_hash({"a": 1, "b": [1, 2]}), canonical_hash({"b": [1, 2], "a": 1}))

    def test_numbers_block_replaced_only(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            md, runs_dir = Path(t) / "N.md", Path(t) / "runs"
            runs_dir.mkdir()
            md.write_text(f"hand text above\n{BEGIN}\nOLD\n{END}\nhand text below\n", encoding="utf-8")
            regenerate(md, runs_dir)
            text = md.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("hand text above\n"))
            self.assertTrue(text.endswith("hand text below\n"))
            self.assertNotIn("OLD", text)


if __name__ == "__main__":
    unittest.main()
