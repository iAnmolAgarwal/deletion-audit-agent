"""The vision step: each screenshot is read twice, compared, merged and turned into observations.

Rules, each with its basis:

* **Only PNG bytes are read** (T72 F1 as G5 applies it; ``engine.PNG_SIGNATURE``). A file that
  needs a model but does not start with the PNG signature is an explicit failure
  (``VISION_NOT_PNG``) with no observation, so the engine keeps it as an unparsed dependency (T8);
  it is never "nothing found".
* **Two independent readings** (developer ruling T88 (1)). Every image is read once through each
  of two :class:`~deletion_audit.model.ModelClient` objects whose reply caches have different
  roots. The request is the same, so the key is the same, but reading 2 is a cache miss in its
  own namespace: an independent reply, never a replay of reading 1 (G3 section 8: "Replicates use
  a separate cache root, not a key change"). Two clients on one cache root are refused.
* **Field-by-field comparison**; any difference raises ``VISION_READINGS_DISAGREE`` and both
  readings go to ``vision_readings.json`` / ``.md`` (:func:`write_vision_artifacts`) for the
  developer before any paid full run (T88 (1)).
* **What the engine uses when the readings disagree** (:func:`merge_readings`), chosen so that a
  disagreement can never hide a record (``notes/SYSTEM.md``, "the error I care most about
  avoiding"): every record either reading shows is kept; identifier lists are united; a state
  field takes the value that keeps a finding (sync enabled, restore allowed, not deleted,
  download available) when either reading gives it, and otherwise ``unreadable``, which gives the
  record no state from the image and raises ``IMAGE_FIELD_UNREADABLE`` for the cases it touches.
* **IDs must be well-formed** (T88 (2), :mod:`.idshapes`): an ID that fits no learned shape is
  flagged and not used as a resource ID; an ID no other input names is flagged, never dropped.
* **If either reading fails, the image fails** (``VISION_READ_FAILED``): a single unverified
  reading is not used, so the image stays an unparsed dependency of the cases that need it (T8).
* **Observation fields** use the engine's own attribute names (``state/observe.py``), so the engine
  reads an image record exactly as it reads a parsed record. ``record_time`` is left empty: the
  state shown is the state at capture, so the engine falls back to the file's ``captured_at``.
* **Only what is visibly on screen sets a state** (developer ruling T112 item 9, G7 verifier
  finding 1): a reading records each record's redaction-style markers (``visible_markers``, such as
  ``[REDACTED]``) and its status badge (``status_label``) verbatim. The markers pass to the engine as
  ``visible_marker``; the badge is kept for review only (``status_label``) and maps to no state.
  ``state/observe.py`` reads an image observation by its own rule: a record with no transcribed
  subject, no visible state field and no marker gets no state, never a text default.
* **Artifacts name IDs, states and flags only** (``artifacts.py`` rule): identifiers read from an
  image are written as a sha256 prefix of their normalized value plus a masked form.
"""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

from ..discovery.accounts import Flag
from ..engine import PNG_SIGNATURE, AuditContext
from ..evidence.interpret import make_identifier, normalize_identifier
from ..evidence.model import FileRef, Identifier, Locator, Observation
from ..model import ModelCallFailed, ModelClient, ModelRequest, reply_text
from ..model.request import canonical_json
from .idshapes import IdCheck, IdShapes, check_id
from .injection import detect_instruction_like
from .params import EFFORT_VISION, MAX_TOKENS_VISION, MODEL
from .prompting import load_prompt
from .schemas import (
    STATE_FIELDS,
    SUBJECT_FIELDS,
    VERBATIM_FIELDS,
    VISION_SCHEMA,
    SchemaError,
    VisionReading,
    VisionRecord,
    parse_vision,
)

#: The value of each state field that keeps a finding (merge rule; module docstring).
FINDING_VALUE: Mapping[str, str] = MappingProxyType(
    {"sync_enabled": "yes", "restore_allowed": "yes", "marked_deleted": "no", "download_available": "yes"}
)
_KIND: Mapping[str, str] = MappingProxyType(
    {"subject_emails": "email", "subject_phones": "phone", "subject_names": "name", "subject_user_ids": "user_id"}
)
ReadStatus = Literal["OK", "FAILED"]


