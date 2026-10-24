"""Evidence parsing: every manifest file -> a :class:`FileParse` of observations and scopes.

Public API: :func:`parse_all`, :func:`parse_file`, :class:`Observation`, :class:`FileParse`,
:class:`EvidenceIndex`.

Status rules (``notes/INTERFACES.md`` section 4):

* ``OK``: the file yielded at least one observation or one declared scope.
* ``EMPTY``: a non-empty file that yielded neither. It is a failure, never "no records".
* ``UNKNOWN_FAMILY`` / ``AMBIGUOUS_FAMILY``: zero or several family sniffers matched.
* ``NEEDS_MODEL``: an image, or a PDF with no text layer.
* ``ERROR``: anything else that stopped the parse, with a reason that quotes no content.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from types import ModuleType
from typing import Sequence

from . import interpret
from .families._common import Content
from .manifest import ManifestError, load_manifest
from .model import (
    EvidenceIndex,
    FileParse,
    FileRef,
    Identifier,
    Locator,
    NeedsModel,
    Observation,
    ParseError,
    ParseStatus,
    SnapshotScope,
)
from .registry import FAMILIES, detect
from .sqlsafe import SqlSafetyError

__all__ = [
    "EvidenceIndex", "FileParse", "FileRef", "Identifier", "Locator", "ManifestError",
    "Observation", "SnapshotScope", "parse_all", "parse_file",
]


def _result(ref: FileRef, status: ParseStatus, family: str | None, detail: str | None,
            observations: tuple[Observation, ...] = (),
            scopes: tuple[SnapshotScope, ...] = ()) -> FileParse:
    """Build a FileParse for ``ref``."""
    return FileParse(file_id=ref.file_id, path=ref.path, family=family, status=status,
                     observations=observations, scopes=scopes, detail=detail)


def _read(ref: FileRef, dataset_dir: Path) -> bytes:
    """Read the file's bytes; the path must stay inside ``dataset_dir``."""
    root = Path(dataset_dir).resolve()
    path = (root / ref.path).resolve()
    if root not in path.parents:
        raise ParseError("path points outside the dataset directory")
    if not path.is_file():
        raise ParseError("file not found")
    return path.read_bytes()


def _error_detail(exc: BaseException) -> str:
    """A failure reason that never quotes file content."""
    if isinstance(exc, (ParseError, SqlSafetyError)):
        return str(exc)
    if isinstance(exc, sqlite3.Error):
        return f"SQL could not be executed ({type(exc).__name__})"
    if isinstance(exc, ValueError) and "timestamp" in str(exc):
        return f"bad time value: {exc}"
    return f"unexpected {type(exc).__name__}"


def parse_file(ref: FileRef, dataset_dir: Path,
               families: Sequence[ModuleType] = FAMILIES) -> FileParse:
    """Parse one manifest file. Never raises: every failure becomes a non-OK status."""
    try:
        data = _read(ref, dataset_dir)
    except (OSError, ParseError) as exc:
        return _result(ref, "ERROR", None, _error_detail(exc))
    if not data:
        return _result(ref, "ERROR", None, "file is zero bytes")
    content = Content(Path(dataset_dir) / ref.path, data)
    try:
        detection = detect(content, families)
    except Exception as exc:  # a sniffer failure is reported, not raised
        return _result(ref, "ERROR", None, "family detection failed: " + _error_detail(exc))
    if detection.family is None:
        return _result(ref, detection.status, None, detection.detail)
    name = detection.family.NAME
    try:
        raw_file = detection.family.parse(content)
        observations, scopes = interpret.interpret_file(ref, name, raw_file)
    except NeedsModel as exc:
        return _result(ref, "NEEDS_MODEL", name, str(exc))
    except Exception as exc:  # a bad file must not stop parse_all
        return _result(ref, "ERROR", name, _error_detail(exc))
    if not observations and not scopes:
        return _result(ref, "EMPTY", name, "non-empty file yielded no observation and no scope")
    return _result(ref, "OK", name, None, observations, scopes)


def parse_all(dataset_dir: Path) -> EvidenceIndex:
    """Parse every manifest row, in manifest order.

    Raises only when the manifest itself is missing or malformed.
    """
    refs = load_manifest(Path(dataset_dir))
    return EvidenceIndex(files={ref.file_id: parse_file(ref, Path(dataset_dir)) for ref in refs})
