"""Loader for ``dataset/evidence_files.csv``."""
from __future__ import annotations

import csv
from pathlib import Path

from .interpret import normalize_time
from .model import FileRef

MANIFEST_NAME = "evidence_files.csv"
MANIFEST_HEADER = ["file_id", "file_path", "origin", "captured_at"]


class ManifestError(ValueError):
    """The manifest is missing or malformed."""


def load_manifest(dataset_dir: Path) -> tuple[FileRef, ...]:
    """Read the manifest in file order.

    Raises :class:`ManifestError` (or ``FileNotFoundError`` when the file is absent) because
    without the manifest there is no list of files to report on.
    """
    path = Path(dataset_dir) / MANIFEST_NAME
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        header = next(reader, None)
        if header != MANIFEST_HEADER:
            raise ManifestError(f"{MANIFEST_NAME}: unexpected header")
        refs: list[FileRef] = []
        seen: set[str] = set()
        for row in reader:
            refs.append(_row_to_ref(row, reader.line_num, seen))
    return tuple(refs)


def _row_to_ref(row: list[str], line: int, seen: set[str]) -> FileRef:
    """Validate one manifest row and build its FileRef."""
    if len(row) != len(MANIFEST_HEADER) or not all(row):
        raise ManifestError(f"{MANIFEST_NAME} line {line}: expected 4 non-empty fields")
    file_id, file_path, origin, captured_at = row
    if file_id in seen:
        raise ManifestError(f"{MANIFEST_NAME} line {line}: duplicate file_id {file_id}")
    seen.add(file_id)
    try:
        captured = normalize_time(captured_at)
    except ValueError as exc:
        raise ManifestError(f"{MANIFEST_NAME} line {line}: {exc}") from None
    return FileRef(file_id=file_id, path=file_path, origin=origin, captured_at=captured)