def vision_request(png: bytes) -> ModelRequest:
    """The request for one screenshot: the vision prompt, the fenced image and the reading schema; no tools.

    The image sits between ``<screenshot>`` and ``</screenshot>`` text blocks, which the prompt calls
    data, not instructions (T95 item 2)."""
    data = base64.b64encode(png).decode("ascii")
    return ModelRequest({
        "model": MODEL,
        "max_tokens": MAX_TOKENS_VISION,
        "system": load_prompt("vision"),
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": "<screenshot>"},
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": data}},
            {"type": "text", "text": "</screenshot>\nReport the records this screenshot shows, as JSON in the "
                                     "required format."},
        ]}],
        "output_config": {"effort": EFFORT_VISION, "format": {"type": "json_schema", "schema": VISION_SCHEMA}},
    })


@dataclass(frozen=True)
class ReadAttempt:
    """One reading: the parsed reading, or the failure that stopped it (never both)."""

    key: str
    reading: VisionReading | None
    failure: str | None = None
    error_class: str | None = None
    raw_sha256: str | None = None  # sha256 of canonical_json(reply.raw): tells a re-read from the original (T112 4(b))


def read_once(png: bytes, client: ModelClient) -> ReadAttempt:
    """Read ``png`` once through ``client``; a failed call or bad reply is an explicit failure."""
    req = vision_request(png)
    try:
        reply = client.call(req)
        digest = hashlib.sha256(canonical_json(reply.raw).encode("utf-8")).hexdigest()
        return ReadAttempt(req.key(), parse_vision(json.loads(reply_text(reply.raw) or "null")), raw_sha256=digest)
    except ModelCallFailed as exc:
        return ReadAttempt(req.key(), None, exc.reason, exc.error_class)
    except (SchemaError, ValueError) as exc:
        return ReadAttempt(req.key(), None, "UNPARSEABLE", type(exc).__name__)


# --------------------------------------------------------------------------- compare and merge
def _norm(field_name: str, value: str) -> str:
    """The normalized form of one subject value (the evidence layer's one normalizer)."""
    return normalize_identifier(_KIND[field_name], value)  # type: ignore[arg-type]


def _by_id(reading: VisionReading) -> dict[str, list[VisionRecord]]:
    out: dict[str, list[VisionRecord]] = {}
    for r in reading.records:
        out.setdefault(r.shown_id.strip(), []).append(r)
    return out


def _subjects(records: Iterable[VisionRecord], name: str) -> tuple[str, ...]:
    """The normalized values of one subject list across ``records``, deduplicated and sorted."""
    return tuple(sorted({_norm(name, v) for r in records for v in getattr(r, name) if v.strip()}))


def _merge_state(name: str, values: Iterable[str]) -> str:
    """Equal values stand; otherwise the finding value if any reading gave it, else ``unreadable``."""
    distinct = sorted(set(values))
    if len(distinct) == 1:
        return distinct[0]
    return FINDING_VALUE[name] if FINDING_VALUE[name] in distinct else "unreadable"


def merge_records(shown_id: str, records: Sequence[VisionRecord]) -> VisionRecord:
    """One record from several reports of it (merge rule, module docstring)."""

    def state(name: str) -> str:
        """The merged value of one state field across ``records``."""
        return _merge_state(name, (getattr(r, name) for r in records))

    return VisionRecord(
        shown_id=shown_id,
        subject_emails=_subjects(records, "subject_emails"),
        subject_phones=_subjects(records, "subject_phones"),
        subject_names=_subjects(records, "subject_names"),
        subject_user_ids=_subjects(records, "subject_user_ids"),
        sync_enabled=state("sync_enabled"),
        restore_allowed=state("restore_allowed"),
        marked_deleted=state("marked_deleted"),
        download_available=state("download_available"),
        visible_markers=tuple(sorted({m for r in records for m in r.visible_markers if m.strip()})),
        status_label=" | ".join(sorted({r.status_label for r in records if r.status_label.strip()})),
    )


