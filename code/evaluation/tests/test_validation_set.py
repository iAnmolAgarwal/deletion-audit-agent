"""The validation-set section: every fixture with an expectation file, per arm, apart from DEV and holdout.

Synthetic fixtures and runs in a temporary world (``test_reports.World``); expected counts are written
out by hand in each test, never taken from the code under test.
"""
from __future__ import annotations

import json
from typing import Any

from evaluation import report_spec, validation_set
from evaluation.tests import run_dirs as rd
from evaluation.tests.test_reports import Base

GOOD = {"case_95001": ("COMPLETE", [rd.step("a_1")])}


class TestValidationSet(Base):
    def write_fixture(self, rel: str, rows: dict[str, tuple[str, list[dict[str, Any]]]] | None = None,
                      assertions: dict[str, Any] | None = None) -> None:
        d = self.w.fixtures / rel
        d.mkdir(parents=True)
        (d / "EXPECTED.md").write_text(f"# {rel}\n\n**Tests:** a made-up family.\n", encoding="utf-8")
        if rows is not None:
            rd.write_csv(d / "expected_output.csv", rows)
        if assertions is not None:
            (d / "expected_assertions.json").write_text(json.dumps({"cases": assertions}), encoding="utf-8")

    def setUp(self) -> None:
        super().setUp()
        self.write_fixture("FX1_rows", GOOD)
        self.write_fixture("red/RX2_two", {"case_95011": ("COMPLETE", [rd.step("a_11")]),
                                           "case_95012": ("COMPLETE", [rd.step("a_12")])})
        self.write_fixture("FX4_assert", assertions={"case_95041": {"deletion_status_never": ["COMPLETE"],
                                                                    "extra_key": 1}})
        self.write_fixture("FX5_notrun", {"case_95051": ("COMPLETE", [rd.step("a_51")])})
        (self.w.fixtures / "FX6_no_expectation").mkdir()
        (self.w.fixtures / "FX6_no_expectation" / "EXPECTED.md").write_text("# no files\n", encoding="utf-8")
        self.w.dev_run("dev-a")

    def runs(self) -> None:
        rd.write_run(self.w.runs, "v-fx1", GOOD, [rd.case("case_95001")],
                     calls=[{"event": "cache_hit"}, {"event": "replay_miss"}])
        # RX2: case_95011 exact, case_95012 has the wrong status -> 1 of 2, fixture fails
        rd.write_run(self.w.runs, "v-rx2", {"case_95011": ("COMPLETE", [rd.step("a_11")]),
                                            "case_95012": ("INCOMPLETE", [rd.step("a_12")])},
                     [rd.case("case_95011"), rd.case("case_95012")], calls=[{"event": "cache_hit"}])
        finding = [dict(rd.step("a_41", "REPORT_REMAINING_RECORD", "ev_1"), phase="FINDING", state="PRESENT")]
        rd.write_run(self.w.runs, "v-fx4", {"case_95041": ("INCOMPLETE", finding)}, [rd.case("case_95041")])

    def spec(self, validation: dict[str, dict[str, str]]) -> report_spec.ReportSpec:
        return self.w.spec(validation=validation)

    def test_discovers_every_folder_with_an_expectation_file(self) -> None:
        self.assertEqual(validation_set.discover(self.w.fixtures),
                         ["FX1_rows", "FX4_assert", "FX5_notrun", "red/RX2_two"])

    def test_pass_counts_per_fixture_and_arm(self) -> None:
        self.runs()
        b = self.build(self.spec({"tools_off": {"FX1_rows": "v-fx1", "red/RX2_two": "v-rx2",
                                                "FX4_assert": "v-fx4"}}))
        a = b["evaluation"]["validation"]["arms"]["tools_off"]
        per = {x["folder"]: x for x in a["fixtures"]}
        # FX1 pass (1/1), RX2 fail (1/2), FX4 assertions pass (1/1; extra_key not checked), FX5 not run
        self.assertEqual((per["FX1_rows"]["result"], per["FX1_rows"]["cases_passed"]), ("pass", 1))
        self.assertEqual((per["red/RX2_two"]["result"], per["red/RX2_two"]["failed"]), ("fail", ["case_95012"]))
        self.assertEqual((per["FX4_assert"]["result"], per["FX4_assert"]["not_checked"]), ("pass", ["extra_key"]))
        self.assertEqual(per["FX5_notrun"]["result"], "not run")
        self.assertEqual(per["FX1_rows"]["replay_misses"], 1)
        self.assertEqual((a["listed"], a["run"], a["scored"], a["fixtures_passed"], a["cases_scored"],
                          a["cases_passed"]), (4, 3, 3, 2, 4, 3))
        md = b["evaluation_md"]
        self.assertIn("## 5b. Validation set", md)
        self.assertIn("Fixtures passed 2/3 scored (4 listed, 3 run, 0 not scored); cases passed 3/4 scored", md)
        self.assertIn("| red/RX2_two | `v-rx2` | ok | 1/2 | case_95012 | 0 | 0 | fail |", md)
        # apart from DEV: no fixture case ID before the custom and validation sections, DEV still 22 cases
        self.assertIn("| FX4_assert | `v-fx4` | ok | 1/1 | none | n/a (no calls.jsonl) | 0 |", md)
        self.assertNotIn("case_950", md.split("## 5. Custom eval cases")[0])
        self.assertEqual(b["evaluation"]["dev"]["cases"], 22)
        self.assertEqual(b["failures"], [])

    def test_unchecked_run_is_listed_not_scored_and_does_not_refuse_the_build(self) -> None:
        # a wrong row, but the run's producer record has an evidence failure: never read, never scored
        rd.write_run(self.w.runs, "v-bad", {"case_95001": ("INCOMPLETE", [rd.step("a_1")])}, [rd.case("case_95001")],
                     producer={"evidence_failures": ["ev_1:ERROR"], "evidence_skipped": [], "output_sha256": "x"})
        b = self.build(self.spec({"A+": {"FX1_rows": "v-bad"}}))
        a = b["evaluation"]["validation"]["arms"]["A+"]
        fx1 = [x for x in a["fixtures"] if x["folder"] == "FX1_rows"][0]
        self.assertEqual((fx1["result"], fx1["producer_check"]), ("not scored", "refused"))
        self.assertNotIn("cases_passed", fx1)
        self.assertEqual((a["scored"], a["not_scored"], a["fixtures_passed"]), (0, 1, 0))
        self.assertIn("not scored: producer check refused: failure: ev_1:ERROR", b["evaluation_md"])

    def test_no_validation_runs_says_not_a_zero(self) -> None:
        b = self.build(self.w.spec())
        self.assertIn("nothing was scored. This is not a zero.", b["evaluation_md"])

    def test_spec_checks(self) -> None:
        with self.assertRaises(ValueError):
            self.build(self.spec({"A+": {"FX9_missing": "v-fx1"}}))
        with self.assertRaises(ValueError):
            self.build(self.spec({"B": {"FX1_rows": "v-fx1"}}))
        with self.assertRaises(ValueError):
            self.w.spec(validation={"A+": {"../escape": "v-fx1"}})
        s = self.spec({"A+": {"FX1_rows": "v-fx1"}})
        # validation runs are inputs but not scored runs: the section checks each run's producer itself
        self.assertIn("v-fx1", s.input_runs())
        self.assertNotIn("v-fx1", s.scored_runs())
