"""freeze_check: refuses on each blocking count separately, passes only when all are 0; T110 repeat stop."""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import shutil
import tempfile
import unittest
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest import mock

from evaluation import freeze_check as fc_mod
from evaluation import paths
from evaluation.freeze_check import COUNTS, freeze_check

from .run_dirs import ABSENT, agent, agree_image, case, image, intent, rreading, rrec, step, write_run

IDS = ["case_901", "case_902", "case_903"]
AGREE = agree_image()
DISAGREE = image("evidence_09", rreading(rrec("acct_1002", sync_enabled="yes")),
                 rreading(rrec("acct_1002", sync_enabled="no")), False, ["records[acct_1002].sync_enabled"],
                 [("account_service", "acct_1002", True, True)])
FAILED_IMG = image("evidence_12", rreading(rrec("acct_1003")), None, None, [], status="FAILED",
                   flags=["VISION_READ_FAILED"])
LABELS = image("evidence_14", rreading(rrec("CS-4821")), rreading(rrec("CS-4821")), True, [],
               [(None, "CS-4821", False, False)], flags=["VISION_ID_UNRECOGNIZED"])


def failed_agent(*keys: str) -> dict[str, Any]:
    """An agent block whose conversation failed (T109 (c)): status FAILED, its request keys listed."""
    return agent(status="FAILED", flags=["AGENT_CALL_FAILED"], replies=list(keys))


def call(key: str, outcome: str, error_class: str | None = None, input_tokens: int | None = None) -> dict[str, Any]:
    """One calls.jsonl event (the call log's field names)."""
    return {"run_id": "x", "key": key, "event": "send", "attempt": 1, "outcome": outcome, "from_cache": False,
            "error_class": error_class, "usage": {} if input_tokens is None else {"input_tokens": input_tokens}}


def rows() -> dict[str, tuple[str, list[dict[str, Any]]]]:
    return {c: ("COMPLETE", [step("account_" + c[5:])]) for c in IDS}


