"""Reading and writing ``output.csv`` files (prediction side; gold goes through gold.py).

A row whose ``steps_json`` does not parse to a JSON list is kept with ``parse_error`` set.
It is never turned into ``[]``: a failed parse is an explicit failure, not "nothing found"
(../CLAUDE.md section 3).
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .contract import STEP_KEYS
from .paths import SAMPLE_OUTPUT

OUTPUT_HEADER: list[str] = ["case_id", "deletion_status", "steps_json"]


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


def parse_steps(raw: str) -> tuple[list[Any] | None, str | None]:
    """Parse a ``steps_json`` cell; return (steps, None) or (None, error)."""
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        return None, f"invalid JSON: {exc}"
    if not isinstance(value, list):
        return None, f"steps_json is a JSON {type(value).__name__}, not a list"
    return value, None


def read_output(path: Path) -> OutputFile:
    """Read a prediction file. Refuses the gold file, which only gold.py may read."""
    if path.resolve() == SAMPLE_OUTPUT.resolve():
        raise PermissionError("sample_output.csv is gold; load it only through evaluation.gold")
    raw_bytes = path.read_bytes()
    issues: list[str] = []
    if b"\r\n" in raw_bytes:
        issues.append("CRLF line endings (the sample file uses LF)")
    if raw_bytes.startswith(b"\xef\xbb\xbf"):
        issues.append("UTF-8 BOM present")
    rows: dict[str, OutputRow] = {}
    order: list[str] = []
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if header != OUTPUT_HEADER:
            issues.append(f"header is {header!r}, expected {OUTPUT_HEADER!r}")
        for lineno, record in enumerate(reader, start=2):
            if len(record) != 3:
                issues.append(f"record {lineno}: {len(record)} fields, expected 3")
                if not record:
                    continue
                record = (record + ["", "", ""])[:3]
            case_id, status, raw = record
            if case_id in rows:
                issues.append(f"record {lineno}: duplicate case_id {case_id!r}")
                continue
            steps, err = parse_steps(raw)
            rows[case_id] = OutputRow(case_id, status, steps, raw, err)
            order.append(case_id)
    return OutputFile(rows=rows, order=order, issues=issues, header=header)


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
