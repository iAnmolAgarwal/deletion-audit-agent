"""The typed open questions the agent may pose for one case (G3 section 1.0, a closed list).

Each question names the only slot an accepted answer may fill (``slot``); ``None`` means the
answer is recorded but changes no step, because a ruling already settles that fact.

* ``INTENT_UNCERTAIN``: turn 1 committed ``UNCERTAIN`` (or its quote failed the code check).
  Choices DELETION_REQUEST, NOT_DELETION; slot ``intent``.
* ``INTENT_CROSSCHECK``: the committed label disagrees with the intake rows (T71 Q10).
  Choices DELETION_REQUEST, NOT_DELETION; slot ``intent``.
* ``IMAGE_FIELD_UNREADABLE``: a merged image reading leaves a state field of one of the case's
  records unreadable. Choices yes, no; slot ``image_field:<file>:<resource>:<field>``.
* ``IMAGE_SUBJECT_CONFLICT``: the engine flagged an image whose subject is not the catalog's
  person. Choices SUBJECT_DIFFERS, SUBJECT_MATCHES; slot None (T71 Q11 keeps the record either way).
* ``UNKNOWN_FORMAT``: a non-image file this case depends on did not parse. Choices ADDS_NO_RECORD,
  CANNOT_READ; slot None (answers never add observations: not built, 0 such files today).

``oq_id`` is ``q_`` plus the first 12 hex characters of sha256 over (case, type, subject): stable,
never a row index (G3 section 5).

``INSTRUCTION_LIKE_TEXT`` is never posed: G3 section 1.0 calls it "a flag only, never a step" with
no tool that helps, so the loop raises the flag ``INSTRUCTION_LIKE_TEXT`` instead of a question
that could change nothing.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from typing import get_args

from ..engine import OpenQuestion, OpenQuestionType
from ..record import CaseRecord
from .schemas import TRI_VALUES

OQ_TYPES: tuple[str, ...] = get_args(OpenQuestionType)
INTENT_TYPES: frozenset[str] = frozenset({"INTENT_UNCERTAIN", "INTENT_CROSSCHECK"})
INTENT_CHOICES: tuple[str, ...] = ("DELETION_REQUEST", "NOT_DELETION")
#: Readable values of an image state field (``unreadable`` and ``not_shown`` are not answers).
FIELD_CHOICES: tuple[str, ...] = tuple(v for v in TRI_VALUES if v in ("yes", "no"))


def oq_id(case_id: str, oq_type: str, subject: str) -> str:
    """The stable ID of one question."""
    digest = hashlib.sha256(f"{case_id}\x1f{oq_type}\x1f{subject}".encode()).hexdigest()
    return "q_" + digest[:12]


def question(case_id: str, oq_type: OpenQuestionType, subject: str, choices: Iterable[str],
             slot: str | None) -> OpenQuestion:
    """One :class:`~deletion_audit.engine.OpenQuestion`."""
    return OpenQuestion(oq_id(case_id, oq_type, subject), oq_type, subject, tuple(choices), slot)


def intent_question(case_id: str, oq_type: OpenQuestionType) -> OpenQuestion:
    """An intent question (subject ``request``; slot ``intent``)."""
    return question(case_id, oq_type, "request", INTENT_CHOICES, "intent")


def record_questions(record: CaseRecord, unreadable: Mapping[str, Iterable[tuple[str, str]]],
                     image_files: frozenset[str] = frozenset()) -> tuple[OpenQuestion, ...]:
    """The evidence questions for one engine record.

    ``unreadable`` maps an image file ID to its ``(resource_id, field)`` pairs whose merged value is
    unreadable; only the case's own resources raise a question. ``image_files`` are the files the
    vision step owns: an unread image is not an unknown format, so it raises no UNKNOWN_FORMAT.
    """
    cid = record.case_id
    mine = {r.key.resource_id for r in record.resources}
    out: list[OpenQuestion] = []
    for file_id in sorted(unreadable):
        for rid, name in sorted(set(unreadable[file_id])):
            if rid in mine:
                subject = f"{file_id}:{rid}:{name}"
                out.append(question(cid, "IMAGE_FIELD_UNREADABLE", subject, FIELD_CHOICES, f"image_field:{subject}"))
    conflicts = sorted({f.detail.split(":", 1)[0] for f in record.flags if f.code == "IMAGE_SUBJECT_CONFLICT"})
    for rid in conflicts:
        out.append(question(cid, "IMAGE_SUBJECT_CONFLICT", rid, ("SUBJECT_DIFFERS", "SUBJECT_MATCHES"), None))
    for file_id in sorted(record.failed_dependencies - image_files):
        out.append(question(cid, "UNKNOWN_FORMAT", file_id, ("ADDS_NO_RECORD", "CANNOT_READ"), None))
    return tuple(out)