class TestFreezeCheck(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.runs = Path(self._tmp.name) / "runs"
        self.runs.mkdir()
        self.approved = Path(self._tmp.name) / "approved_output.json"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def check(self, cases: list[dict[str, Any]] | None = None, **kw: Any) -> dict[str, Any]:
        d = write_run(self.runs, "r1", rows(), cases or [case(c) for c in IDS], vision=kw.pop("vision", [AGREE]), **kw)
        self.approve(hashlib.sha256((d / "output.csv").read_bytes()).hexdigest())
        return freeze_check("r1", runs_root=self.runs, approved_record=self.approved)

    def approve(self, sha: str) -> None:
        """A synthetic approved-output record (T101) outside the runs directory."""
        self.approved.write_text(json.dumps({"approved_output": {"run_id": "r1", "sha256": sha,
                                                                 "path": "runs/r1/output.csv"}}), encoding="utf-8")

    @contextlib.contextmanager
    def patched(self) -> Iterator[None]:
        """The CLI pointed at the temporary runs and approved-output record."""
        with mock.patch.object(fc_mod, "RUNS", self.runs), mock.patch.object(fc_mod, "APPROVED_RECORD", self.approved):
            yield

    def failing(self, res: dict[str, Any]) -> list[str]:
        return [r.split(" ")[0].rstrip(":") for r in res["refusals"]]

    def test_passes_when_all_zero(self) -> None:
        res = self.check()
        self.assertTrue(res["passed"], res["refusals"])
        self.assertEqual(res["counts"], {k: 0 for k in COUNTS})

    def test_refuses_on_failed_closed_row_only(self) -> None:
        cases = [case(c) for c in IDS]
        cases[1] = case("case_902", row_state="FAILED_CLOSED", failed_closed="NOTHING_FOUND")
        res = self.check(cases)
        self.assertFalse(res["passed"])
        self.assertEqual(self.failing(res), ["failed_closed_rows"])
        self.assertEqual(res["counts"]["failed_closed_rows"], 1)
        self.assertEqual(res["ids"]["failed_closed_rows"], ["case_902"])

    def test_refuses_on_intent_failed_closed_flag_only(self) -> None:
        cases = [case(c) for c in IDS]
        cases[2] = case("case_903", flags=["INTENT_FAILED_CLOSED"])
        res = self.check(cases)
        self.assertEqual(self.failing(res), ["intent_failed_closed"])
        self.assertEqual(res["counts"]["intent_failed_closed"], 1)

    def test_intent_failed_budget_source_counts(self) -> None:
        cases = [case(c) for c in IDS]
        cases[0] = case("case_901", agent(intent=intent(None, "FAILED_BUDGET", agrees=None)))
        res = self.check(cases)
        self.assertEqual(self.failing(res), ["intent_failed_closed"])
        self.assertEqual(res["ids"]["intent_failed_closed"], ["case_901"])

    def test_refuses_on_evidence_skip_only(self) -> None:
        res = self.check(skips=["evidence_04:png-model-needed"])
        self.assertEqual(res["producer_check"], "ok")  # the allow-list passes the score check...
        self.assertEqual(self.failing(res), ["evidence_skips"])  # ...but not the freeze check
        self.assertEqual(res["counts"]["evidence_skips"], 1)

    def test_refuses_on_vision_disagreement_only(self) -> None:
        res = self.check(vision=[AGREE, DISAGREE])
        self.assertEqual(self.failing(res), ["vision_unresolved_disagreements"])
        self.assertEqual(res["ids"]["vision_unresolved_disagreements"], ["evidence_09"])

    def test_refuses_on_failed_vision_reading_with_its_reason(self) -> None:
        res = self.check(vision=[AGREE, FAILED_IMG])
        self.assertEqual(self.failing(res), ["vision_failed_readings"])
        self.assertEqual(res["ids"]["vision_failed_readings"], ["evidence_12"])
        self.assertIn("vision_failed_readings = 1 (e.g. evidence_12 [VISION_READ_FAILED])", res["refusals"])
        self.assertEqual(res["counts"]["vision_unresolved_disagreements"], 0)  # a failure is not a disagreement

    def test_disagreement_is_named_by_its_path(self) -> None:
        res = self.check(vision=[DISAGREE])
        self.assertIn("vision_unresolved_disagreements = 1 (e.g. evidence_09 [records[acct_1002].sync_enabled])",
                      res["refusals"])

    def test_unmapped_label_is_listed_and_does_not_block(self) -> None:
        res = self.check(vision=[AGREE, LABELS])
        self.assertTrue(res["passed"], res["refusals"])
        self.assertEqual(res["vision_unmapped_labels"]["count"], 1)
        self.assertEqual(res["vision_unmapped_labels"]["labels"], ["evidence_14:CS-4821"])
        self.assertFalse(res["vision_unmapped_labels"]["blocks"])

    # ---- T109 (c), T110: FAILED agent outcomes block; repeat failures stop for the developer ----
    def test_failed_agent_case_blocks_and_is_listed_with_its_error_class(self) -> None:
        cases = [case(c) for c in IDS]
        cases[1] = case("case_902", failed_agent("k1", "k2"))
        res = self.check(cases, calls=[call("k1", "ok", input_tokens=900), call("k2", "give_up", "APITimeoutError")])
        self.assertFalse(res["passed"])
        self.assertEqual(res["result"], "REFUSED")
        self.assertEqual(res["counts"]["agent_failed_cases"], 1)
        self.assertEqual(res["ids"]["agent_failed_cases"], ["case_902"])
        self.assertIn("agent_failed_cases = 1 (e.g. case_902 [APITimeoutError])", res["refusals"])
        self.assertTrue(any("re-run the same command" in r for r in res["refusals"]))
        self.assertEqual(res["agent_failed"][0]["request_size"]["max_logged_input_tokens"], 900)

    def test_record_flag_detail_gives_the_error_class(self) -> None:
        cases = [case(c) for c in IDS]
        cases[0] = case("case_901", failed_agent())
        cases[0]["flags"] = [{"code": "AGENT_CALL_FAILED", "detail": "loop: TRANSPORT_GAVE_UP (RateLimitError)"}]
        res = self.check(cases)
        self.assertEqual(res["agent_failed"][0]["error_class"], "RateLimitError")
        self.assertIsNone(res["agent_failed"][0]["request_size"]["max_logged_input_tokens"])

    def test_failed_case_without_a_recorded_class_says_so(self) -> None:
        cases = [case(c) for c in IDS]
        cases[2] = case("case_903", failed_agent("k9"))
        res = self.check(cases)
        self.assertIn("agent_failed_cases = 1 (e.g. case_903 [not recorded])", res["refusals"])

    def fail_runs(self, classes: list[str | None]) -> list[str]:
        """One run per entry: case_902 FAILED with that error class (None: the case passes)."""
        ids = []
        for i, cls in enumerate(classes):
            cases = [case(c) for c in IDS]
            calls = []
            if cls is not None:
                cases[1] = case("case_902", failed_agent(f"t1-{i}", f"loop-{i}"))
                calls = [call(f"t1-{i}", "ok", input_tokens=1200 + i), call(f"loop-{i}", "give_up", cls)]
            write_run(self.runs, f"r{i}", rows(), cases, vision=[AGREE], calls=calls)
            ids.append(f"r{i}")
        d = self.runs / ids[-1]
        self.approve(hashlib.sha256((d / "output.csv").read_bytes()).hexdigest())
        return ids

    def test_same_failure_on_two_reruns_in_a_row_stops_for_the_developer(self) -> None:
        ids = self.fail_runs(["APITimeoutError"] * 3)
        res = freeze_check(ids[-1], runs_root=self.runs, approved_record=self.approved, prior_run_ids=ids[:-1])
        self.assertEqual(res["result"], "STOP-FOR-DEVELOPER")
        self.assertFalse(res["passed"])
        self.assertEqual(res["stop_for_developer"], [{
            "case_id": "case_902", "error_class": "APITimeoutError", "runs": ["r0", "r1", "r2"],
            "request_size": {"max_logged_input_tokens": 1202, "request_keys": 2,
                             "basis": "cases.jsonl agent.replies x calls.jsonl usage.input_tokens"}}])
        out = io.StringIO()
        with self.patched(), contextlib.redirect_stdout(out):
            status = fc_mod.main(["--run-id", "r2", "--prior-run-id", "r0", "--prior-run-id", "r1"])
        self.assertEqual(status, fc_mod.EXIT_STOP)
        text = out.getvalue()
        self.assertIn("STOP-FOR-DEVELOPER", text)
        self.assertIn("case case_902: error class APITimeoutError; request size 1202 input tokens", text)

    def test_only_the_two_runs_just_before_count(self) -> None:
        """Four runs, oldest first: the window is the last two priors, never the first two."""
        timeout = "APITimeoutError"
        for classes, stops in (([timeout, timeout, "RateLimitError", timeout], False),
                               (["RateLimitError", timeout, timeout, timeout], True)):
            ids = self.fail_runs(list(classes))
            res = freeze_check(ids[-1], runs_root=self.runs, approved_record=self.approved, prior_run_ids=ids[:-1])
            self.assertEqual(bool(res["stop_for_developer"]), stops, classes)
            for d in self.runs.iterdir():
                shutil.rmtree(d)

    def test_no_stop_on_a_different_class_a_pass_between_or_too_few_runs(self) -> None:
        cases: list[list[str | None]] = [["APITimeoutError", "RateLimitError", "APITimeoutError"],
                                         ["APITimeoutError", None, "APITimeoutError"],
                                         ["APITimeoutError", "APITimeoutError"]]
        for classes in cases:
            ids = self.fail_runs(classes)
            res = freeze_check(ids[-1], runs_root=self.runs, approved_record=self.approved, prior_run_ids=ids[:-1])
            self.assertEqual(res["stop_for_developer"], [], classes)
            self.assertEqual(res["result"], "REFUSED", classes)  # still blocked: the FAILED case remains
            self.assertEqual(res["ids"]["agent_failed_cases"], ["case_902"], classes)
            for d in self.runs.iterdir():
                shutil.rmtree(d)

    def test_unreadable_prior_run_is_an_error_not_a_pass(self) -> None:
        ids = self.fail_runs(["APITimeoutError"])
        res = freeze_check(ids[-1], runs_root=self.runs, approved_record=self.approved, prior_run_ids=["missing-run"])
        self.assertTrue(any("prior run missing-run" in e for e in res["errors"]))
        self.assertFalse(res["passed"])

    # ---- T112 4(a): an acknowledgement covering the image and both reading keys resolves it ----
    def ack_check(self, acknowledged: Any) -> dict[str, Any]:
        d = write_run(self.runs, "r1", rows(), [case(c) for c in IDS], vision=[AGREE, DISAGREE])
        prod = json.loads((d / "producer.json").read_text(encoding="utf-8"))
        prod["vision"] = {"review": {"ack_run_id": "vision-1", "acknowledged": acknowledged}}
        (d / "producer.json").write_text(json.dumps(prod), encoding="utf-8")
        self.approve(hashlib.sha256((d / "output.csv").read_bytes()).hexdigest())
        return freeze_check("r1", runs_root=self.runs, approved_record=self.approved)

    def test_acknowledged_disagreement_is_resolved(self) -> None:
        res = self.ack_check([{"file_id": "evidence_09", "reply_keys": DISAGREE["reply_keys"]}])
        self.assertTrue(res["passed"], res["refusals"])
        self.assertEqual(res["counts"]["vision_unresolved_disagreements"], 0)
        self.assertEqual(res["vision_acknowledged_disagreements"], ["evidence_09"])

    def test_acknowledgement_for_another_reading_key_does_not_resolve(self) -> None:
        res = self.ack_check([{"file_id": "evidence_09", "reply_keys": [DISAGREE["reply_keys"][0], "re-read"]}])
        self.assertEqual(self.failing(res), ["vision_unresolved_disagreements"])
        self.assertEqual(res["vision_acknowledged_disagreements"], [])

    def test_acknowledgement_for_another_image_does_not_resolve(self) -> None:
        res = self.ack_check([{"file_id": "evidence_04", "reply_keys": AGREE["reply_keys"]}])
        self.assertEqual(self.failing(res), ["vision_unresolved_disagreements"])

    def test_malformed_acknowledgement_leaves_the_count_not_computed(self) -> None:
        res = self.ack_check([{"file_id": "evidence_09"}])
        self.assertIsNone(res["counts"]["vision_unresolved_disagreements"])
        self.assertFalse(res["passed"])

    def test_refuses_unchecked_run(self) -> None:
        res = self.check(bad_hash=True)
        self.assertFalse(res["passed"])
        self.assertEqual(res["producer_check"], "output-mismatch")
        self.assertTrue(any(r.startswith("error: producer check output-mismatch") for r in res["refusals"]))

    def test_refuses_missing_agent_field(self) -> None:
        cases = [case(c) for c in IDS]
        cases[0] = case("case_901", ABSENT)
        res = self.check(cases)
        self.assertFalse(res["passed"])
        self.assertIsNone(res["counts"]["intent_failed_closed"])
        self.assertIn("intent_failed_closed: not computed (see errors)", res["refusals"])

    def test_refuses_missing_vision_artifact(self) -> None:
        res = self.check(vision=ABSENT)
        self.assertIsNone(res["counts"]["vision_unresolved_disagreements"])
        self.assertFalse(res["passed"])

    def test_metrics_count_disagreement_is_error(self) -> None:
        res = self.check(fc_count=2)
        self.assertFalse(res["passed"])
        self.assertTrue(any("failed_closed.count disagrees" in r for r in res["refusals"]))

    def test_cli_exit_status_names_counts(self) -> None:
        d1 = write_run(self.runs, "r1", rows(), [case(c) for c in IDS], vision=[AGREE, DISAGREE])
        self.approve(hashlib.sha256((d1 / "output.csv").read_bytes()).hexdigest())
        out = io.StringIO()
        with self.patched(), contextlib.redirect_stdout(out):
            status = fc_mod.main(["--run-id", "r1"])
        self.assertEqual(status, 1)
        self.assertIn("vision_unresolved_disagreements = 1", out.getvalue())
        write_run(self.runs, "r2", rows(), [case(c) for c in IDS], vision=[AGREE])
        with self.patched(), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(fc_mod.main(["--run-id", "r2"]), 0)

    # ---- T101: the run's output must be the approved file ----
    def test_approved_output_match_passes_and_both_hashes_are_printed(self) -> None:
        d = write_run(self.runs, "r1", rows(), [case(c) for c in IDS], vision=[AGREE])
        sha = hashlib.sha256((d / "output.csv").read_bytes()).hexdigest()
        self.approve(sha)
        out = io.StringIO()
        with self.patched(), contextlib.redirect_stdout(out):
            self.assertEqual(fc_mod.main(["--run-id", "r1"]), 0)
        self.assertIn(f"output sha256:   {sha}", out.getvalue())
        self.assertIn(f"approved sha256: {sha} (match: approved_output)", out.getvalue())

    def test_approved_output_mismatch_refuses_only_on_that_check(self) -> None:
        d = write_run(self.runs, "r1", rows(), [case(c) for c in IDS], vision=[AGREE])
        sha = hashlib.sha256((d / "output.csv").read_bytes()).hexdigest()
        self.approve("f" * 64)
        res = freeze_check("r1", runs_root=self.runs, approved_record=self.approved)
        self.assertFalse(res["passed"])
        self.assertEqual(res["counts"], {k: 0 for k in COUNTS})  # every count is 0: only the approval refuses
        self.assertEqual(len(res["refusals"]), 1)
        self.assertIn(sha, res["refusals"][0])
        self.assertIn("f" * 64, res["refusals"][0])
        self.assertEqual((res["approved_output"]["output_sha256"], res["approved_output"]["approved_sha256"]),
                         (sha, "f" * 64))
        out = io.StringIO()
        with self.patched(), contextlib.redirect_stdout(out):
            self.assertEqual(fc_mod.main(["--run-id", "r1"]), 1)
        self.assertIn("MISMATCH", out.getvalue())

    # ---- T119: a provisional approval for the freeze check and the holdout run ----
    def record(self, approved_sha: str, **extra: Any) -> None:
        self.approved.write_text(json.dumps({"approved_output": {"run_id": "a", "sha256": approved_sha,
                                                                 "path": "x.csv"}, **extra}), encoding="utf-8")

    def test_provisional_freeze_sha_passes_and_says_which_matched(self) -> None:
        d = write_run(self.runs, "r1", rows(), [case(c) for c in IDS], vision=[AGREE])
        sha = hashlib.sha256((d / "output.csv").read_bytes()).hexdigest()
        self.record("f" * 64, provisional_freeze={"run_id": "r1", "sha256": sha, "ruling": "T119", "scope": "freeze"})
        res = freeze_check("r1", runs_root=self.runs, approved_record=self.approved)
        self.assertTrue(res["passed"], res["refusals"])
        self.assertEqual(res["approved_output"]["matched"], "provisional_freeze (T119)")
        out = io.StringIO()
        with self.patched(), contextlib.redirect_stdout(out):
            self.assertEqual(fc_mod.main(["--run-id", "r1"]), 0)
        self.assertIn("match: provisional_freeze (T119)", out.getvalue())
        self.assertIn(f"provisional sha256: {sha} (run r1, T119", out.getvalue())
        self.record("f" * 64, provisional_freeze={"run_id": "r1", "sha256": "e" * 64})
        res = freeze_check("r1", runs_root=self.runs, approved_record=self.approved)
        self.assertFalse(res["passed"])
        self.assertIn("e" * 64, res["refusals"][-1])

    # ---- T118 step 4: FAILED_CLOSED rows identical to the approved file are listed, not counted ----
    def fc_run(self) -> tuple[Path, str]:
        cases = [case(c) for c in IDS]
        cases[1] = case("case_902", row_state="FAILED_CLOSED", failed_closed="NOTHING_FOUND")
        d = write_run(self.runs, "r1", rows(), cases, vision=[AGREE])
        return d, hashlib.sha256((d / "output.csv").read_bytes()).hexdigest()

    def test_failed_closed_row_identical_to_the_approved_file_is_accepted(self) -> None:
        d, sha = self.fc_run()
        base = Path(self._tmp.name) / "approved_test.csv"
        base.write_bytes((d / "output.csv").read_bytes())
        self.approved.write_text(json.dumps({
            "approved_output": {"sha256": sha, "path": str(base)},
            "freeze_accepts_failed_closed_identical_to": {"sha256": sha, "ruling": "T118 step 4"}}), encoding="utf-8")
        res = freeze_check("r1", runs_root=self.runs, approved_record=self.approved)
        self.assertTrue(res["passed"], res["refusals"])
        self.assertEqual(res["counts"]["failed_closed_rows"], 0)
        self.assertEqual(res["failed_closed_accepted"]["cases"], ["case_902"])
        out = io.StringIO()
        with self.patched(), contextlib.redirect_stdout(out):
            self.assertEqual(fc_mod.main(["--run-id", "r1"]), 0)
        self.assertIn("FAILED_CLOSED rows accepted (T118 step 4", out.getvalue())

    def test_failed_closed_row_that_differs_from_the_approved_file_still_blocks(self) -> None:
        d, sha = self.fc_run()
        text = (d / "output.csv").read_text(encoding="utf-8").splitlines(keepends=True)
        changed = [line.replace("COMPLETE", "INCOMPLETE", 1) if line.startswith("case_902,") else line for line in text]
        base = Path(self._tmp.name) / "approved_test.csv"
        base.write_text("".join(changed), encoding="utf-8")
        bsha = hashlib.sha256(base.read_bytes()).hexdigest()
        self.approved.write_text(json.dumps({
            "approved_output": {"sha256": sha, "path": "x.csv"},
            "approved_outputs": {"test": {"sha256": bsha, "path": str(base)}},
            "freeze_accepts_failed_closed_identical_to": {"sha256": bsha, "ruling": "T118 step 4"}}), encoding="utf-8")
        res = freeze_check("r1", runs_root=self.runs, approved_record=self.approved)
        self.assertEqual((res["counts"]["failed_closed_rows"], res["failed_closed_accepted"]["cases"]), (1, []))
        self.assertFalse(res["passed"])
        base.write_text("tampered", encoding="utf-8")  # the named file no longer has the recorded sha256
        res = freeze_check("r1", runs_root=self.runs, approved_record=self.approved)
        self.assertEqual(res["counts"]["failed_closed_rows"], 1)
        self.assertTrue(any("does not have the recorded sha256" in e for e in res["errors"]))

    def test_without_the_ruling_key_no_failed_closed_row_is_accepted(self) -> None:
        d, sha = self.fc_run()
        self.approve(sha)
        res = freeze_check("r1", runs_root=self.runs, approved_record=self.approved)
        self.assertEqual((res["counts"]["failed_closed_rows"], res["failed_closed_accepted"]), (1, {"cases": [],
                                                                                                    "rule": None}))

    def test_unreadable_approved_record_refuses(self) -> None:
        write_run(self.runs, "r1", rows(), [case(c) for c in IDS], vision=[AGREE])
        for body in ("not json", json.dumps({"approved_output": {"sha256": "short"}}), json.dumps({})):
            self.approved.write_text(body, encoding="utf-8")
            res = freeze_check("r1", runs_root=self.runs, approved_record=self.approved)
            self.assertFalse(res["passed"], body)
            self.assertTrue(any(r.startswith("approved output: approved-output record unreadable")
                                for r in res["refusals"]), body)
        res = freeze_check("r1", runs_root=self.runs, approved_record=self.approved.with_name("missing.json"))
        self.assertFalse(res["passed"])

    def test_default_record_is_the_repo_notes_file(self) -> None:
        self.assertEqual(fc_mod.APPROVED_RECORD, paths.REPO_ROOT / "notes" / "approved_output.json")

    def test_bad_run_id_refused(self) -> None:
        with self.assertRaises(ValueError):
            freeze_check("bad id", runs_root=self.runs)


if __name__ == "__main__":
    unittest.main()
