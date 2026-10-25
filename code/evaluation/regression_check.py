"""Regression check: a finished run against the developer-approved output file for its case set.

Usage (from the repo root):
    python3 -B code/evaluation/regression_check.py --run-id <run_id> [--record <approved-output record>]

This is an evaluation check, outside the runtime: the pipeline never reads a stored output file
(it compares each model-derived change with the engine's model-free row computed in the same run).
Rules, each with its reason (T-numbers point to ``code/docs/DECISIONS.md``):

* **Which approved file.** Rule: the record (default ``notes/approved_output.json``) names the
  approved output (``approved_output``) and one approved file per split (``approved_outputs``); the
  check uses the first of them, in that order, whose case set equals the run's ``output.csv``. No
  entry with the run's case set refuses the check. Reason: an approved file covers one case set
  (T101 (1), T117 B2), so a different set is not comparable, and a guess would hide a regression.
* **The file is checked first.** Rule: the approved file's sha256 must equal the record's before a
  row is read; a mismatch, a missing file or an unreadable record refuses the check. Reason:
  approving a file means approving those exact bytes (T101 (1)).
* **Every differing row is reported with its cause.** Rule: a row differs when its status or its
  ``steps_json`` text differs from the approved row. Its cause is read from the run's
  ``regression_vs_engine.json``: a case judged there is a model-derived change (cause and verdict as
  judged); any other differing row is an ``engine`` change (the engine's model-free row itself
  differs from the approved row). An unreadable report leaves each cause ``not recorded``, never
  ``engine``. Reason: a failed read is an explicit failure, never "nothing found".
* **Pass.** Rule: the check passes only when no row differs. Reason: the submitted output must be
  byte-identical to an approved file, and any change needs the developer's re-approval (T101 (3)).

Exit status: 0 pass, 1 rows differ, 2 refused (no comparable approved file, or unreadable inputs).
The report names case IDs, statuses, step counts and causes only, never request or evidence text.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if __package__ in (None, ""):  # run as a script: same bootstrap as freeze_check.py
    _here = str(Path(__file__).resolve().parent)
    sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != Path(_here)]
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = "evaluation"

from evaluation import runs  # noqa: E402
from evaluation.paths import REPO_ROOT, RUNS  # noqa: E402

APPROVED_RECORD: Path = REPO_ROOT / "notes" / "approved_output.json"
OUTPUT_FILE = "output.csv"
CHANGES_FILE = "regression_vs_engine.json"  # the run's model-derived-change report (agent/model_changes.py)
HEADER = ["case_id", "deletion_status", "steps_json"]
NOT_RECORDED = "not recorded"
EXIT_PASS, EXIT_DIFFERS, EXIT_REFUSED = 0, 1, 2


class CheckRefused(ValueError):
    """The run cannot be compared: no approved file with its case set, or an unreadable input."""


@dataclass(frozen=True)
class Approved:
    """One approved file of the record, sha256-checked, with its rows."""

    entry: str
    path: str
    sha256: str
    run_id: str | None
    rows: Mapping[str, tuple[str, str]]


@dataclass
class CheckResult:
    """The check's outcome for one run."""

    run_id: str
    approved: dict[str, Any]
    rows_compared: int = 0
    differing: list[dict[str, Any]] = field(default_factory=list)
    refusal: str | None = None
    errors: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        """No refusal and no differing row."""
        return self.refusal is None and not self.differing

    def as_json(self) -> dict[str, Any]:
        """The record body (rows in case order)."""
        return {"kind": "regression-check", "run_id": self.run_id, "approved": self.approved,
                "rows_compared": self.rows_compared, "differing_rows": len(self.differing),
                "rows": self.differing, "refusal": self.refusal, "errors": self.errors, "passed": self.passed}


