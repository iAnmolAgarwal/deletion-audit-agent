"""The five read-only tools the harness binds to one case.

* ``audit_case`` (modes A+ and A): commits the intent and returns the engine's brief.
* ``get_request_context``, ``inspect_evidence``, ``lookup_identity``, ``list_activity``.

Rules, each rule then its reason:

* **Three tools are bound to the case; two lookups are not.** The model never names a case:
  ``audit_case``, ``get_request_context`` and ``inspect_evidence`` read the case the harness bound.
  ``lookup_identity`` answers for any identifier, and ``list_activity`` matches its string (at
  least 4 characters) against every activity row's resource ID and details. Both are read-only
  and cut off at ``audit_at``, and no tool result can change a fact the engine settled, so a
  lookup beyond the case informs the model's answer and nothing else.
* **Everything is cut off at ``audit_at``:** a file captured after it is refused, and activity,
  audit-log and identity rows after it are not returned. Reason: nothing after ``audit_at`` may be
  cited.
* **Every result names its evidence IDs,** copied from the inputs, never composed. Reason: answer
  validation accepts only IDs a tool returned.
* **Read-only and gold-free:** the tools read the in-memory :class:`~deletion_audit.engine.World`
  and the vision results only. No tool opens a file, writes anything or touches gold; a hygiene
  test scans this module's source.
* **Arguments are checked** against each tool's input schema before the tool runs; a bad call
  returns an error result and is never guessed at.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .. import timeutil
from ..engine import EngineBrief, World
from ..evidence.interpret import classify_identifier, make_identifier
from ..evidence.model import Identifier, Observation
from ..inputs.requests import DeletionRequest
from ..model import canonical_json
from ..record import CrossCheck
from ..state.observe import observation_state
from .prompting import tool_descriptions
from .schemas import AUDIT_CASE_INPUT, STATE_FIELDS, SUBJECT_FIELDS, SchemaError, check
from .vision import ImageReadRecord

MAX_ROWS = 25
MAX_OBSERVATIONS = 30
INPUT_SCHEMAS: Mapping[str, Mapping[str, Any]] = {
    "audit_case": AUDIT_CASE_INPUT,
    "get_request_context": {"type": "object", "properties": {}, "additionalProperties": False},
    "inspect_evidence": {
        "type": "object",
        "properties": {"file_id": {"type": "string"},
                       "focus": {"type": "string", "enum": ["records", "identity", "state"]}},
        "required": ["file_id", "focus"],
        "additionalProperties": False,
    },
    "lookup_identity": {
        "type": "object", "properties": {"value": {"type": "string"}}, "required": ["value"],
        "additionalProperties": False,
    },
    "list_activity": {
        "type": "object", "properties": {"identifier_or_resource": {"type": "string"}},
        "required": ["identifier_or_resource"], "additionalProperties": False,
    },
}
TOOL_NAMES: tuple[str, ...] = tuple(INPUT_SCHEMAS)


def tool_definitions() -> list[dict[str, Any]]:
    """The tool list sent with every conversation request (case-independent, fixed order)."""
    desc = tool_descriptions()
    return [{"name": n, "description": desc[n], "input_schema": json.loads(json.dumps(INPUT_SCHEMAS[n]))}
            for n in TOOL_NAMES]


def args_hash(name: str, args: Any) -> str:
    """sha256 prefix of the canonical (name, arguments): the no-repeat key and the artifact field."""
    return hashlib.sha256(canonical_json({"name": name, "input": args}).encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class ToolResult:
    """One tool result: JSON content, whether it is an error, and the evidence IDs it shows."""

    content: str
    is_error: bool
    evidence_ids: tuple[str, ...]


def _ok(data: Any, evidence_ids: Sequence[str]) -> ToolResult:
    ids = tuple(dict.fromkeys(evidence_ids))
    return ToolResult(json.dumps({"evidence_ids": list(ids), "data": data}, sort_keys=True, ensure_ascii=False),
                      False, ids)


def _error(message: str) -> ToolResult:
    return ToolResult(json.dumps({"error": message}, sort_keys=True), True, ())


class CaseTools:
    """The tools for one case. ``brief`` builds the engine brief on first use (memoized by the caller)."""

    def __init__(self, case_id: str, world: World, crosscheck: CrossCheck,
                 vision: Mapping[str, ImageReadRecord], brief: Callable[[], EngineBrief]) -> None:
        """Bind the tools to ``case_id``; nothing is computed until a tool runs."""
        self.case_id = case_id
        self.world = world
        self.request: DeletionRequest = next(r for r in world.ctx.requests if r.case_id == case_id)
        self.crosscheck = crosscheck
        self.vision = vision
        self.brief = brief

    @property
    def audit_at(self) -> str:
        """The case's audit time; every tool cuts off here."""
        return self.request.audit_at

    def run(self, name: str, args: Any) -> ToolResult:
        """Check ``args`` against the tool's schema, then run it; unknown tools and bad args are errors."""
        if name not in INPUT_SCHEMAS:
            return _error(f"unknown tool {name!r}")
        try:
            check(args, INPUT_SCHEMAS[name])
        except SchemaError as exc:
            return _error(f"arguments do not match the input schema: {exc}")
        handler: Callable[[Mapping[str, Any]], ToolResult] = getattr(self, f"_{name}")
        return handler(args)

    # ------------------------------------------------------------------ tools
    def _audit_case(self, args: Mapping[str, Any]) -> ToolResult:
        """The engine's brief: settled records (read-only), the cited file, open questions."""
        brief = self.brief()
        ids = [brief.citation.file_id] if brief.citation.file_id else []
        ids += [r.cite for r in brief.settled if r.cite]
        return _ok(json.loads(brief.for_model()), ids)

    def _get_request_context(self, args: Mapping[str, Any]) -> ToolResult:
        """Dates, reported status, intake rows at or before audit_at, same-person request count."""
        rows = {a.activity_id: a for a in self.world.ctx.activity}
        intake = [rows[i] for i in self.crosscheck.activity_ids if i in rows]
        person = self.world.resolutions[self.case_id].person
        same = sum(1 for res in self.world.resolutions.values() if person and res.person == person)
        r = self.request
        data = {
            "reported_status": r.reported_status, "requested_at": r.requested_at, "reported_at": r.reported_at,
            "audit_at": r.audit_at,
            "intake_rows": [{"activity_id": a.activity_id, "event_time": a.event_time, "event_type": a.event_type,
                             "resource_id": a.resource_id, "details": a.details} for a in intake],
            "same_person_requests": same,
        }
        return _ok(data, [a.activity_id for a in intake])

    def _inspect_evidence(self, args: Mapping[str, Any]) -> ToolResult:
        """A file captured at or before audit_at: image readings, or the case's parsed records."""
        file_id, focus = str(args["file_id"]), str(args["focus"])
        ref = next((f for f in self.world.ctx.manifest if f.file_id == file_id), None)
        if ref is None:
            return _error("unknown file_id")
        if not timeutil.le(ref.captured_at, self.audit_at):
            return _error("this file was captured after the audit time and cannot be used")
        if file_id in self.vision:
            return _ok(_image_data(self.vision[file_id], focus), [file_id])
        fp = self.world.ctx.index.files.get(file_id)
        if fp is None or not fp.ok:
            return _ok({"kind": "parsed", "status": fp.status if fp else "MISSING", "records": []}, [file_id])
        own = {lk.resource_id for lk in self.world.case_links[self.case_id] if lk.resource_id}
        asg = self.world.assignments.get(self.case_id)
        if asg and asg.resource_id:
            own.add(asg.resource_id)
        mine = [o for o in fp.observations if o.resource_id in own]
        data = {"kind": "parsed", "status": fp.status, "family": fp.family, "records_in_file": len(fp.observations),
                "records": [_observation_data(o, focus) for o in mine[:MAX_OBSERVATIONS]]}
        return _ok(data, [file_id])

    def _lookup_identity(self, args: Mapping[str, Any]) -> ToolResult:
        """Who an identifier belongs to, now or before, as of audit_at; audit-log IDs as evidence."""
        raw = str(args["value"]).strip()
        if not raw:
            return _error("value is empty")
        kind = classify_identifier("", raw)
        if kind == "other":
            return _error("value is not an email, phone, email hash or user ID")
        ident = make_identifier(kind, raw, "lookup")
        matches: dict[str, dict[str, Any]] = {}
        for row in self.world.ctx.identities:
            if timeutil.le(row.updated_at, self.audit_at) and _row_matches(row.user_id, row.email, row.phone,
                                                                           row.email_hash, ident):
                matches.setdefault(row.user_id, {"user_id": row.user_id, "current": False, "audit_ids": []})
                matches[row.user_id]["current"] = True
        for a in self.world.ctx.audit_log:
            if not timeutil.le(a.event_time, self.audit_at):
                continue
            if any(i is not None and i.kind == ident.kind and i.value == ident.value
                   for i in (a.old_identifier, a.new_identifier)):
                entry = matches.setdefault(a.user_id, {"user_id": a.user_id, "current": False, "audit_ids": []})
                entry["audit_ids"].append(a.audit_id)
        data = {"value_kind": kind, "matches": [matches[k] for k in sorted(matches)]}
        return _ok(data, [i for k in sorted(matches) for i in matches[k]["audit_ids"]])

    def _list_activity(self, args: Mapping[str, Any]) -> ToolResult:
        """Activity rows at or before audit_at for a resource, or mentioning an identifier."""
        key = str(args["identifier_or_resource"]).strip()
        if len(key) < 4:
            return _error("give a resource ID or an identifier of at least 4 characters")
        rows = [a for a in self.world.ctx.activity
                if timeutil.le(a.event_time, self.audit_at) and (a.resource_id == key or key in a.details)]
        rows.sort(key=lambda a: (timeutil.sort_key(a.event_time), a.activity_id))
        rows = rows[-MAX_ROWS:]
        data = {"rows": [{"activity_id": a.activity_id, "event_time": a.event_time, "event_type": a.event_type,
                          "source_system": a.source_system, "target_system": a.target_system,
                          "resource_id": a.resource_id, "reported_result": a.reported_result, "details": a.details}
                         for a in rows]}
        return _ok(data, [a.activity_id for a in rows])


