"""Write ``output.csv``: one row per case, numeric case order, LF endings, compact JSON.

Basis: G1 serialization facts (``notes/CONTRACT_DRAFT.md`` section 1): UTF-8, no BOM, LF,
``csv.writer`` QUOTE_MINIMAL, ``json.dumps(..., separators=(",", ":"))`` in the README key order
reproduces 17/22 DEV gold lines byte for byte. Rows are in numeric case order, the order of
``deletion_requests.csv`` (G1 A1; ``code/evaluation/coherence`` accepts string or numeric order).
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from collections.abc import Iterable, Sequence
from pathlib import Path

from ..inputs.requests import case_number
from .model import Step

OUTPUT_HEADER = ("case_id", "deletion_status", "steps_json")


def steps_json(steps: Sequence[Step]) -> str:
    """Compact JSON array of the steps, README key order."""
    return json.dumps([s.as_json() for s in steps], separators=(",", ":"), ensure_ascii=False)


def render_output(rows: Iterable[tuple[str, str, Sequence[Step]]]) -> bytes:
    """The bytes of ``output.csv`` for ``(case_id, status, steps)`` rows, sorted by case number."""
    return render_text_rows((case_id, status, steps_json(steps)) for case_id, status, steps in rows)


def render_text_rows(rows: Iterable[tuple[str, str, str]]) -> bytes:
    """The bytes of ``output.csv`` for ``(case_id, status, steps_json text)`` rows, sorted by case
    number; a row taken from another output file is written byte for byte (T118 assembly)."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(OUTPUT_HEADER)
    for case_id, status, text in sorted(rows, key=lambda r: case_number(r[0])):
        writer.writerow([case_id, status, text])
    return buf.getvalue().encode("utf-8")


def write_output(rows: Iterable[tuple[str, str, Sequence[Step]]], path: Path) -> str:
    """Write ``output.csv`` atomically and return its sha256."""
    return write_output_bytes(render_output(rows), path)


def write_output_bytes(data: bytes, path: Path) -> str:
    """Write rendered ``output.csv`` bytes atomically and return their sha256."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)
    return hashlib.sha256(data).hexdigest()
