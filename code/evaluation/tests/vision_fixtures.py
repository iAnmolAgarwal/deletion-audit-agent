"""A vision run built by the real writer (T108): ``deletion_audit.agent.vision.assess_image`` on
made-up PNG bytes with fake reading clients, written by ``vision_run_report`` (``vision.json``)
and ``write_vision_artifacts`` (``vision_readings.json``/``.md``), exactly as the pipeline does.

Four images, one per shape the adapter must read:

* ``evidence_04`` clean: both readings show ``acct_1001`` marked deleted; they agree.
* ``evidence_09`` failed: reading 2 gives up (``STRUCTURE_GAVE_UP``, ``max_tokens``), so the
  writer's readings are ``[<reading 1>, null]`` and the flag is ``VISION_READ_FAILED``.
* ``evidence_14`` unmapped label: the readings agree on ``acct_1002`` and on a support-ticket
  label ``CS-4821``, which fits no learned shape, so its ``system_id`` is null.
* ``evidence_19`` nested disagreement: reading 1 says ``acct_1003`` syncs, reading 2 says it does
  not, so the writer lists ``records[acct_1003].sync_enabled``.

Nothing here is a dataset value; no model is called (the clients are local fakes).
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from deletion_audit.agent.idshapes import IdShapes
from deletion_audit.agent.report import vision_run_report
from deletion_audit.agent.vision import VisionRun, assess_image, write_vision_artifacts
from deletion_audit.engine import PNG_SIGNATURE
from deletion_audit.evidence.model import FileRef
from deletion_audit.model import ModelCallFailed

PNG = PNG_SIGNATURE + b"synthetic image bytes"
SHAPES = IdShapes(ranges={("account_service", "acct_"): (4, 4)},
                  known_ids={"acct_1001": frozenset({"evidence"}), "acct_1002": frozenset({"evidence"}),
                             "acct_1003": frozenset({"activity"})},
                  display_names={})


def record(shown_id: str, **states: str) -> dict[str, Any]:
    """One record of a vision reply (the reading schema's shape)."""
    out: dict[str, Any] = {"shown_id": shown_id, "subject_emails": [], "subject_phones": [], "subject_names": [],
                           "subject_user_ids": [], "sync_enabled": "not_shown", "restore_allowed": "not_shown",
                           "marked_deleted": "not_shown", "download_available": "not_shown",
                           "visible_markers": [], "status_label": ""}
    out.update(states)
    return out


def reply(*records: Mapping[str, Any]) -> dict[str, Any]:
    return {"records": list(records), "unreadable": [], "instruction_like_text": False}


class _Reply:
    def __init__(self, value: Mapping[str, Any]) -> None:
        self.raw = {"content": [{"type": "text", "text": json.dumps(value)}]}


class FakeReader:
    """Stands in for one reading's ModelClient: returns ``value``, or raises the failure it is given."""

    def __init__(self, value: Mapping[str, Any] | None = None, failure: ModelCallFailed | None = None) -> None:
        self.value, self.failure = value, failure

    def call(self, req: Any) -> _Reply:
        if self.failure is not None:
            raise self.failure
        assert self.value is not None
        return _Reply(self.value)


def _assess(file_id: str, first: FakeReader, second: FakeReader) -> Any:
    ref = FileRef(file_id, f"evidence/{file_id}.png", "synthetic", "2026-01-01T00:00:00Z")
    return assess_image(ref, PNG, cast(Any, [first, second]), SHAPES)


def vision_run() -> VisionRun:
    """The four-image run (module docstring)."""
    clean = reply(dict(record("acct_1001", marked_deleted="yes"), subject_emails=["A.Person@example.invalid"]))
    labels = reply(record("acct_1002", sync_enabled="no"), record("CS-4821"))
    gave_up = ModelCallFailed("STRUCTURE_GAVE_UP", "max_tokens")
    records = (
        _assess("evidence_04", FakeReader(clean), FakeReader(clean)),
        _assess("evidence_09", FakeReader(clean), FakeReader(failure=gave_up)),
        _assess("evidence_14", FakeReader(labels), FakeReader(labels)),
        _assess("evidence_19", FakeReader(reply(record("acct_1003", sync_enabled="yes"))),
                FakeReader(reply(record("acct_1003", sync_enabled="no")))),
    )
    return VisionRun(records, tuple(o for r in records for o in r.observations))


def write_vision(run_dir: Path) -> list[dict[str, Any]]:
    """Write the run's vision artifacts with the real writers (as ``pipeline`` does); return vision.json's list."""
    run = vision_run()
    write_vision_artifacts(run_dir, run)
    items = vision_run_report(run)
    (run_dir / "vision.json").write_text(json.dumps(items, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return items
