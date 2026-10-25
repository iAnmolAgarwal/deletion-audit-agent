"""Typed loaders for the CSV inputs: ``system_activity.csv``, ``user_identities.csv`` and
``user_audit_log.csv``.

* Times go through the evidence layer's one time normalizer and keep their exact seconds.
* IDs are copied as written. Identifiers go through the one identifier normalizer and keep
  their raw value.
* Empty fields become None. An empty required field, a wrong field count, a bad header or a
  bad time raises :class:`InputFormatError` naming the file and line; no row is skipped.
* Rows come back in file order. Which rows belong to which person is not decided here.
"""
from __future__ import annotations

import csv
from collections.abc import Callable, Iterator
from pathlib import Path

from ..evidence.interpret import make_identifier, normalize_time
from ..evidence.model import Identifier, IdKind
from .model import ActivityRow, AuditLogRow, IdentityRow, InputFormatError

__all__ = [
    "ActivityRow", "AuditLogRow", "IdentityRow", "InputFormatError",
    "load_activity", "load_audit_log", "load_identities",
]

ACTIVITY_FILE = "system_activity.csv"
IDENTITIES_FILE = "user_identities.csv"
AUDIT_LOG_FILE = "user_audit_log.csv"

ACTIVITY_HEADER = ("activity_id", "event_time", "event_type", "source_system",
                   "target_system", "resource_id", "reported_result", "details")
IDENTITIES_HEADER = ("user_id", "name", "email", "phone", "email_hash", "updated_at")
AUDIT_LOG_HEADER = ("audit_id", "user_id", "event_time", "field_name", "old_value", "new_value")
IDENTIFIER_FIELDS: dict[str, IdKind] = {"email": "email", "phone": "phone",
                                        "email_hash": "email_hash"}



class _Fields:
    """Accessors over one CSV record that raise InputFormatError with file and line."""

    def __init__(self, file_name: str, line: int, values: dict[str, str]) -> None:
        """Wrap one record."""
        self.file_name, self.line, self.values = file_name, line, values

    def required(self, name: str) -> str:
        """A field that must be non-empty, copied as written."""
        value = self.values[name]
        if value == "":
            raise InputFormatError(self.file_name, self.line, f"empty required field {name}")
        return value

    def optional(self, name: str) -> str | None:
        """A field that may be empty; empty becomes None."""
        return self.values[name] or None

    def time(self, name: str) -> str:
        """A required time field, normalized to exact-second UTC."""
        raw = self.required(name)
        try:
            return normalize_time(raw)
        except ValueError as exc:
            raise InputFormatError(self.file_name, self.line, f"{name}: {exc}") from None

    def identifier(self, kind: IdKind, name: str) -> Identifier | None:
        """An optional identifier field."""
        raw = self.optional(name)
        return None if raw is None else make_identifier(kind, raw, name)


def _records(dataset_dir: Path, file_name: str, header: tuple[str, ...]) -> Iterator[_Fields]:
    """Yield every data record of a CSV file after checking its header and field counts."""
    path = Path(dataset_dir) / file_name
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        first = next(reader, None)
        if first is None or tuple(first) != header:
            raise InputFormatError(file_name, 1, "unexpected header")
        for values in reader:
            if len(values) != len(header):
                raise InputFormatError(file_name, reader.line_num,
                                       f"expected {len(header)} fields, found {len(values)}")
            yield _Fields(file_name, reader.line_num, dict(zip(header, values, strict=True)))


def _load[Row](dataset_dir: Path, file_name: str, header: tuple[str, ...],
               build: Callable[[_Fields], Row]) -> tuple[Row, ...]:
    """Load a CSV file into typed rows."""
    return tuple(build(record) for record in _records(dataset_dir, file_name, header))


def _activity(f: _Fields) -> ActivityRow:
    """Build one ActivityRow."""
    return ActivityRow(
        activity_id=f.required("activity_id"),
        event_time=f.time("event_time"),
        event_type=f.required("event_type"),
        source_system=f.required("source_system"),
        target_system=f.required("target_system"),
        resource_id=f.optional("resource_id"),
        reported_result=f.optional("reported_result"),
        details=f.values["details"],
    )


def _identity(f: _Fields) -> IdentityRow:
    """Build one IdentityRow."""
    return IdentityRow(
        user_id=f.required("user_id"),
        name=f.optional("name"),
        email=f.identifier("email", "email"),
        phone=f.identifier("phone", "phone"),
        email_hash=f.optional("email_hash"),
        updated_at=f.time("updated_at"),
    )


def _audit(f: _Fields) -> AuditLogRow:
    """Build one AuditLogRow; identifier fields also get typed old/new identifiers."""
    field_name = f.required("field_name")
    kind = IDENTIFIER_FIELDS.get(field_name)
    return AuditLogRow(
        audit_id=f.required("audit_id"),
        user_id=f.required("user_id"),
        event_time=f.time("event_time"),
        field_name=field_name,
        old_value=f.optional("old_value"),
        new_value=f.optional("new_value"),
        old_identifier=f.identifier(kind, "old_value") if kind else None,
        new_identifier=f.identifier(kind, "new_value") if kind else None,
    )


def load_activity(dataset_dir: Path) -> tuple[ActivityRow, ...]:
    """Load ``system_activity.csv`` in file order."""
    return _load(dataset_dir, ACTIVITY_FILE, ACTIVITY_HEADER, _activity)


def load_identities(dataset_dir: Path) -> tuple[IdentityRow, ...]:
    """Load ``user_identities.csv`` in file order."""
    return _load(dataset_dir, IDENTITIES_FILE, IDENTITIES_HEADER, _identity)


def load_audit_log(dataset_dir: Path) -> tuple[AuditLogRow, ...]:
    """Load ``user_audit_log.csv`` in file order."""
    return _load(dataset_dir, AUDIT_LOG_FILE, AUDIT_LOG_HEADER, _audit)
