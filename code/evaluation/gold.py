"""Dev-filtered gold loader: the only code path that reads ``dataset/sample_output.csv``.

Holdout lock (../CLAUDE.md section 4, developer decision D3):

* By default only DEV gold leaves this module. Each CSV record is tested on its FIRST field
  (``case_id``) and a holdout record is dropped right there, before its ``steps_json`` text
  is handed to the JSON parser. A holdout answer is therefore never decoded, printed,
  counted or compared. ``tests/test_gold.py`` proves it with a fixture whose holdout rows
  hold invalid JSON and a spy on ``json.loads``.
* The holdout path exists but is locked. It opens only with ``holdout=True`` AND
  ``unlock_phrase`` equal to the developer's phrase "HOLDOUT EVALUATION RUN". Without both it
  raises :class:`HoldoutLockedError` before the file is opened. A successful unlock is
  logged to stderr and appended to ``runs/HOLDOUT_ACCESS.log``. It is meant to be called
  once, after freeze, in the run the developer names.

Request rows are NOT locked (developer ruling T47, building on T32): the lock covers gold
only. The holdout cases' request inputs may join the batch account matching, so
:func:`load_requests` returns every row of the file. A DEV run chooses which cases it solves
and scores by an explicit selection (``cases=DEV_IDS``), not by this lock.

Other readers: ``outputs.read_output`` refuses the gold file by identity (same file or same
bytes) unless this module's unlock phrase is given (verifier finding B1).
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .paths import HOLDOUT_ACCESS_LOG, SAMPLE_OUTPUT, SAMPLE_REQUESTS
from .split import DEV_IDS, HOLDOUT_IDS

UNLOCK_PHRASE: str = "HOLDOUT EVALUATION RUN"
GOLD_HEADER: list[str] = ["case_id", "deletion_status", "steps_json"]


class HoldoutLockedError(PermissionError):
    """Raised when holdout data is requested without the developer's unlock phrase."""


@dataclass(frozen=True)
class GoldCase:
    """One gold answer row: status and parsed steps."""

    case_id: str
    status: str
    steps: list[dict[str, Any]]


def check_unlock(holdout: bool, unlock_phrase: str | None, what: str, run_id: str | None) -> None:
    """Refuse holdout access unless the exact unlock phrase is given; log a granted unlock."""
    if not holdout:
        return
    if unlock_phrase != UNLOCK_PHRASE:
        raise HoldoutLockedError(
            f"holdout {what} is locked: pass unlock_phrase={UNLOCK_PHRASE!r}, and only in the "
            "single post-freeze run the developer names (../CLAUDE.md section 4)"
        )
    stamp = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    line = json.dumps({"at": stamp, "what": what, "run_id": run_id})
    print(f"HOLDOUT ACCESS GRANTED: {line}", file=sys.stderr)
    HOLDOUT_ACCESS_LOG.parent.mkdir(parents=True, exist_ok=True)
    with HOLDOUT_ACCESS_LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_gold(
    path: Path = SAMPLE_OUTPUT,
    *,
    holdout: bool = False,
    unlock_phrase: str | None = None,
    run_id: str | None = None,
) -> dict[str, GoldCase]:
    """Return gold answers keyed by ``case_id``: DEV only by default.

    Args:
        path: a gold file in ``case_id,deletion_status,steps_json`` form.
        holdout: return the holdout cases instead of DEV. Locked; see the module docstring.
        unlock_phrase: must equal :data:`UNLOCK_PHRASE` when ``holdout`` is true.
        run_id: recorded in the access log when the holdout is unlocked.

    Raises:
        HoldoutLockedError: holdout requested without the unlock phrase (before any I/O).
        ValueError: bad header, a case ID in neither split, a duplicate, or an incomplete split.
    """
    check_unlock(holdout, unlock_phrase, "gold", run_id)
    wanted, dropped_set = (HOLDOUT_IDS, DEV_IDS) if holdout else (DEV_IDS, HOLDOUT_IDS)
    out: dict[str, GoldCase] = {}
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if header != GOLD_HEADER:
            raise ValueError(f"unexpected gold header {header!r}")
        for record in reader:
            case_id = record[0] if record else ""
            if case_id in dropped_set:
                continue  # holdout lock: dropped on the first field, steps_json never parsed
            if case_id not in wanted:
                raise ValueError(f"gold case {case_id!r} is in neither split")
            if case_id in out:
                raise ValueError(f"duplicate gold case {case_id!r}")
            if len(record) != 3:
                raise ValueError(f"gold row {case_id!r} has {len(record)} fields, expected 3")
            steps = json.loads(record[2])
            if not isinstance(steps, list):
                raise ValueError(f"gold row {case_id!r}: steps_json is not a JSON list")
            out[case_id] = GoldCase(case_id=case_id, status=record[1], steps=steps)
    if set(out) != set(wanted):
        missing = sorted(set(wanted) - set(out))
        raise ValueError(f"gold incomplete: missing {missing}")
    return out


def load_requests(
    path: Path = SAMPLE_REQUESTS,
    *,
    cases: Iterable[str] | None = None,
) -> dict[str, dict[str, str]]:
    """Return request rows keyed by ``case_id``: every row, or only the IDs in ``cases``.

    Request inputs are not locked (module docstring, T47). ``cases`` is the caller's explicit
    selection, e.g. ``cases=DEV_IDS`` for a DEV run. Works for both
    ``sample_deletion_requests.csv`` and ``deletion_requests.csv``.
    """
    wanted = None if cases is None else frozenset(cases)
    out: dict[str, dict[str, str]] = {}
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            case_id = row["case_id"]
            if wanted is not None and case_id not in wanted:
                continue
            if case_id in out:
                raise ValueError(f"duplicate request case {case_id!r}")
            out[case_id] = row
    return out
