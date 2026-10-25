"""Invariants on the real inputs (no gold): every row of every non-holdout request, checked structurally.

These are properties, not snapshots: no expected row or count is stored here.
"""

from __future__ import annotations

import functools
import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from deletion_audit import timeutil
from deletion_audit.engine import AuditContext, audit_all, build_context, build_world
from deletion_audit.policy.rules import violating_states
from deletion_audit.record import CaseRecord

REPO = Path(__file__).resolve().parents[3]
DATASET = REPO / "dataset"
sys.path.insert(0, str(REPO / "code"))
from evaluation.split import HOLDOUT_IDS  # noqa: E402


@functools.lru_cache(maxsize=1)
def records() -> tuple[AuditContext, dict[str, CaseRecord]]:
    ctx = build_context(DATASET)
    cases = [r.case_id for r in ctx.requests if r.case_id not in HOLDOUT_IDS]
    return ctx, audit_all(ctx, cases, world=build_world(ctx))


class RealInvariants(unittest.TestCase):
    """Safety and row invariants over every DEV and test request."""

    def test_every_row_valid_or_failed_closed(self) -> None:
        _, recs = records()
        for r in recs.values():
            hard = [c for c in r.checks if c.severity == "hard" and not c.ok]
            with self.subTest(row=r.row_state):
                self.assertTrue(r.failed_closed is not None or not hard)
                self.assertNotEqual(r.status, "COMPLETE" if r.failed_closed else "-")

    def test_post_audit_evidence_never_cited(self) -> None:
        ctx, recs = records()
        captured = {ref.file_id: ref.captured_at for ref in ctx.manifest}
        for r in recs.values():
            for s in r.steps:
                if s.evidence_id:
                    self.assertIsNotNone(r.request)
                    assert r.request is not None
                    self.assertTrue(timeutil.le(captured[s.evidence_id], r.request.audit_at))

    def test_complete_never_with_live_record_active_flow_or_restore_path(self) -> None:
        ctx, recs = records()
        for r in recs.values():
            if r.status != "COMPLETE":
                continue
            for x in r.resources:
                self.assertNotIn(x.state.value, violating_states(x.category.category, ctx.rules))
                self.assertFalse(x.state.depends_on)

    def test_unparsed_dependency_never_complete(self) -> None:
        _, recs = records()
        for r in recs.values():
            if r.failed_dependencies:
                self.assertEqual(r.status, "INCOMPLETE")

    def test_holdout_rows_never_produced(self) -> None:
        _, recs = records()
        self.assertFalse(set(recs) & HOLDOUT_IDS)


SCRIPT = """
import sys; sys.path.insert(0, {code!r})
from pathlib import Path
from deletion_audit.pipeline import ModelSetup, run
s = run(Path({ds!r}), run_id="det", cases="test", runs_dir=Path(sys.argv[1]),
        model=ModelSetup.replay(Path(sys.argv[1]) / "replycache"))  # hermetic: never the repo's reply cache
print(s.output_sha256)
"""


class Determinism(unittest.TestCase):
    """test_two_process_output_sha256_equal: two processes, different hash seeds, same bytes."""

    def test_two_process_output_sha256_equal(self) -> None:
        shas = []
        for seed in ("1", "4242"):
            with tempfile.TemporaryDirectory() as tmp:
                env = {**os.environ, "PYTHONHASHSEED": seed}
                out = subprocess.run(
                    [sys.executable, "-B", "-c", SCRIPT.format(code=str(REPO / "code"), ds=str(DATASET)), tmp],
                    capture_output=True,
                    text=True,
                    env=env,
                    timeout=300,
                    check=True,
                )
                sha = out.stdout.strip().splitlines()[-1]
                self.assertEqual(sha, hashlib.sha256((Path(tmp) / "det" / "output.csv").read_bytes()).hexdigest())
                shas.append(sha)
        self.assertEqual(shas[0], shas[1])


if __name__ == "__main__":
    unittest.main()
