"""Reply and tool-input schemas, and the frozen dataclasses replies are parsed into.

There is no pydantic in the venv (G7a brief), so each schema is plain JSON Schema checked by GM's
:mod:`deletion_audit.model.schema_check`: enum and const values match exactly (developer ruling
T84), and a reply that breaks its schema never reaches these parsers (GM repairs it or gives up).
The parsers still re-validate, so a value built by hand cannot skip the check.

* :data:`FINAL_ANSWER_SCHEMA`: the answer format of every intent and loop turn (G3 section 5
  ``FinalAnswer``: ``IntentAnswer`` fields plus ``answers`` and ``cannot_answer``, and
  ``uncertain_reason``, the reason the refusal path ``UNCERTAIN`` must give; T95 item 2). One schema for
  every turn keeps the turn-1 request identical across modes (G3 section 3 item 3).
* :data:`AUDIT_CASE_INPUT`: ``audit_case``'s strict input; its ``intent`` admits only
  ``DELETION_REQUEST``, so calling it commits that intent (G3 section 1.2).
* :data:`VISION_SCHEMA`: one screenshot's structured reading (T7, T88).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, get_args

from ..model.schema_check import validate

IntentLabel = Literal["DELETION_REQUEST", "NOT_DELETION", "UNCERTAIN"]
INTENT_LABELS: tuple[str, ...] = get_args(IntentLabel)
RequestKind = Literal[
    "full_deletion", "verify_deletion", "scoped_deletion", "access", "correction", "export",
    "marketing_opt_out", "account_help", "other",
]
REQUEST_KINDS: tuple[str, ...] = get_args(RequestKind)
CannotReason = Literal["NO_EVIDENCE", "CONFLICTING", "UNREADABLE", "OUT_OF_SCOPE"]
CANNOT_REASONS: tuple[str, ...] = get_args(CannotReason)
Tri = Literal["yes", "no", "not_shown", "unreadable"]
TRI_VALUES: tuple[str, ...] = get_args(Tri)
STATE_FIELDS: tuple[str, ...] = ("sync_enabled", "restore_allowed", "marked_deleted", "download_available")
SUBJECT_FIELDS: tuple[str, ...] = ("subject_emails", "subject_phones", "subject_names", "subject_user_ids")


class SchemaError(ValueError):
    """A value that breaks its schema; the message names the first error, never the value."""


def _strings() -> dict[str, Any]:
    return {"type": "array", "items": {"type": "string"}}


_INTENT_FIELDS: dict[str, Any] = {
    "intent": {"type": "string", "enum": list(INTENT_LABELS)},
    "request_kind": {"type": "string", "enum": list(REQUEST_KINDS)},
    "language": {"type": "string"},
    "basis_quote": {"type": "string"},
    "instruction_like_text": {"type": "boolean"},
}

FINAL_ANSWER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        **_INTENT_FIELDS,
        "uncertain_reason": {"type": "string"},
        "answers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "oq_id": {"type": "string"},
                    "choice": {"type": "string"},
                    "evidence_ids": _strings(),
                    "note": {"type": "string"},
                },
                "required": ["oq_id", "choice", "evidence_ids", "note"],
                "additionalProperties": False,
            },
        },
        "cannot_answer": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "oq_id": {"type": "string"},
                    "reason": {"type": "string", "enum": list(CANNOT_REASONS)},
                },
                "required": ["oq_id", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": [*_INTENT_FIELDS, "uncertain_reason", "answers", "cannot_answer"],
    "additionalProperties": False,
}

AUDIT_CASE_INPUT: dict[str, Any] = {
    "type": "object",
    "properties": {**_INTENT_FIELDS, "intent": {"type": "string", "enum": ["DELETION_REQUEST"]}},
    "required": list(_INTENT_FIELDS),
    "additionalProperties": False,
}

_TRI = {"type": "string", "enum": list(TRI_VALUES)}
VISION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "records": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "shown_id": {"type": "string"},
                    **{f: _strings() for f in SUBJECT_FIELDS},
                    **{f: _TRI for f in STATE_FIELDS},
                },
                "required": ["shown_id", *SUBJECT_FIELDS, *STATE_FIELDS],
                "additionalProperties": False,
            },
        },
        "unreadable": _strings(),
        "instruction_like_text": {"type": "boolean"},
    },
    "required": ["records", "unreadable", "instruction_like_text"],
    "additionalProperties": False,
}


def check(value: Any, schema: Mapping[str, Any]) -> None:
    """Raise :class:`SchemaError` unless ``value`` matches ``schema`` (GM's exact checker)."""
    errors = validate(value, schema)
    if errors:
        raise SchemaError(f"{len(errors)} schema error(s); first: {errors[0]}")


@dataclass(frozen=True)
class IntentAnswer:
    """The intent fields of an answer or of an ``audit_case`` call."""

    intent: IntentLabel
    request_kind: str
    language: str
    basis_quote: str
    instruction_like_text: bool
    uncertain_reason: str = ""  # the refusal path's reason (T95 item 2); empty unless UNCERTAIN


@dataclass(frozen=True)
class OQAnswer:
    """One answer to an open question."""

    oq_id: str
    choice: str
    evidence_ids: tuple[str, ...]
    note: str


@dataclass(frozen=True)
class OQCannot:
    """An open question the model declined to answer, with its reason."""

    oq_id: str
    reason: str


@dataclass(frozen=True)
class FinalAnswer:
    """A schema-valid final answer (G3 section 5)."""

    intent: IntentAnswer
    answers: tuple[OQAnswer, ...]
    cannot_answer: tuple[OQCannot, ...]


def _intent(value: Mapping[str, Any]) -> IntentAnswer:
    return IntentAnswer(
        intent=value["intent"],
        request_kind=value["request_kind"],
        language=value["language"],
        basis_quote=value["basis_quote"],
        instruction_like_text=value["instruction_like_text"],
        uncertain_reason=value.get("uncertain_reason", ""),
    )


def parse_final(value: Any) -> FinalAnswer:
    """A :class:`FinalAnswer` from a reply's JSON value (re-validated first)."""
    check(value, FINAL_ANSWER_SCHEMA)
    return FinalAnswer(
        intent=_intent(value),
        answers=tuple(
            OQAnswer(a["oq_id"], a["choice"], tuple(a["evidence_ids"]), a["note"]) for a in value["answers"]
        ),
        cannot_answer=tuple(OQCannot(c["oq_id"], c["reason"]) for c in value["cannot_answer"]),
    )


def parse_audit_case_input(value: Any) -> IntentAnswer:
    """The committed intent from an ``audit_case`` tool input (re-validated first)."""
    check(value, AUDIT_CASE_INPUT)
    return _intent(value)


@dataclass(frozen=True)
class VisionRecord:
    """One record as one screenshot reading reported it (values exactly as the reply gave them)."""

    shown_id: str
    subject_emails: tuple[str, ...]
    subject_phones: tuple[str, ...]
    subject_names: tuple[str, ...]
    subject_user_ids: tuple[str, ...]
    sync_enabled: str
    restore_allowed: str
    marked_deleted: str
    download_available: str


@dataclass(frozen=True)
class VisionReading:
    """One reading of one screenshot."""

    records: tuple[VisionRecord, ...]
    unreadable: tuple[str, ...]
    instruction_like_text: bool


def parse_vision(value: Any) -> VisionReading:
    """A :class:`VisionReading` from a reply's JSON value (re-validated first)."""
    check(value, VISION_SCHEMA)
    return VisionReading(
        records=tuple(
            VisionRecord(
                shown_id=r["shown_id"],
                subject_emails=tuple(r["subject_emails"]),
                subject_phones=tuple(r["subject_phones"]),
                subject_names=tuple(r["subject_names"]),
                subject_user_ids=tuple(r["subject_user_ids"]),
                sync_enabled=r["sync_enabled"],
                restore_allowed=r["restore_allowed"],
                marked_deleted=r["marked_deleted"],
                download_available=r["download_available"],
            )
            for r in value["records"]
        ),
        unreadable=tuple(value["unreadable"]),
        instruction_like_text=value["instruction_like_text"],
    )
