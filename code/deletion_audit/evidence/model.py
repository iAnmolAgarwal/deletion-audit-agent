"""Data model of the evidence layer (pinned in ``notes/INTERFACES.md`` section 2).

Two layers live here:

* the syntax layer (:class:`RawRecord`, :class:`RawScope`, :class:`RawFile`), which family
  parsers emit with every value kept as the raw string written in the file;
* the interpreted layer (:class:`Identifier`, :class:`Locator`, :class:`SnapshotScope`,
  :class:`Observation`, :class:`FileParse`, :class:`EvidenceIndex`), which only
  ``interpret.py`` builds from the syntax layer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Mapping

IdKind = Literal["email", "phone", "email_hash", "user_id", "name", "subject_reference", "other"]
LocatorKind = Literal["line", "sql_row", "json_path", "pdf_page", "image"]
ScopeSource = Literal["sql_snapshot_scope", "full_collection"]
ParseStatus = Literal["OK", "EMPTY", "UNKNOWN_FAMILY", "AMBIGUOUS_FAMILY", "ERROR", "NEEDS_MODEL"]


class ParseError(ValueError):
    """A file could not be parsed. The message names a position or reason, never file content."""


class NeedsModel(Exception):
    """The file carries no machine-readable text (an image, or a PDF with no text layer)."""


@dataclass(frozen=True)
class FileRef:
    """One row of ``dataset/evidence_files.csv``; ``captured_at`` is normalized to ``...Z``."""

    file_id: str
    path: str
    origin: str
    captured_at: str


# --------------------------------------------------------------------------- syntax layer
@dataclass(frozen=True)
class RawRecord:
    """One record as a family parser read it: syntax only, every value a raw string.

    ``fields`` holds every field of the record. Nested JSON is flattened to dotted keys
    (``profile.email``, ``hits.documents[0].email``); JSON ``null`` and SQL ``NULL`` are
    the string ``"null"``, booleans ``"true"``/``"false"``.
    """

    locator_kind: LocatorKind
    ref: str
    fields: Mapping[str, str]
    record_time: str | None
    trace_id: str | None
    source_system: str | None      # service, data_store, origin_system or system as written
    container: str | None          # table or collection name as written
    event: str | None
    text: str | None = None        # page text for PDFs; other families leave it None
    scope_index: int | None = None  # index into RawFile.scopes when the parser knows it


@dataclass(frozen=True)
class RawScope:
    """A scope declaration as written in the file (systems and time still raw)."""

    locator_kind: LocatorKind
    ref: str
    systems: tuple[str, ...]
    as_of: str | None
    source: ScopeSource
    collection: str | None


@dataclass(frozen=True)
class RawFile:
    """Everything a family parser extracted from one file."""

    records: tuple[RawRecord, ...]
    scopes: tuple[RawScope, ...] = ()


# --------------------------------------------------------------------------- interpreted layer
@dataclass(frozen=True)
class Identifier:
    """An identifier stored in, or used to look up, a record."""

    kind: IdKind
    value: str      # normalized by interpret.normalize_identifier
    raw: str        # exactly as written in the file
    field: str      # source field, e.g. "lookup_key", "profile.email", "message_text"


@dataclass(frozen=True)
class Locator:
    """Where in a file a record or scope sits."""

    file_id: str
    kind: LocatorKind
    ref: str        # "L42", "customer_profiles#rowid=7", "$.snapshots[3].records[0]", "p2"


@dataclass(frozen=True)
class SnapshotScope:
    """A scope a file declares it covers in full."""

    file_id: str
    systems: frozenset[str]
    as_of: str | None
    source: ScopeSource
    collection: str | None
    locator: Locator


@dataclass(frozen=True)
class Observation:
    """One record of one evidence file, interpreted into typed fields."""

    file_id: str
    family: str
    locator: Locator
    captured_at: str
    record_time: str | None
    system_id: str | None
    resource_id: str | None
    record_identifiers: frozenset[Identifier]
    lookup_identifiers: frozenset[Identifier]
    trace_id: str | None
    scope: SnapshotScope | None
    event: str | None
    attrs: Mapping[str, str]
    text: str | None = None


@dataclass(frozen=True)
class FileParse:
    """The parse result of one manifest row."""

    file_id: str
    path: str
    family: str | None
    status: ParseStatus
    observations: tuple[Observation, ...]
    scopes: tuple[SnapshotScope, ...]
    detail: str | None

    @property
    def ok(self) -> bool:
        """True only for status ``OK``."""
        return self.status == "OK"


@dataclass(frozen=True)
class EvidenceIndex:
    """Every manifest row's :class:`FileParse`, in manifest order."""

    files: Mapping[str, FileParse] = field(default_factory=dict)

    def observations(self) -> tuple[Observation, ...]:
        """All observations, files in manifest order, then locator order within a file."""
        return tuple(o for fp in self.files.values() for o in fp.observations)

    def scopes(self) -> tuple[SnapshotScope, ...]:
        """All declared scopes, in the same order."""
        return tuple(s for fp in self.files.values() for s in fp.scopes)

    def failures(self) -> tuple[FileParse, ...]:
        """Every FileParse whose status is not OK, NEEDS_MODEL included."""
        return tuple(fp for fp in self.files.values() if not fp.ok)
