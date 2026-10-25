"""The pipeline: inputs -> engine -> validated rows -> ``runs/<run_id>/output.csv`` plus artifacts.

* The output goes to ``runs/<run_id>/output.csv``. The root ``output.csv`` is written only when
  ``write_root=True`` is passed explicitly (``../CLAUDE.md`` section 5; developer approval needed).
* G5 builds the engine path only (``notes/INTERFACES.md`` section 7): ``mode`` and
  ``replay_only`` are recorded, no model is called, and every case gets the fail-closed intent
  of T71 Q2 (the engine's deletion-path row, flagged).
* Every requested case gets exactly one row; a row is never left empty (``FAILED_CLOSED``).
* **Holdout guard** (``../CLAUDE.md`` section 4): :func:`run` refuses, before it reads any input,
  an explicit case list that names a holdout case, and, after resolving ``"test"``, any resolved
  case that is one. It raises :class:`HoldoutRefused` and writes nothing. The holdout cases'
  request inputs still join the global stages (T32, T47); only running or writing them is
  refused. **The one unlock (T96):** ``holdout_unlock`` must be the developer's exact phrase,
  checked by ``evaluation.gold.check_unlock``, which raises ``HoldoutLockedError`` on any other
  value and logs a granted unlock once per run. Only ``evaluation/holdout_run.py`` passes it
  (``code/evaluation/tests/test_holdout_static.py``); the CLI never does.
* The producer record carries ``git_head`` (the 40-hex HEAD, or None outside a git checkout), so a
  freeze run names the commit it ran on (T96: ``holdout_run`` checks it against the freeze tag).
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import sys
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from .artifacts import RunArtifacts, now_ist
from .engine import AuditContext, FailClosedIntent, World, audit_all, build_context, build_world
from .steps.serialize import write_output

Mode = Literal["A+", "A", "tools_off"]
RUN_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*", re.ASCII)
REPO_ROOT = Path(__file__).resolve().parents[2]


class HoldoutRefused(ValueError):
    """A run named a holdout case (module docstring); the message never lists the IDs."""


def holdout_ids() -> frozenset[str]:
    """The locked holdout case IDs, from ``code/evaluation/split.py`` (the mirror of
    ``notes/split.json``). An import failure propagates: the guard never runs without its list."""
    code_dir = str(REPO_ROOT / "code")
    if code_dir not in sys.path:
        sys.path.insert(0, code_dir)
    from evaluation.split import HOLDOUT_IDS

    return frozenset(HOLDOUT_IDS)


def refuse_holdout(cases: Iterable[str]) -> None:
    """Raise :class:`HoldoutRefused` when any of ``cases`` is a holdout case."""
    named = set(cases) & holdout_ids()
    if named:
        raise HoldoutRefused(
            f"refused: {len(named)} holdout case(s) requested; holdout cases are never run or written "
            "(../CLAUDE.md section 4)"
        )


def guard_holdout(cases: Iterable[str], holdout_unlock: str | None, run_id: str, granted: bool) -> bool:
    """Refuse holdout cases unless ``holdout_unlock`` is the developer's phrase (module docstring).

    Returns whether the unlock is granted for this run; a granted unlock is logged once (the
    second call of a run, after ``"test"`` is resolved, passes ``granted=True``).
    """
    if not set(cases) & holdout_ids():
        return granted
    if holdout_unlock is None:
        refuse_holdout(cases)
    if not granted:
        from evaluation.gold import check_unlock  # code/ is on sys.path: holdout_ids() put it there

        check_unlock(True, holdout_unlock, "engine run", run_id)
    return True


def git_head() -> str | None:
    """The repo's HEAD commit (40 hex), or None when it cannot be read."""
    try:
        out = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"], capture_output=True,
                             text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    head = out.stdout.strip()
    return head if out.returncode == 0 and re.fullmatch(r"[0-9a-f]{40}", head) else None


@dataclass(frozen=True)
class RunSummary:
    """What a run wrote and its headline counts."""

    run_id: str
    output_path: Path
    output_sha256: str
    rows: int
    metrics: dict[str, Any]


