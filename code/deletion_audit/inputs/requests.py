"""Loader for the two request files (T32): ``deletion_requests.csv`` and ``sample_deletion_requests.csv``.

Both files' request *inputs* are loaded, because the global account assignment must see every
competing request (developer ruling T32). ``sample_output.csv`` (gold) is never opened here.
Which cases are solved and written is chosen by the caller, never by this loader.

* Times go through the evidence layer's one time normalizer (exact seconds kept).
* The email goes through the one identifier normalizer; its raw value is kept.
* A malformed row is isolated (T86 item 2): it becomes a :class:`RequestIssue` naming the file,
  line and, when readable, the case; the rows around it load normally. A bad header raises.
* A case ID is readable only when it is exactly ``case_<digits>`` (developer ruling T87(5); every
  one of the 550 real request rows has that shape). A row whose ID is not readable is an issue
  with no case, so it is reported in the run artifacts and gets no output row, whatever its other
  fields hold.
* A case ID in both files is an issue in each file, at its own line (T86 item 2): the case keeps
  its malformed-request row and is never dropped silently.
"""

from __future__ import annotations

import csv
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ..evidence.interpret import make_identifier, normalize_time
from ..evidence.model import Identifier
from .model import InputFormatError

ReportedStatus = Literal["COMPLETE", "PARTIALLY_COMPLETE", "NOT_STARTED"]
RequestSource = Literal["test", "sample"]

TEST_FILE = "deletion_requests.csv"
SAMPLE_FILE = "sample_deletion_requests.csv"
REQUEST_HEADER = ("case_id", "email", "requested_at", "reported_status", "reported_at", "audit_at", "request_text")
REPORTED_STATUSES: frozenset[str] = frozenset({"COMPLETE", "PARTIALLY_COMPLETE", "NOT_STARTED"})


@dataclass(frozen=True)
class DeletionRequest:
    """One request row. ``source`` says which file it came from; sample rows compete in the
    account assignment (T32) but the caller decides whether their rows are written."""

    case_id: str
    email: Identifier
    requested_at: str
    reported_status: ReportedStatus
    reported_at: str
    audit_at: str
    request_text: str
    source: RequestSource


#: T87(5): a readable case ID is non-empty and shaped ``case_<digits>`` (used with ``fullmatch``).
CASE_ID_RE = re.compile(r"case_[0-9]+", re.ASCII)


@dataclass(frozen=True)
class RequestIssue:
    """A request row that could not be loaded (T86 item 2). ``case_id`` is set only when readable;
    ``reason`` names the problem, never the cell content."""

    file: str
    line: int
    case_id: str | None
    reason: str


def _row_issue(row: dict[str, str]) -> str | None:
    """Why a full-width row is malformed, or None."""
    for key in REQUEST_HEADER[:-1]:
        if not row[key]:
            return f"empty required field {key}"
    if row["reported_status"] not in REPORTED_STATUSES:
        return "reported_status not in the enum"
    for key in ("requested_at", "reported_at", "audit_at"):
        try:
            normalize_time(row[key])
        except ValueError:
            return f"{key}: unrecognized time"
    return None


def _load_file(
    dataset_dir: Path, name: str, source: RequestSource
) -> tuple[list[tuple[int, DeletionRequest]], list[RequestIssue]]:
    """Load one request file in file order, isolating bad rows (T86 item 2).

    A bad header still raises :class:`InputFormatError` (no row can be read). A bad row becomes a
    :class:`RequestIssue`; the rows around it load normally. A case ID that appears twice is an
    issue for that case and neither row is used (which one is right cannot be known). Each loaded
    request comes with its file line.
    """
    path = Path(dataset_dir) / name
    good: list[tuple[int, DeletionRequest]] = []
    issues: list[RequestIssue] = []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        header = next(reader, None)
        if header is None or tuple(header) != REQUEST_HEADER:
            raise InputFormatError(name, 1, "unexpected header")
        for values in reader:
            line = reader.line_num
            first = values[0] if values else ""
            readable = first if CASE_ID_RE.fullmatch(first) else None  # T87(5): exact shape, no trimming
            if len(values) != len(REQUEST_HEADER):
                issues.append(
                    RequestIssue(name, line, readable, f"expected {len(REQUEST_HEADER)} fields, found {len(values)}")
                )
                continue
            row = dict(zip(REQUEST_HEADER, values, strict=True))
            problem = _row_issue(row) if readable else "case_id not readable"
            if problem:
                issues.append(RequestIssue(name, line, readable, problem))
                continue
            good.append(
                (
                    line,
                    DeletionRequest(
                        case_id=row["case_id"],
                        email=make_identifier("email", row["email"], "email"),
                        requested_at=normalize_time(row["requested_at"]),
                        reported_status=row["reported_status"],  # type: ignore[arg-type]
                        reported_at=normalize_time(row["reported_at"]),
                        audit_at=normalize_time(row["audit_at"]),
                        request_text=row["request_text"],
                        source=source,
                    ),
                )
            )
    counts = Counter(r.case_id for _, r in good) + Counter(i.case_id for i in issues if i.case_id)
    dup = {c for c, n in counts.items() if n > 1}
    for line, r in good:
        if r.case_id in dup:
            issues.append(RequestIssue(name, line, r.case_id, "duplicate case_id"))
    return [(line, r) for line, r in good if r.case_id not in dup], issues


def load_requests_checked(dataset_dir: Path) -> tuple[tuple[DeletionRequest, ...], tuple[RequestIssue, ...]]:
    """Every loadable request of both files (test rows first, then sample rows, file order), and
    every row that could not be loaded.

    A case ID in both files (as a loaded row or as a malformed one) is an issue in each file at its
    own line, and no row of it is used (which file is right cannot be known). The issue in
    ``deletion_requests.csv`` keeps the case in a ``"test"`` run, where it becomes a
    MALFORMED_REQUEST row (T86 item 2), never a drop and never an answer from the other file.
    """
    test, ti = _load_file(dataset_dir, TEST_FILE, "test")
    sample, si = _load_file(dataset_dir, SAMPLE_FILE, "sample")
    in_test = {r.case_id for _, r in test} | {i.case_id for i in ti if i.case_id}
    in_sample = {r.case_id for _, r in sample} | {i.case_id for i in si if i.case_id}
    clash = in_test & in_sample
    clash_issues = [
        RequestIssue(own, line, r.case_id, f"case_id also in {other}")
        for own, other, rows in ((TEST_FILE, SAMPLE_FILE, test), (SAMPLE_FILE, TEST_FILE, sample))
        for line, r in rows
        if r.case_id in clash
    ]
    rows = [r for _, r in test + sample if r.case_id not in clash]
    return tuple(rows), tuple(ti + si + clash_issues)


def load_requests(dataset_dir: Path) -> tuple[DeletionRequest, ...]:
    """Every loadable request of both files (the pinned form; see :func:`load_requests_checked`)."""
    return load_requests_checked(dataset_dir)[0]


def case_number(case_id: str) -> tuple[int, str]:
    """Numeric sort key for output row order (9 before 10, not string order); see ``notes/CONTRACT_DRAFT.md`` A1."""
    head, _, tail = case_id.rpartition("_")
    return (int(tail), case_id) if tail.isdigit() else (-1, case_id)