def parse_rows(data: bytes) -> dict[str, tuple[str, str]]:
    """``{case_id: (status, steps_json text)}`` from ``output.csv`` bytes; a bad header, a short row or a
    duplicated case raises :class:`CheckRefused` (a file that cannot be read row by row is not compared)."""
    try:
        reader = csv.reader(io.StringIO(data.decode("utf-8")))
        header = next(reader, None)
        lines = list(reader)
    except (UnicodeDecodeError, csv.Error) as exc:
        raise CheckRefused(f"the output file cannot be parsed ({type(exc).__name__})") from exc
    if header != HEADER:
        raise CheckRefused("the output file has an unexpected header")
    rows: dict[str, tuple[str, str]] = {}
    for line in lines:
        if len(line) != 3 or line[0] in rows:
            raise CheckRefused("the output file has a short or duplicated row")
        rows[line[0]] = (line[1], line[2])
    return rows


def _entries(record: Mapping[str, Any]) -> list[tuple[str, Mapping[str, Any]]]:
    """The record's approved files in check order: ``approved_output``, then each split (sorted)."""
    out: list[tuple[str, Mapping[str, Any]]] = []
    main = record.get("approved_output")
    if isinstance(main, Mapping):
        out.append(("approved_output", main))
    per_split = record.get("approved_outputs")
    if isinstance(per_split, Mapping):
        out += [(f"approved_outputs.{k}", v) for k, v in sorted(per_split.items()) if isinstance(v, Mapping)]
    return out


def load_approved(record_path: Path, repo_root: Path, entry: str, raw: Mapping[str, Any]) -> Approved:
    """One entry's file, read relative to ``repo_root`` and checked against its recorded sha256."""
    try:
        rel, sha = str(raw["path"]), str(raw["sha256"])
    except (KeyError, TypeError) as exc:
        raise CheckRefused(f"{entry} in {record_path.name} has no path or sha256") from exc
    path = Path(rel) if Path(rel).is_absolute() else Path(repo_root) / rel
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise CheckRefused(f"the approved file {rel} cannot be read ({type(exc).__name__})") from exc
    actual = hashlib.sha256(data).hexdigest()
    if actual != sha:
        raise CheckRefused(f"the approved file {rel} has sha256 {actual[:16]}..., the record says {sha[:16]}...")
    run_id = raw.get("run_id")
    return Approved(entry, rel, sha, run_id if isinstance(run_id, str) else None, parse_rows(data))