def compare_readings(a: VisionReading, b: VisionReading) -> tuple[str, ...]:
    """The fields on which two readings differ, as sorted paths such as ``records[x].sync_enabled``."""
    out: list[str] = []
    ia, ib = _by_id(a), _by_id(b)
    if set(ia) != set(ib):
        out.append("records")
    for sid in sorted(set(ia) & set(ib)):
        ra, rb = merge_records(sid, ia[sid]), merge_records(sid, ib[sid])
        if len(ia[sid]) != len(ib[sid]):
            out.append(f"records[{sid}].count")
        for name in (*SUBJECT_FIELDS, *STATE_FIELDS, *VERBATIM_FIELDS):
            if getattr(ra, name) != getattr(rb, name):
                out.append(f"records[{sid}].{name}")
    if a.instruction_like_text != b.instruction_like_text:
        out.append("instruction_like_text")
    if bool(a.unreadable) != bool(b.unreadable):
        out.append("unreadable")
    return tuple(sorted(out))


def merge_readings(readings: Sequence[VisionReading]) -> VisionReading:
    """The reading the engine uses: every record kept, subjects united, states merged (docstring)."""
    groups: dict[str, list[VisionRecord]] = {}
    for reading in readings:
        for sid, recs in _by_id(reading).items():
            groups.setdefault(sid, []).extend(recs)
    return VisionReading(
        records=tuple(merge_records(sid, groups[sid]) for sid in sorted(groups)),
        unreadable=tuple(sorted({u for r in readings for u in r.unreadable})),
        instruction_like_text=any(r.instruction_like_text for r in readings),
    )


# --------------------------------------------------------------------------- observations
def record_attrs(rec: VisionRecord) -> dict[str, str]:
    """Engine attribute names for one merged record (``state/observe.py`` vocabulary)."""
    attrs: dict[str, str] = {}
    targets = (("subject_emails", ("email", "requester_email")), ("subject_phones", ("phone", "requester_phone")),
               ("subject_names", ("name", "requester_name")), ("subject_user_ids", ("user_id",)))
    for name, keys in targets:
        values = getattr(rec, name)
        if values:
            for key in keys:
                attrs[key] = values[0]
    tri = {"yes": "true", "no": "false"}
    if rec.sync_enabled in tri:
        attrs["enabled"] = tri[rec.sync_enabled]
    if rec.restore_allowed in tri:
        attrs["restore_allowed"] = tri[rec.restore_allowed]
    if rec.download_available in tri:
        attrs["download_available"] = tri[rec.download_available]
    if rec.marked_deleted in tri:
        attrs["account_status"] = "DELETED" if rec.marked_deleted == "yes" else "ACTIVE"
    if rec.visible_markers:
        attrs["visible_marker"] = " | ".join(rec.visible_markers)
    if rec.status_label:
        attrs["status_label"] = rec.status_label  # review only: state/observe.py never reads it
    return attrs


def record_identifiers(rec: VisionRecord) -> frozenset[Identifier]:
    """The subject identifiers of one merged record, built by the evidence layer's normalizer."""
    out = set()
    for name in SUBJECT_FIELDS:
        kind = _KIND[name]
        for value in getattr(rec, name):
            out.add(make_identifier(kind, value, kind))  # type: ignore[arg-type]
    return frozenset(out)


def image_observation(ref: FileRef, rid: str, system: str, rec: VisionRecord) -> Observation:
    """One image observation for one usable record (Locator kind ``image``)."""
    return Observation(
        file_id=ref.file_id,
        family="image",
        locator=Locator(ref.file_id, "image", f"record:{rid}"),
        captured_at=ref.captured_at,
        record_time=None,
        system_id=system,
        resource_id=rid,
        record_identifiers=record_identifiers(rec),
        lookup_identifiers=frozenset(),
        trace_id=None,
        scope=None,
        event=None,
        attrs=MappingProxyType(record_attrs(rec)),
    )