def evidence_record(ctx: AuditContext, world: World) -> dict[str, Any]:
    """Producer-record evidence fields for ``evidence_guard.check_producer`` (T47, T60, T72)."""
    skipped = sorted(f"{f.file_id}:png-model-needed" for f in world.failures if f.png)
    failures = sorted(f"{f.file_id}:{f.status}" for f in world.failures if not f.png)
    return {
        "evidence_skipped": skipped,
        "evidence_skip_count": len(skipped),
        "evidence_failures": failures,
        "evidence_no_resource_id_files": [],
        "evidence_parse": {fid: fp.status for fid, fp in ctx.index.files.items()},
    }


def resolve_cases(ctx: AuditContext, cases: Sequence[str] | Literal["test"]) -> list[str]:
    """``"test"`` = every row of ``deletion_requests.csv``; otherwise the given case IDs."""
    if cases == "test":
        bad = [i.case_id for i in ctx.request_issues if i.case_id and i.file == "deletion_requests.csv"]
        return sorted({r.case_id for r in ctx.requests if r.source == "test"} | set(bad))
    return list(cases)


def run(
    dataset_dir: Path,
    *,
    run_id: str,
    cases: Sequence[str] | Literal["test"],
    mode: Mode = "A+",
    replay_only: bool = True,
    write_root: bool = False,
    runs_dir: Path | None = None,
    command: str = "",
    holdout_unlock: str | None = None,
) -> RunSummary:
    """Run the engine on ``cases`` and write the run directory (module docstring)."""
    if RUN_ID_RE.fullmatch(run_id) is None:
        raise ValueError("run id must match ^[A-Za-z0-9][A-Za-z0-9._-]*$")
    granted = False
    if cases != "test":
        granted = guard_holdout(cases, holdout_unlock, run_id, granted)  # before any input is read
    t0 = time.monotonic()
    ctx = build_context(dataset_dir)
    wanted = resolve_cases(ctx, cases)
    granted = guard_holdout(wanted, holdout_unlock, run_id, granted)  # also a resolved "test" run
    world = build_world(ctx)
    records = audit_all(ctx, wanted, FailClosedIntent(), world)
    run_dir = (runs_dir or REPO_ROOT / "runs") / run_id
    out_path = run_dir / "output.csv"
    sha = write_output([(r.case_id, r.status, r.steps) for r in records.values()], out_path)
    if write_root:
        root_sha = write_output([(r.case_id, r.status, r.steps) for r in records.values()], REPO_ROOT / "output.csv")
        if root_sha != sha:
            raise RuntimeError("root output.csv differs from the run's output.csv")
    arts = RunArtifacts(run_dir)
    for r in records.values():
        arts.case(r)
    producer = {
        "tool": "code/deletion_audit (pipeline.run)",
        "command": command,
        "description": (
            f"G5 deterministic engine on {len(records)} case(s); mode {mode} recorded, engine path only; "
            "intent fail-closed (T71 Q2); no model calls"
        ),
        "mode": mode,
        "replay_only": replay_only,
        "rows_written": len(records),
        "output_sha256": sha,
        "model_ids": [],
        "paid_model_calls": 0,
        "created_at": now_ist(),
        "code_sha256": code_hash(),
        "git_head": git_head(),
        "holdout_unlocked": granted,
        **evidence_record(ctx, world),
        "request_issues": [
            {"file": i.file, "line": i.line, "case_id": i.case_id, "reason": i.reason} for i in ctx.request_issues
        ],
    }
    metrics = arts.finish(sha, producer, time.monotonic() - t0)
    return RunSummary(run_id, out_path, sha, len(records), metrics)


def code_hash() -> str:
    """sha256 over the package's .py files, by relative path (metadata for the producer record)."""
    pkg = Path(__file__).resolve().parent
    h = hashlib.sha256()
    for p in sorted(pkg.rglob("*.py")):
        h.update(str(p.relative_to(pkg)).encode() + b"\0" + p.read_bytes() + b"\0")
    return h.hexdigest()
