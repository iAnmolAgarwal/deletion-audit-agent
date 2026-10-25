"""The CLI's paid entry points: nothing is sent without ``--paid``, one BudgetGuard per command, the
API key loaded from ``--env-file`` and never written, the routing check and the vision command.

Every transport is GM's FakeTransport, handed in through ``main(transport_factory=...)``; the env
file is a made-up temporary file (never the repo's own), and its value is a made-up string.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from deletion_audit import __main__ as cli
from deletion_audit.model import FakeTransport
from deletion_audit.pipeline import run_routing_check

from ..agent._support import PNG, answer, dataset, final_reply, tmpdir
from ..engine_fixtures import Dataset, Person, case
from ._wiring import paid_setup, plant_model_free, read_json, reading, sent, shown

FAKE_KEY = "fake-test-value-" + "9" * 24  # made up; built so no assignment literal appears in the source
NAME = cli.API_KEY_NAME


class Factory:
    """A transport factory that records how often it was called and what key the process held then."""

    def __init__(self, script: list[Any]) -> None:
        self.script = script
        self.calls = 0
        self.key_seen: str | None = None
        self.transports: list[FakeTransport] = []

    def __call__(self) -> FakeTransport:
        self.calls += 1
        self.key_seen = os.environ.get(NAME)
        t = FakeTransport(list(self.script))
        self.transports.append(t)
        return t


def run_cli(argv: list[str], factory: Factory | None = None) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = cli.main(argv, transport_factory=factory)
        except SystemExit as exc:
            code = int(exc.code or 0)
    return code, out.getvalue(), err.getvalue()


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tmpdir()
        (self.tmp / "ds").mkdir()
        self.root = dataset().write(self.tmp / "ds")
        self.replies = self.tmp / "replycache"
        self.runs = self.tmp / "rundirs"
        patcher = mock.patch("deletion_audit.pipeline.REPO_ROOT", self.tmp)  # notes/ and git under the temp dir
        patcher.start()
        self.addCleanup(patcher.stop)
        env = mock.patch.dict(os.environ, {}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop(NAME, None)

    def env_file(self, *lines: str) -> Path:
        p = self.tmp / "fake_key.envfile"
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return p

    def base_args(self, run_id: str) -> list[str]:
        return ["--run-id", run_id, "--set", "test", "--dataset", str(self.root), "--cache-dir", str(self.replies),
                "--runs-dir", str(self.runs)]


class TestNothingSentWithoutPaid(Base):
    def test_replay_run_never_builds_a_transport(self) -> None:
        f = Factory([])
        code, out, _ = run_cli(self.base_args("r1"), f)
        self.assertEqual((code, f.calls), (0, 0))
        self.assertIn("2 rows", out)

    def test_caps_and_env_file_need_paid(self) -> None:
        f = Factory([])
        for extra in (["--dollar-cap", "1"], ["--call-cap", "3"], ["--env-file", str(self.env_file("X=1"))]):
            code, _, err = run_cli(self.base_args("r2") + extra, f)
            self.assertEqual(code, 2, extra)
            self.assertIn("need --paid", err)
        self.assertEqual(f.calls, 0)

    def test_paid_needs_both_caps(self) -> None:
        f = Factory([])
        for extra in ([], ["--dollar-cap", "1"], ["--call-cap", "3"]):
            code, _, err = run_cli(self.base_args("r3") + ["--paid", *extra], f)
            self.assertEqual(code, 2, extra)
        self.assertEqual(f.calls, 0)


class TestPaidRun(Base):
    def test_one_budget_guard_with_the_caps_and_the_mode(self) -> None:
        nd = final_reply(answer("NOT_DELETION", "Send me a copy of my data"))
        dr = final_reply(answer("DELETION_REQUEST", "delete my account", kind="full_deletion"))
        f = Factory([dr, nd])
        code, out, _ = run_cli(self.base_args("p1") + ["--paid", "--dollar-cap", "0.5", "--call-cap", "2",
                                                       "--mode", "tools_off"], f)
        # the model-change check does not allow Bo's NOT_APPLICABLE row (one turn-1 reading, not two), so
        # the row falls back to the model-free row (T118 (2c)) and the run passes
        self.assertEqual((code, f.calls), (0, 1))
        producer = read_json(self.runs / "p1" / "producer.json")
        self.assertEqual(producer["run_passed"], True)
        self.assertEqual(len(producer["fell_back_cases"]), 1)
        self.assertEqual(producer["budget"]["dollar_cap"], 0.5)
        self.assertEqual(producer["budget"]["call_cap"], 2)
        self.assertEqual(producer["budget"]["sends"], 2)
        self.assertEqual(producer["mode"], "tools_off")
        self.assertFalse(producer["replay_only"])

    def test_call_cap_holds_across_the_command(self) -> None:
        dr = final_reply(answer("DELETION_REQUEST", "delete my account", kind="full_deletion"))
        f = Factory([dr, dr, dr])
        code, _, _ = run_cli(self.base_args("p2") + ["--paid", "--dollar-cap", "1", "--call-cap", "1",
                                                     "--mode", "tools_off"], f)
        self.assertEqual(code, 0)
        self.assertEqual(f.transports[0].calls, 1)  # the second case's turn 1 is refused by the one guard
        lines = [json.loads(x) for x in (self.runs / "p2" / "cases.jsonl").read_text().splitlines()]
        self.assertEqual(sorted(c["agent"]["intent"]["source"] for c in lines), ["FAILED_BUDGET", "MODEL"])


class TestEnvFile(Base):
    def test_key_is_loaded_into_the_process_and_written_nowhere(self) -> None:
        dr = final_reply(answer("DELETION_REQUEST", "delete my account", kind="full_deletion"))
        f = Factory([dr, dr])
        envf = self.env_file("# a comment", "OTHER_SETTING=keep-out", f"export {NAME}=\"{FAKE_KEY}\"")
        code, out, err = run_cli(self.base_args("k1") + ["--paid", "--dollar-cap", "1", "--call-cap", "5",
                                                         "--mode", "tools_off", "--env-file", str(envf)], f)
        self.assertEqual(code, 0, err)
        self.assertEqual(f.key_seen, FAKE_KEY)  # the transport was built with the key in the environment
        self.assertNotIn("OTHER_SETTING", os.environ)  # only the key line is used
        self.assertNotIn(FAKE_KEY, out + err)
        for p in sorted((self.runs / "k1").rglob("*")):
            if p.is_file():
                self.assertNotIn(FAKE_KEY, p.read_text(encoding="utf-8"), p.name)
        for p in sorted(self.replies.rglob("*")):
            if p.is_file():
                self.assertNotIn(FAKE_KEY, p.read_text(encoding="utf-8"), p.name)
        for body in f.transports[0].sent:
            self.assertNotIn(FAKE_KEY, json.dumps(body, default=str))

    def test_value_forms(self) -> None:
        for line, value in ((f"{NAME}={FAKE_KEY}", FAKE_KEY), (f"{NAME}='{FAKE_KEY}'", FAKE_KEY),
                            (f"{NAME} = {FAKE_KEY} # note", FAKE_KEY)):
            os.environ.pop(NAME, None)
            cli.load_api_key(self.env_file(line))
            self.assertEqual(os.environ.get(NAME), value, line)

    def test_missing_line_empty_value_or_missing_file_is_an_error_that_quotes_nothing(self) -> None:
        for lines in (("OTHER=1",), (f"{NAME}=",), (f"{NAME}=''",)):
            with self.assertRaises(cli.EnvFileError) as ctx:
                cli.load_api_key(self.env_file(*lines))
            self.assertNotIn("OTHER", str(ctx.exception))
        with self.assertRaises(cli.EnvFileError):
            cli.load_api_key(self.tmp / "absent.envfile")
        f = Factory([])
        code, out, err = run_cli(self.base_args("k2") + ["--paid", "--dollar-cap", "1", "--call-cap", "5",
                                                         "--env-file", str(self.env_file("OTHER=secretish"))], f)
        self.assertEqual((code, f.calls), (2, 0))
        self.assertNotIn("secretish", out + err)


class TestExitCodes(Base):
    def test_vision_review_refusal_exits_4(self) -> None:
        (self.tmp / "ds2").mkdir()
        root = dataset(image=PNG).write(self.tmp / "ds2")
        f = Factory([])
        code, _, err = run_cli(["--run-id", "v1", "--set", "test", "--dataset", str(root), "--cache-dir",
                                str(self.replies), "--runs-dir", str(self.runs), "--paid", "--dollar-cap", "1",
                                "--call-cap", "5"], f)
        self.assertEqual(code, cli.EXIT_VISION_REVIEW)
        self.assertIn("--vision-ack", err)
        self.assertEqual(f.transports[0].calls, 0)

    def test_regression_gate_stop_exits_5(self) -> None:
        """An unexplained model-derived change exits 5; ``--regression-gate`` is accepted as a no-op."""
        with plant_model_free():
            code, _, err = run_cli(self.base_args("g1") + ["--regression-gate"])
        self.assertEqual(code, cli.EXIT_GATE_STOP)
        self.assertIn("RUN NOT PASSING", err)

    def test_run_id_is_optional(self) -> None:
        code, out, _ = run_cli(self.base_args("x")[2:])
        self.assertEqual(code, 0)
        made = [d.name for d in self.runs.iterdir()]
        self.assertEqual(len(made), 1)
        self.assertRegex(made[0], r"^run-\d{8}T\d{6}$")
        self.assertIn(made[0], out)

    def test_write_root_needs_the_test_set(self) -> None:
        code, _, err = run_cli(["--set", "dev", "--write-root", "--runs-dir", str(self.runs)])
        self.assertEqual(code, 2)
        self.assertIn("--write-root needs --set test", err)
        self.assertFalse((self.tmp / "output.csv").exists())


class TestRoutingAndVisionCommands(Base):
    def make_repo(self) -> Path:
        """A temporary repo layout: dataset/ (the synthetic one) and two fixture folders."""
        repo = self.tmp / "repo"
        (repo / "dataset").mkdir(parents=True)
        d = dataset()
        d.add_request(case(9003), "cy@example.test", sample=True, request_text="Erase everything about me now.")
        d.people.append(Person("user_9003", "cy@example.test"))
        d.write(repo / "dataset")
        for name in ("F99_synthetic", "redteam/R99_synthetic"):
            p = repo / "code" / "tests" / "fixtures" / name
            p.mkdir(parents=True)
            fx = Dataset(people=[Person("user_9101", "fx@example.test")])
            fx.add_request(case(9101), "fx@example.test", request_text=f"Delete my data ({name}).")
            fx.write(p)
        return repo

    def test_routing_check_reads_each_distinct_text_once_per_namespace(self) -> None:
        repo = self.make_repo()
        script = [final_reply(answer("UNCERTAIN", "")) for _ in range(8)]
        setup = paid_setup(self.replies, script)
        with mock.patch("deletion_audit.pipeline.dev_ids", return_value=frozenset()):
            rec = run_routing_check(run_id="rc1", sources=["test", "fixtures", "redteam"], model=setup,
                                    runs_dir=self.runs, repo_root=repo)
        self.assertEqual((rec["distinct_texts"], rec["cases"]), (4, 4))
        self.assertEqual(len(sent(setup)), 8)  # 4 texts x 2 namespaces
        body = read_json(self.runs / "rc1" / "routing_table.json")
        self.assertEqual({r["folder"] for r in body["case_rows"]}, {"dataset", "F99_synthetic", "R99_synthetic"})
        self.assertEqual(body["matrix_label_x_intake"]["replies"]["UNCERTAIN"],
                         {"intake_row_present": 1, "intake_row_absent": 3})
        self.assertTrue(all(r["labels"] == ["UNCERTAIN", "UNCERTAIN"] for r in body["case_rows"]))
        for name in ("routing_table.md", "calls.jsonl", "usage.json", "run.json"):
            self.assertTrue((self.runs / "rc1" / name).is_file(), name)
        text = (self.runs / "rc1" / "routing_table.json").read_text(encoding="utf-8")
        self.assertNotIn("Delete my data", text)  # texts are named by text_id only
        # a second run replays both namespaces: nothing sent
        again = paid_setup(self.replies, [])
        run_routing_check(run_id="rc2", sources=["test", "fixtures", "redteam"], model=again, runs_dir=self.runs,
                          repo_root=repo)
        self.assertEqual(sent(again), [])

    def test_full_run_replays_the_routing_check_replies_in_both_namespaces(self) -> None:
        """The routing check and the full run build the same turn-1 request, so the full run buys nothing
        for turn 1 and reads the replicate from the second namespace (T97 (2))."""
        repo = self.make_repo()
        nd = final_reply(answer("NOT_DELETION", "Send me a copy of my data"))
        dr = final_reply(answer("DELETION_REQUEST", "delete my account", kind="full_deletion"))
        # routing_table reads texts in text_id order; give every text the reply that fits it
        from deletion_audit.agent.routing import text_id
        from deletion_audit.pipeline import text_cases

        texts = sorted({c.text for c in text_cases(["test"], repo)}, key=text_id)
        script = [r for t in texts for r in ((nd, nd) if t.startswith("Send me") else (dr, dr))]
        run_routing_check(run_id="rc5", sources=["test"], model=paid_setup(self.replies, script), runs_dir=self.runs,
                          repo_root=repo)
        f = Factory([])
        code, _, _ = run_cli(["--run-id", "full", "--set", "test", "--dataset", str(repo / "dataset"), "--mode",
                              "tools_off", "--cache-dir", str(self.replies), "--runs-dir", str(self.runs)], f)
        self.assertEqual((code, f.calls), (0, 0))
        lines = [json.loads(x) for x in (self.runs / "full" / "cases.jsonl").read_text().splitlines()]
        reps = sorted(tuple(c["agent"]["turn1_replicates"]) for c in lines)
        self.assertEqual(reps, [("DELETION_REQUEST", "DELETION_REQUEST"), ("NOT_DELETION", "NOT_DELETION")])
        usage = read_json(self.runs / "full" / "usage.json")
        self.assertEqual((usage["model_calls"], usage["cache_hits"]), (0, 4))
        self.assertEqual(usage["replies_used"]["bought_by_runs"], {"rc5": 4})

    def test_dev_source_takes_dev_ids_only_and_refuses_holdout(self) -> None:
        repo = self.make_repo()
        setup = paid_setup(self.replies, [final_reply(answer("UNCERTAIN", ""))] * 2)
        with mock.patch("deletion_audit.pipeline.dev_ids", return_value=frozenset({case(9003)})):
            rec = run_routing_check(run_id="rc3", sources=["dev"], model=setup, runs_dir=self.runs, repo_root=repo)
        self.assertEqual(rec["cases"], 1)
        from deletion_audit.pipeline import HoldoutRefused

        with mock.patch("deletion_audit.pipeline.dev_ids", return_value=frozenset({case(9003)})), \
                mock.patch("deletion_audit.pipeline.holdout_ids", return_value=frozenset({case(9003)})):
            with self.assertRaises(HoldoutRefused):
                run_routing_check(run_id="rc4", sources=["dev"], model=paid_setup(self.replies, []),
                                  runs_dir=self.runs, repo_root=repo)

    def test_unknown_source_is_refused(self) -> None:
        code, _, err = run_cli(["routing-check", "--run-id", "x", "--texts", "dev,gold"])
        self.assertEqual(code, 2)
        with self.assertRaises(ValueError):
            run_routing_check(run_id="x", sources=["gold"], model=paid_setup(self.replies, []), runs_dir=self.runs)

    def test_vision_command_reads_each_image_twice_and_replays_without_paid(self) -> None:
        (self.tmp / "ds3").mkdir()
        root = dataset(image=PNG).write(self.tmp / "ds3")
        value = final_reply(reading([shown("data_flow_900000003", sync_enabled="yes")]))
        f = Factory([value, value])
        code, out, _ = run_cli(["vision", "--run-id", "vc1", "--dataset", str(root), "--cache-dir", str(self.replies),
                                "--runs-dir", str(self.runs), "--paid", "--dollar-cap", "1", "--call-cap", "2"], f)
        self.assertEqual((code, f.transports[0].calls), (0, 2))
        rec = read_json(self.runs / "vc1" / "run.json")
        # the reading changes Ada's row (an enabled flow), so the image is on the review list (T112 item 4 (b))
        self.assertEqual((rec["read_ok"], rec["needs_review"], rec["model_calls"]), (["ev_img"], ["ev_img"], 2))
        for name in ("vision_readings.json", "vision_readings.md", "vision.json", "calls.jsonl", "usage.json"):
            self.assertTrue((self.runs / "vc1" / name).is_file(), name)
        f2 = Factory([])
        code, _, _ = run_cli(["vision", "--run-id", "vc2", "--dataset", str(root), "--cache-dir", str(self.replies),
                              "--runs-dir", str(self.runs)], f2)
        self.assertEqual((code, f2.calls), (0, 0))
        self.assertEqual(read_json(self.runs / "vc2" / "run.json")["read_ok"], ["ev_img"])


if __name__ == "__main__":
    unittest.main()