# --------------------------------------------------------------------------- per image and run
@dataclass(frozen=True)
class ImageReadRecord:
    """Everything the vision step decided for one image file."""

    file_id: str
    status: ReadStatus
    attempts: tuple[ReadAttempt, ...]
    agree: bool | None
    disagreements: tuple[str, ...]
    flags: tuple[Flag, ...]
    ids: tuple[IdCheck, ...]
    merged: VisionReading | None
    observations: tuple[Observation, ...]

    def unreadable_fields(self) -> tuple[tuple[str, str], ...]:
        """``(resource_id, field)`` for every usable record whose merged state field is unreadable."""
        if self.merged is None:
            return ()
        usable = {c.shown_id.strip(): c.resource_id for c in self.ids if c.resource_id}
        return tuple(sorted(
            (usable[r.shown_id], name) for r in self.merged.records if r.shown_id in usable
            for name in STATE_FIELDS if getattr(r, name) == "unreadable"
        ))


@dataclass(frozen=True)
class VisionRun:
    """The vision step's result for a whole run."""

    records: tuple[ImageReadRecord, ...]
    observations: tuple[Observation, ...] = field(default=())

    def by_file(self) -> dict[str, ImageReadRecord]:
        """Records by file ID."""
        return {r.file_id: r for r in self.records}

    def read_ok(self) -> frozenset[str]:
        """File IDs whose two readings both succeeded (the PNGs that are no longer unread)."""
        return frozenset(r.file_id for r in self.records if r.status == "OK")

    def needs_review(self) -> tuple[str, ...]:
        """File IDs the developer must review before a paid full run (disagreement or failure; T88)."""
        return tuple(sorted(r.file_id for r in self.records if r.status != "OK" or r.agree is False))


def _read_bytes(ctx: AuditContext, ref: FileRef) -> bytes | None:
    """The file's bytes when its path stays inside the dataset directory, else None."""
    root = Path(ctx.dataset_dir).resolve()
    path = (root / ref.path).resolve()
    if root not in path.parents or not path.is_file():
        return None
    return path.read_bytes()


def _id_flags(checks: Sequence[IdCheck]) -> list[Flag]:
    codes = {"malformed": "VISION_ID_MALFORMED", "unrecognized": "VISION_ID_UNRECOGNIZED",
             "ambiguous": "VISION_ID_AMBIGUOUS"}
    out = [Flag(codes[c.basis], f"shown id not used as a resource ID ({c.basis})") for c in checks if c.basis in codes]
    out += [Flag("VISION_ID_UNCORROBORATED", f"{c.resource_id}: no other input names it")
            for c in checks if c.resource_id and not c.named_elsewhere]
    return out


def _observations(ref: FileRef, merged: VisionReading, checks: Sequence[IdCheck]) -> tuple[Observation, ...]:
    """One observation per usable resource ID (records naming the same resource are merged)."""
    by_rid: dict[str, list[VisionRecord]] = {}
    system: dict[str, str] = {}
    shown = {r.shown_id: r for r in merged.records}
    for c in checks:
        if c.resource_id and c.system_id and c.shown_id in shown:
            by_rid.setdefault(c.resource_id, []).append(shown[c.shown_id])
            system.setdefault(c.resource_id, c.system_id)
    return tuple(image_observation(ref, rid, system[rid], merge_records(rid, by_rid[rid])) for rid in sorted(by_rid))


