"""M1: list and dict values in any step field score as wrong and are reported, never crash.
M2: both status readings for an unparseable row are computed."""
from __future__ import annotations

import json
import unittest

from evaluation.coherence import EvidenceIndex, check_file, check_row, parse_time
from evaluation.contract import STEP_KEYS, hashable, step_key
from evaluation.drift import drift_table
from evaluation.outputs import OUTPUT_HEADER, OutputFile
from evaluation.scorer import aggregate, score_case, score_predictions

from .fixtures import gold, incomplete_example, row

AUDIT = "2026-09-15T12:00:00Z"
EV = EvidenceIndex(files={"evidence_01": parse_time("2026-09-01T00:00:00Z")}, activities={}, audits={})
BAD_VALUES = ([1, 2], ["account_service"], {"a": 1}, {"x": [1, {"y": 2}]}, [])


def poisoned(field: str, value: object) -> list[dict]:
    steps = [dict(s) for s in incomplete_example()]
    for s in steps:
        s[field] = value
    return steps


class TestHashable(unittest.TestCase):
    def test_scalars_unchanged_and_containers_tagged(self) -> None:
        for v in ("a", 1, 1.5, True, None):
            self.assertEqual(hashable(v), v)
        self.assertEqual(hashable([1]), ("<list>", "[1]"))
        self.assertEqual(hashable({"b": 1, "a": 2}), ("<dict>", '{"a":2,"b":1}'))
        self.assertNotEqual(hashable(["x"]), "x")
        hash(step_key({"phase": [1], "operation": {"a": 1}, "system_id": [], "resource_id": {}}))


class TestScorerNeverCrashes(unittest.TestCase):
    def test_every_field_every_container(self) -> None:
        g = gold("case_x", "INCOMPLETE", incomplete_example())
        for field in STEP_KEYS:
            for value in BAD_VALUES:
                with self.subTest(field=field, value=value):
                    c = score_case(row("case_x", "INCOMPLETE", poisoned(field, value)), g)
                    self.assertFalse(c["row_exact"])
                    self.assertFalse(c["steps_exact"])
                    if field in ("phase", "operation", "system_id", "resource_id"):
                        self.assertEqual(c["step_tp"], 0)
                    else:
                        self.assertEqual(c["step_tp"], 4)
                        self.assertEqual(c["field_eq"][field], 0)
                    json.dumps(c)  # score.json must still serialise
                    agg = aggregate([c])
                    self.assertEqual(agg["published"]["row_exact"]["n"], 0)

    def test_score_predictions_and_drift(self) -> None:
        g = {"case_x": gold("case_x", "INCOMPLETE", incomplete_example())}
        preds = {"case_x": row("case_x", "INCOMPLETE", poisoned("resource_id", {"a": [1]}))}
        res = score_predictions(preds, g)
        self.assertEqual(res["aggregate"]["published"]["step"]["tp"], 0)
        drift_table(preds, g)


class TestCoherenceReportsH04(unittest.TestCase):
    def test_every_field_every_container(self) -> None:
        for field in STEP_KEYS:
            for value in BAD_VALUES:
                with self.subTest(field=field, value=value):
                    r = row("case_x", "INCOMPLETE", poisoned(field, value))
                    v = check_row(r, audit_at=AUDIT, evidence=EV)
                    self.assertIn("H04", {x.rule for x in v if x.severity == "hard"})
                    out = OutputFile(rows={"case_x": r}, order=["case_x"], header=list(OUTPUT_HEADER))
                    check_file(out, audit_at={"case_x": AUDIT}, evidence=EV, expected_ids=["case_x"])


class TestStatusReadingsM2(unittest.TestCase):
    def test_unparseable_right_status(self) -> None:
        g = gold("case_e", "NOT_APPLICABLE", [])
        c = score_case(row("case_e", "NOT_APPLICABLE", None, raw="[{broken"), g)
        self.assertTrue(c["status_ok"])                       # reading (a): credited
        self.assertFalse(c["status_ok_unparseable_wrong"])    # reading (c): wrong
        ok = score_case(row("case_f", "NOT_APPLICABLE", []), gold("case_f", "NOT_APPLICABLE", []))
        missing = score_case(None, gold("case_g", "NOT_APPLICABLE", []))
        p = aggregate([c, ok, missing])["published"]
        self.assertEqual((p["status_accuracy"]["n"], p["status_accuracy"]["of"]), (2, 3))
        self.assertEqual((p["status_accuracy_unparseable_wrong"]["n"], p["status_accuracy_unparseable_wrong"]["of"]), (1, 3))


if __name__ == "__main__":
    unittest.main()
