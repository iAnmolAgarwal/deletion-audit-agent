"""Row types of the three CSV inputs (pinned in ``notes/INTERFACES.md`` section 3)."""
from __future__ import annotations

from dataclasses import dataclass

from ..evidence.model import Identifier


class InputFormatError(ValueError):
    """A CSV input is malformed. The message names the file and line."""

    def __init__(self, file_name: str, line: int, reason: str) -> None:
        """Record where the problem is and why."""
        super().__init__(f"{file_name} line {line}: {reason}")
        self.file_name = file_name
        self.line = line
        self.reason = reason


@dataclass(frozen=True)
class ActivityRow:
    """One row of ``dataset/system_activity.csv``."""

    activity_id: str
    event_time: str
    event_type: str
    source_system: str
    target_system: str
    resource_id: str | None
    reported_result: str | None
    details: str


@dataclass(frozen=True)
class IdentityRow:
    """One row of ``dataset/user_identities.csv``."""

    user_id: str
    name: str | None
    email: Identifier | None
    phone: Identifier | None
    email_hash: str | None
    updated_at: str


@dataclass(frozen=True)
class AuditLogRow:
    """One row of ``dataset/user_audit_log.csv``; ``audit_id`` is kept because it can be cited."""

    audit_id: str
    user_id: str
    event_time: str
    field_name: str
    old_value: str | None
    new_value: str | None
    old_identifier: Identifier | None
    new_identifier: Identifier | None