def pick_approved(record_path: Path, repo_root: Path, cases: set[str]) -> Approved:
    """The first approved file of the record whose case set equals ``cases`` (module docstring)."""
    try:
        record = json.loads(Path(record_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise CheckRefused(f"the approved-output record is unreadable ({type(exc).__name__})") from exc
    if not isinstance(record, Mapping):
        raise CheckRefused("the approved-output record is not a JSON object")
    entries = _entries(record)
    if not entries:
        raise CheckRefused("the approved-output record names no approved file")
    for entry, raw in entries:
        approved = load_approved(record_path, repo_root, entry, raw)
        if set(approved.rows) == cases:
            return approved
    raise CheckRefused(f"no approved file has the run's case set ({len(cases)} case(s)); checked "
                       f"{', '.join(e for e, _ in entries)}")


def model_changes(run_dir: Path) -> tuple[dict[str, Mapping[str, Any]] | None, str | None]:
    """The run's judged model-derived changes by case, or (None, why) when the report is unreadable."""
    try:
        body = json.loads((run_dir / CHANGES_FILE).read_text(encoding="utf-8"))
        rows = body["rows"]
        if not isinstance(rows, list):
            raise TypeError("rows is not a list")
        by_case = {str(r["case_id"]): r for r in rows}
    except (OSError, UnicodeDecodeError, ValueError, KeyError, TypeError) as exc:
        return None, f"{CHANGES_FILE}: missing or unreadable ({type(exc).__name__}); causes not recorded"
    return by_case, None


def _n_steps(steps_json: str) -> int | None:
    try:
        value = json.loads(steps_json)
    except ValueError:
        return None
    return len(value) if isinstance(value, list) else None


def _case_order(case_id: str) -> tuple[int, str]:
    digits = case_id.rpartition("_")[2]
    return (int(digits) if digits.isdigit() else -1, case_id)


def regression_check(run_id: str, *, runs_root: Path = RUNS, approved_record: Path | None = None,
                     repo_root: Path = REPO_ROOT) -> CheckResult:
    """Compare ``runs/<run_id>/output.csv`` with its approved file (module docstring); never raises on bad
    artifacts: a refusal is recorded instead."""
    record_path = approved_record or APPROVED_RECORD
    result = CheckResult(run_id, {"record": str(record_path), "entry": None, "path": None, "sha256": None})
    run_dir = Path(runs_root) / runs.check_run_id(run_id)
    try:
        mine = parse_rows((run_dir / OUTPUT_FILE).read_bytes())
    except OSError as exc:
        result.refusal = f"the run's {OUTPUT_FILE} cannot be read ({type(exc).__name__})"
        return result
    except CheckRefused as exc:
        result.refusal = f"the run's {OUTPUT_FILE}: {exc}"
        return result
    try:
        approved = pick_approved(record_path, repo_root, set(mine))
    except CheckRefused as exc:
        result.refusal = str(exc)
        return result
    result.approved.update(entry=approved.entry, path=approved.path, sha256=approved.sha256, run_id=approved.run_id)
    result.rows_compared = len(mine)
    changes, why = model_changes(run_dir)
    if why:
        result.errors.append(why)
    for cid in sorted(mine, key=_case_order):
        before, now = approved.rows[cid], mine[cid]
        if before == now:
            continue
        judged = changes.get(cid) if changes is not None else None
        if changes is None:
            cause, verdict = NOT_RECORDED, NOT_RECORDED
        elif judged is None:
            cause, verdict = "engine", "not a model-derived change: the model-free row differs from the approved row"
        else:
            cause, verdict = str(judged.get("cause")), str(judged.get("verdict"))
        result.differing.append({
            "case_id": cid, "cause": cause, "verdict": verdict,
            "approved": {"status": before[0], "n_steps": _n_steps(before[1])},
            "run": {"status": now[0], "n_steps": _n_steps(now[1])},
            "status_differs": before[0] != now[0],
        })
    return result


def main(argv: list[str] | None = None) -> int:
    """Run the check; exit 0 on pass, 1 when rows differ, 2 when refused."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run-id", required=True, help="the run to check (runs/<id>/)")
    ap.add_argument("--record", help="the approved-output record (default notes/approved_output.json)")
    a = ap.parse_args(argv)
    res = regression_check(a.run_id, runs_root=RUNS, approved_record=Path(a.record) if a.record else None,
                           repo_root=REPO_ROOT)
    ap_ = res.approved
    print(f"regression check {res.run_id}: against {ap_['entry']} {ap_['path']} "
          f"(sha256 {str(ap_['sha256'])[:16]}...; record {ap_['record']})")
    for e in res.errors:
        print(f"  error: {e}")
    if res.refusal:
        print(f"REGRESSION CHECK REFUSED: {res.refusal}")
        return EXIT_REFUSED
    print(f"  rows compared {res.rows_compared}; differing {len(res.differing)}")
    for r in res.differing:
        print(f"  {r['case_id']}: {r['approved']['status']} ({r['approved']['n_steps']}) -> "
              f"{r['run']['status']} ({r['run']['n_steps']}); cause {r['cause']}; {r['verdict']}")
    if res.passed:
        print("REGRESSION CHECK PASSED: every row equals the approved file")
        return EXIT_PASS
    print("REGRESSION CHECK FAILED: rows differ from the approved file")
    return EXIT_DIFFERS


if __name__ == "__main__":
    sys.exit(main())
