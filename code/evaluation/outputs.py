"""Reading and writing ``output.csv`` files (prediction side; gold goes through gold.py).

A row whose ``steps_json`` does not parse to a JSON list is kept with ``parse_error`` set.
It is never turned into ``[]``: a failed parse is an explicit failure, not "nothing found"
(../CLAUDE.md section 3).

Gold guard (verifier finding B1, developer ruling T47): :func:`read_output` refuses the gold
file by identity, not by path spelling. A file is the gold file when ``os.path.samefile``
says so (case variants on a case-insensitive disk, hard links, symlinks) or when its bytes
have the same sha256 as ``sample_output.csv`` (copies). The sha256 is computed only when the
two sizes are equal, in memory; the digest is never stored, printed or logged. The guard
has no unlock route (T99 C): the HOLDOUT EVALUATION RUN scores through ``gold.load_gold``.
Limit: a copy with even one byte changed is not caught by this guard.

Field size (verifier F3, ruling T72): ``csv``'s default field limit (131072 characters)
crashed the whole read on one oversized ``steps_json`` cell. :func:`read_output` raises the
limit to :data:`FIELD_SIZE_CAP` (16 MiB) for the duration of the read and restores the
process value afterwards. 16 MiB is about 600 times the largest plausible honest row (a
100-step ``steps_json`` is about 25 KB) and still bounds memory per field. A record that
still fails to parse becomes a hard issue, never a crash, and the read goes on.

Decoding (verifier M1, ruling T80): the file's bytes are read ONCE. The same bytes give
``OutputFile.sha256`` (what ``evaluate.py score`` records), feed a second gold-identity
check, and are decoded as UTF-8 with ``surrogateescape``, so an invalid byte cannot raise.
A record holding an undecodable byte is skipped with a hard issue that names its record
number, never its value.

Case names (T72 note 1): messages built from a file name a case only by a value matching
:data:`CASE_ID_RE` (``case_`` then ASCII digits); any other first-column value is named by
its record number (``<record N>``, the header being record 1), never by the value.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import paths
from .contract import STEP_KEYS
from .gold import HoldoutLockedError

OUTPUT_HEADER: list[str] = ["case_id", "deletion_status", "steps_json"]
FIELD_SIZE_CAP: int = 16 * 1024 * 1024  # characters per CSV field while reading a prediction file
CASE_ID_RE: re.Pattern[str] = re.compile(r"case_[0-9]+", re.ASCII)


def is_case_name(value: str) -> bool:
    """True when ``value`` is fully ``case_`` plus ASCII digits (safe to print as a case name)."""
    return isinstance(value, str) and CASE_ID_RE.fullmatch(value) is not None


def case_label(value: str, record_no: int | None) -> str:
    """``value`` if it is a case name, else ``<record N>`` (never the value itself)."""
    if is_case_name(value):
        return value
    return f"<record {record_no}>" if record_no is not None else "<unnamed record>"


@dataclass(frozen=True)
class OutputRow:
    """One predicted row. ``steps`` is None when ``steps_json`` failed to parse to a list."""

    case_id: str
    status: str
    steps: list[Any] | None
    raw_steps: str
    parse_error: str | None = None


@dataclass
class OutputFile:
    """A parsed output file: rows by case, plus file-level problems in file order."""

    rows: dict[str, OutputRow]
    order: list[str]
    issues: list[str] = field(default_factory=list)
    header: list[str] | None = None
    record_no: dict[str, int] = field(default_factory=dict)  # case_id -> CSV record number (header = 1)
    sha256: str | None = None  # sha256 of the exact bytes that were parsed


def parse_steps(raw: str) -> tuple[list[Any] | None, str | None]:
    """Parse a ``steps_json`` cell; return (steps, None) or (None, error)."""
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        return None, f"invalid JSON: {exc}"
    if not isinstance(value, list):
        return None, f"steps_json is a JSON {type(value).__name__}, not a list"
    return value, None


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 16), b""):
            h.update(block)
    return h.hexdigest()


def is_gold_file(path: Path, data: bytes | None = None) -> bool:
    """True when ``path`` is the gold file (``paths.SAMPLE_OUTPUT``, read at call time).

    Without ``data`` (the check before reading): same file by ``os.path.samefile`` (any
    spelling, hard link or symlink), or the same bytes by sha256 (a copy); only ``stat`` is
    used unless the sizes are equal. A missing candidate returns False (the read then fails).

    With ``data`` (the check on the bytes actually read; T81): the held bytes are compared
    FIRST, by size and sha256, so nothing that happens to ``path`` afterwards (renamed,
    removed) can make the check skip them. It fails closed: any error while reading the
    gold side counts as gold, except a gold file that does not exist at all (nothing to
    protect).
    """
    gold = paths.SAMPLE_OUTPUT
    if data is not None:
        try:
            if len(data) != os.stat(gold).st_size:
                return False
            return hashlib.sha256(data).hexdigest() == _sha256(gold)
        except FileNotFoundError:
            return False
        except Exception:  # noqa: BLE001 -- fail closed: cannot prove the held bytes are not gold
            return True
    try:
        if os.path.samefile(path, gold):
            return True
        if os.stat(path).st_size != os.stat(gold).st_size:
            return False
    except OSError:  # a missing gold file or candidate: nothing to protect or compare
        return False
    return _sha256(path) == _sha256(gold)


def _has_bad_bytes(fields: list[str]) -> bool:
    """True when a decoded field holds a surrogate-escaped (undecodable) byte."""
    return any("\udc80" <= ch <= "\udcff" for f in fields for ch in f)


def read_output(path: Path) -> OutputFile:
    """Read a prediction file. Refuses the gold file, which only gold.py may read; there is no
    unlock route here (T99 C).

    Raises:
        HoldoutLockedError: ``path`` is the gold file (see :func:`is_gold_file`).
    """
    def refuse() -> None:
        raise HoldoutLockedError(
            f"{path} is the gold file (sample_output.csv by identity or content); load gold only "
            "through evaluation.gold")

    if is_gold_file(path):
        refuse()
    raw_bytes = path.read_bytes()  # the only read: hash, gold check and parse all use these bytes
    if is_gold_file(path, raw_bytes):  # the file changed into gold after the check
        refuse()
    issues: list[str] = []
    if b"\r\n" in raw_bytes:
        issues.append("CRLF line endings (the sample file uses LF)")
    if raw_bytes.startswith(b"\xef\xbb\xbf"):
        issues.append("UTF-8 BOM present")
    rows: dict[str, OutputRow] = {}
    order: list[str] = []
    record_no: dict[str, int] = {}
    header: list[str] | None = None
    previous_limit = csv.field_size_limit(FIELD_SIZE_CAP)
    try:
        text = raw_bytes.removeprefix(b"\xef\xbb\xbf").decode("utf-8", errors="surrogateescape")
        with io.StringIO(text, newline="") as f:
            reader = csv.reader(f)
            lineno = 0
            while True:
                lineno += 1
                try:
                    record = next(reader)
                except StopIteration:
                    break
                except csv.Error as exc:  # e.g. a field over FIELD_SIZE_CAP: an issue, never a crash
                    issues.append(f"record {lineno}: CSV error ({exc}); record skipped, and the records "
                                  "after it may be misaligned")
                    continue
                if _has_bad_bytes(record):  # invalid UTF-8: an issue for this record, never a crash
                    issues.append(f"record {lineno}: invalid UTF-8 bytes; record skipped")
                    continue
                if lineno == 1:
                    header = record
                    if header != OUTPUT_HEADER:
                        issues.append(f"header: not {','.join(OUTPUT_HEADER)} ({len(header)} column(s))")
                    continue
                if len(record) != 3:
                    issues.append(f"record {lineno}: {len(record)} fields, expected 3")
                    if not record:
                        continue
                    record = (record + ["", "", ""])[:3]
                case_id, status, raw = record
                if case_id in rows:
                    shown = case_id if is_case_name(case_id) else "(value not shown)"
                    issues.append(f"record {lineno}: duplicate case_id {shown}")
                    continue
                steps, err = parse_steps(raw)
                rows[case_id] = OutputRow(case_id, status, steps, raw, err)
                order.append(case_id)
                record_no[case_id] = lineno
    finally:
        csv.field_size_limit(previous_limit)
    return OutputFile(rows=rows, order=order, issues=issues, header=header, record_no=record_no,
                      sha256=hashlib.sha256(raw_bytes).hexdigest())


def serialize_steps(steps: list[dict[str, Any]]) -> str:
    """Compact JSON in the README key order (matches 17 of 22 DEV gold rows byte for byte)."""
    ordered = [{k: s[k] for k in STEP_KEYS if k in s} | {k: v for k, v in s.items() if k not in STEP_KEYS}
               for s in steps]
    return json.dumps(ordered, separators=(",", ":"))


def write_output(path: Path, rows: Iterable[tuple[str, str, list[dict[str, Any]]]]) -> int:
    """Write ``(case_id, status, steps)`` rows with LF endings; return the row count."""
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(OUTPUT_HEADER)
        for case_id, status, steps in rows:
            writer.writerow([case_id, status, serialize_steps(steps)])
            n += 1
    return n