def assess_image(ref: FileRef, png: bytes | None, clients: Sequence[ModelClient], shapes: IdShapes) -> ImageReadRecord:
    """Read one image through each client, compare, merge, check IDs and build observations."""
    if png is None or not png.startswith(PNG_SIGNATURE):
        flag = Flag("VISION_NOT_PNG", "bytes do not start with the PNG signature; not read")
        return ImageReadRecord(ref.file_id, "FAILED", (), None, (), (flag,), (), None, ())
    attempts = tuple(read_once(png, c) for c in clients)
    failed = [a for a in attempts if a.reading is None]
    if failed:
        failures = tuple(Flag("VISION_READ_FAILED", f"reading {i + 1}: {a.failure} ({a.error_class})")
                         for i, a in enumerate(attempts) if a.reading is None)
        return ImageReadRecord(ref.file_id, "FAILED", attempts, None, (), failures, (), None, ())
    readings = [a.reading for a in attempts if a.reading is not None]
    disagreements = compare_readings(readings[0], readings[1]) if len(readings) == 2 else ()
    merged = merge_readings(readings)
    checks = tuple(check_id(r.shown_id, shapes) for r in merged.records)
    flags: list[Flag] = []
    if disagreements:
        flags.append(Flag("VISION_READINGS_DISAGREE", f"{len(disagreements)} field(s) differ; merged by rule"))
    if merged.instruction_like_text:
        flags.append(Flag("INSTRUCTION_LIKE_TEXT_MODEL", "a reading saw instruction-like text in the image"))
    shown = [r.shown_id for r in merged.records] + [n for r in merged.records for n in r.subject_names]
    code_hit = detect_instruction_like("\n".join([*shown, *merged.unreadable])).patterns
    if code_hit:
        flags.append(Flag("INSTRUCTION_LIKE_TEXT_CODE", ",".join(code_hit)))
    if merged.unreadable:
        flags.append(Flag("VISION_UNREADABLE_NOTED", f"{len(merged.unreadable)} note(s) of unreadable content"))
    flags += _id_flags(checks)
    rec = ImageReadRecord(ref.file_id, "OK", attempts, not disagreements, disagreements, (), checks, merged,
                          _observations(ref, merged, checks))
    flags += [Flag("VISION_FIELD_UNREADABLE", f"{rid}: {name}") for rid, name in rec.unreadable_fields()]
    return ImageReadRecord(rec.file_id, rec.status, rec.attempts, rec.agree, rec.disagreements,
                           tuple(sorted(set(flags), key=lambda f: (f.code, f.detail))), rec.ids, rec.merged,
                           rec.observations)


def reading_observations(ref: FileRef, rec: ImageReadRecord, k: int) -> tuple[Observation, ...]:
    """The observations reading ``k`` (0 or 1) alone gives, built exactly as the merged ones are
    (same normalizer, same ID checks; developer ruling T118 (2a), used by the regression gate).

    Only a read-OK image has two readings; any other request raises ValueError (an explicit
    failure, never an empty "nothing shown")."""
    if rec.status != "OK" or not 0 <= k < len(rec.attempts) or rec.attempts[k].reading is None:
        raise ValueError(f"{rec.file_id}: no reading {k + 1} to build observations from")
    single = merge_readings([rec.attempts[k].reading])  # type: ignore[list-item]
    return _observations(ref, single, rec.ids)


def check_namespaces(clients: Sequence[ModelClient]) -> None:
    """Refuse fewer than two clients, or two clients that share a reply-cache root (T88 (1))."""
    if len(clients) != 2:
        raise ValueError("the vision step needs exactly two clients, one per reading")
    roots = {Path(c.cache.root).resolve() for c in clients}
    if len(roots) != 2:
        raise ValueError("the two readings need separate reply-cache roots, or reading 2 replays reading 1")


def image_files(ctx: AuditContext) -> tuple[FileRef, ...]:
    """Manifest files the parsers left for a model (status NEEDS_MODEL), in manifest order."""
    files = ctx.index.files
    return tuple(ref for ref in ctx.manifest if ref.file_id in files and files[ref.file_id].status == "NEEDS_MODEL")


def read_images(ctx: AuditContext, clients: Sequence[ModelClient], shapes: IdShapes) -> VisionRun:
    """Read every NEEDS_MODEL file twice (PNG only) and return the records and observations."""
    check_namespaces(clients)
    records = tuple(assess_image(ref, _read_bytes(ctx, ref), clients, shapes) for ref in image_files(ctx))
    return VisionRun(records, tuple(o for r in records for o in r.observations))