def _row_matches(user_id: str, email: Identifier | None, phone: Identifier | None, email_hash: str | None,
                 ident: Identifier) -> bool:
    """Whether an identity row's current values include ``ident`` (exact, normalized; T49)."""
    if ident.kind == "user_id":
        return user_id == ident.value
    if ident.kind == "email_hash":
        return (email_hash or "").lower() == ident.value
    candidate = email if ident.kind == "email" else phone if ident.kind == "phone" else None
    return candidate is not None and candidate.value == ident.value


def _image_data(rec: ImageReadRecord, focus: str) -> dict[str, Any]:
    """An image's merged reading, filtered by focus, with the ID checks and the disagreements."""
    checks = {c.shown_id.strip(): c for c in rec.ids}
    records = []
    for r in rec.merged.records if rec.merged else ():
        c = checks.get(r.shown_id)
        item: dict[str, Any] = {"shown_id": r.shown_id, "resource_id": c.resource_id if c else None,
                                "system_id": c.system_id if c else None, "id_basis": c.basis if c else None}
        if focus == "identity":
            item.update({n: list(getattr(r, n)) for n in SUBJECT_FIELDS})
        if focus == "state":
            item.update({n: getattr(r, n) for n in STATE_FIELDS})
        records.append(item)
    return {"kind": "image", "status": rec.status, "readings_agree": rec.agree,
            "disagreeing_fields": list(rec.disagreements), "records": records}


def _observation_data(o: Observation, focus: str) -> dict[str, Any]:
    """One parsed record, filtered by focus."""
    item: dict[str, Any] = {"resource_id": o.resource_id, "system_id": o.system_id, "event": o.event,
                            "time": o.record_time or o.captured_at, "locator": o.locator.ref}
    if focus == "state":
        item["state"] = observation_state(o, o.system_id)
    if focus == "identity":
        item["identifiers"] = sorted({f"{i.kind}:{i.value}" for i in o.record_identifiers})
    return item