# --------------------------------------------------------------------------- reports and artifacts
def _sha12(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _mask(value: str) -> str:
    """A masked form for the review table: first character, then the domain or the last 2 characters."""
    if "@" in value:
        local, _, domain = value.partition("@")
        return f"{local[:1]}…@{domain}"
    return f"{value[:1]}…{value[-2:]}" if len(value) > 3 else "…"


def reading_report(reading: VisionReading | None) -> dict[str, Any] | None:
    """A JSON-ready reading with every identifier replaced by a sha256 prefix of its normalized value."""
    if reading is None:
        return None
    return {
        "records": [
            {
                "shown_id": r.shown_id,
                **{n: sorted(_sha12(_norm(n, v)) for v in getattr(r, n)) for n in SUBJECT_FIELDS},
                **{n: getattr(r, n) for n in STATE_FIELDS},
                "visible_markers": list(r.visible_markers),
                "status_label": r.status_label,
            }
            for r in sorted(reading.records, key=lambda x: x.shown_id)
        ],
        "unreadable_count": len(reading.unreadable),
        "instruction_like_text": reading.instruction_like_text,
    }


def image_report(rec: ImageReadRecord) -> dict[str, Any]:
    """The run-level vision item for one image (field names fixed by the G7a brief for G7b)."""
    return {
        "file_id": rec.file_id,
        "status": rec.status,
        "reply_keys": [a.key for a in rec.attempts],
        "reading_sha256": [a.raw_sha256 for a in rec.attempts],
        "readings": [reading_report(a.reading) for a in rec.attempts],
        "agree": rec.agree,
        "disagreements": list(rec.disagreements),
        "flags": sorted({f.code for f in rec.flags}),
        "resource_ids": [
            {
                "system_id": c.system_id,
                "resource_id": c.resource_id if c.resource_id else c.shown_id.strip(),
                "well_formed": c.well_formed,
                "named_elsewhere": c.named_elsewhere,
                "shown_id": c.shown_id,
                "basis": c.basis,
                "named_by": list(c.named_by),
            }
            for c in rec.ids
        ],
    }


def _field_values(reading: VisionReading, path: str) -> str:
    """The value at a disagreement path in one reading, masked, for the review table."""
    if not path.startswith("records["):
        if path == "records":
            return ", ".join(sorted(_by_id(reading))) or "(none)"
        return str(getattr(reading, path, "")) if path != "unreadable" else str(bool(reading.unreadable))
    sid, _, name = path[len("records["):].partition("].")
    recs = _by_id(reading).get(sid)
    if not recs:
        return "(record absent)"
    if name == "count":
        return str(len(recs))
    merged = merge_records(sid, recs)
    value = getattr(merged, name)
    if name in SUBJECT_FIELDS:
        return ", ".join(f"{_mask(v)} {_sha12(v)}" for v in value) or "(none)"
    return str(value)


def review_markdown(run: VisionRun, needs_review: Sequence[str] | None = None) -> str:
    """A short Markdown comparison of the two readings of every image, for the developer (T88 (1))."""
    lines = ["# Vision readings: two independent readings per image (T88)", "",
             "Identifiers are masked; the sha256 prefix shows whether two values are the same.", "",
             "| file | status | agree | disagreeing fields | flags |", "|---|---|---|---|---|"]
    for r in run.records:
        flags = ", ".join(sorted({f.code for f in r.flags})) or "-"
        lines.append(f"| {r.file_id} | {r.status} | {r.agree} | {len(r.disagreements)} | {flags} |")
    for r in run.records:
        if not r.disagreements:
            continue
        a, b = (x.reading for x in r.attempts)
        lines += ["", f"## {r.file_id}", "", "| field | reading 1 | reading 2 | engine uses |", "|---|---|---|---|"]
        merged = r.merged
        for path in r.disagreements:
            used = _field_values(merged, path) if merged is not None else "-"
            first = _field_values(a, path) if a is not None else "-"
            second = _field_values(b, path) if b is not None else "-"
            lines.append(f"| `{path}` | {first} | {second} | {used} |")
    review = ", ".join(needs_review if needs_review is not None else run.needs_review()) or "none"
    lines += ["", f"Needs the developer's review before a paid full run: {review}.", ""]
    return "\n".join(lines)


def write_vision_artifacts(run_dir: Path, run: VisionRun,
                           needs_review: Sequence[str] | None = None) -> tuple[Path, Path]:
    """Write ``vision_readings.json`` and ``vision_readings.md`` under ``run_dir``; return both paths.

    ``needs_review`` is the run's review list (the pipeline adds every image whose readings change a
    row, T112 item 4 (b)); default: the failed or disagreeing images only."""
    run_dir.mkdir(parents=True, exist_ok=True)
    js = run_dir / "vision_readings.json"
    md = run_dir / "vision_readings.md"
    needs = list(needs_review) if needs_review is not None else list(run.needs_review())
    body = {"images": [image_report(r) for r in run.records], "needs_review": needs}
    js.write_text(json.dumps(body, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    md.write_text(review_markdown(run, needs), encoding="utf-8")
    return js, md
