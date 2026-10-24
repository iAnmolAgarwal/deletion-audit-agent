"""Evidence guard: a skipped, empty or half-parsed evidence file refuses output (verifier B2).

Developer ruling T47. "Nothing found" must never pass as success, so a producer writes no
output when any of these holds:

* a skip whose reason is outside :data:`ALLOWED_SKIP_REASONS`. The allow-list holds exactly
  one reason, ``png-model-needed`` (an image waiting for the model part, G7). Every other
  reason refuses: ``unknown-json``, ``unknown``, any ``FAILED`` or ``-failed`` label, and any
  reason not seen before. A ``png-model-needed`` skip is allowed only when the file's bytes
  start with the PNG signature :data:`PNG_SIGNATURE`, by content and never by the label or
  the file name (verifier F1, ruling T72); anything else with that label refuses;
* a parsed file that yields zero units, with two exceptions:
  - (T38) the file declares a scope (a full collection, a snapshot, or a ``snapshot_scope``
    table) and has no rows: that is valid absence evidence;
  - (T51) "text present, no resource ID": the file's extracted text is non-empty AND its raw
    text holds no token shaped like a resource ID (a known resource prefix, then ``_`` and
    digits). Such a file is listed with the run, like an allowed skip, and does not refuse.
    If a resource-ID-shaped token IS present while the parser yielded nothing, that is a
    parser failure and the run refuses. An empty text layer still refuses. The test is by
    content only, never by file name or ID. The prefixes come from ``contract.PREFIX_SYSTEM``
    plus the extractor's own prefix table when one is given. It applies to text-layer
    documents only, recognised by content (the bytes start with ``%PDF-``): the "extracted
    text" is the extractor's text layer, and the raw text checked is that layer plus the
    file's bytes. A structured file (JSON, SQL, log, pipe text) that yields nothing keeps
    the T47 rule and refuses: its parser reads fields, not free text, so a record it missed
    need not look like a resource ID (our reading of T51; the narrower one).
  Files whose only units are scope markers are listed as such;
* a log line whose JSON fails to parse. The prototype's ``logparse.parse_line`` swallows
  that error and returns an empty record; :func:`instrument` re-checks the line it actually
  parsed (``rec["raw"]``) without editing the prototype.

Producer record contract (``runs/<run_id>/producer.json``), read by ``evaluate.py score``
through :func:`check_producer`: ``evidence_skipped`` (every skip entry, ``<file_id>:<reason>``)
and ``evidence_failures`` (every failure; empty for a written run), ``evidence_skip_count`` (read
by the G9 freeze check: the final run must have zero skips; not enforced here) and
``evidence_no_resource_id_files`` (the T51 state). A record without
``evidence_failures`` predates this guard and is reported as unverified; a run without a
record is reported as having none. Neither is passed silently.
"""
from __future__ import annotations

import contextlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Mapping

from .contract import PREFIX_SYSTEM

ALLOWED_SKIP_REASONS: frozenset[str] = frozenset({"png-model-needed"})
PNG_SIGNATURE: bytes = b"\x89PNG\r\n\x1a\n"
SCOPE_UNIT_KINDS: frozenset[str] = frozenset({"sql_scope", "bundle_empty"})  # prototype scope markers
_TS_LINE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)\s+(.*)$")  # logparse.TS_RE's form


def resource_prefixes(extra_prefixes: Iterable[str] = ()) -> list[str]:
    """The resource prefixes: ``contract.PREFIX_SYSTEM``'s keys plus the extractor's own table."""
    return sorted({p.rstrip("_") for p in PREFIX_SYSTEM} | {p.rstrip("_") for p in extra_prefixes if p.rstrip("_")})


def resource_id_pattern(extra_prefixes: Iterable[str] = ()) -> re.Pattern[str]:
    """A token shaped like a resource ID: a known prefix, ``_``, digits (case-insensitive).

    No leading word boundary, so ``x_account_12`` also counts: a broader match can only make
    the guard refuse more often, never less.
    """
    alternation = "|".join(re.escape(p) for p in sorted(resource_prefixes(extra_prefixes), key=lambda p: (-len(p), p)))
    return re.compile(rf"(?:{alternation})_\d+", re.IGNORECASE)


PDF_MAGIC = b"%PDF-"


def is_text_layer_document(data: bytes) -> bool:
    """True for a PDF, by content (its first bytes), never by file name."""
    return data.startswith(PDF_MAGIC)


def text_and_raw(path: Path, data: bytes, pdf_text: Callable[[Path], str] | None) -> tuple[str, str]:
    """(extracted text layer, raw text) of a text-layer document. Raises if unreadable."""
    if pdf_text is None:
        raise ValueError("no PDF text extractor given")
    text = pdf_text(path) or ""
    return text, text + "\n" + data.decode("latin-1")


def skip_reason(entry: str) -> str:
    """``evidence_04:png-model-needed`` -> ``png-model-needed``; ``x:FAILED:E:msg`` -> ``FAILED``."""
    parts = entry.split(":")
    return parts[1] if len(parts) > 1 and parts[1] else "<unlabelled>"


def skip_allowed(entry: str) -> bool:
    """The label alone is allow-listed. Necessary, not sufficient: see :func:`has_png_signature`."""
    return skip_reason(entry) in ALLOWED_SKIP_REASONS


def has_png_signature(path: Path) -> bool:
    """True when the file's first 8 bytes are the PNG signature; False if unreadable."""
    try:
        with path.open("rb") as f:
            return f.read(len(PNG_SIGNATURE)) == PNG_SIGNATURE
    except OSError:
        return False


@dataclass
class Recorder:
    """What :func:`instrument` saw while the prototype extracted evidence."""

    units: list[Any] | None = None           # extract_all's units (no link, alias or vision units)
    manifest: dict[str, dict] | None = None
    skipped: list[str] = field(default_factory=list)
    log_line_failures: list[str] = field(default_factory=list)
    _current_file: str | None = None


@contextlib.contextmanager
def instrument(solver_mod: Any, extract_mod: Any) -> Iterator[Recorder]:
    """Wrap the prototype's extractor for the duration of the block; restore it after.

    ``solver.extract_all`` is wrapped to capture the units, manifest and skips it returns.
    ``extract.parse_log`` is wrapped to know the current file, and ``extract.parse_line`` to
    re-check each JSON-dialect line it parsed. The prototype's files are never edited.
    """
    rec = Recorder()
    real_extract_all = solver_mod.extract_all
    real_parse_log = extract_mod.parse_log
    real_parse_line = extract_mod.parse_line

    def extract_all(*a: Any, **k: Any) -> Any:
        units, manifest, skipped = real_extract_all(*a, **k)
        rec.units, rec.manifest = list(units), manifest
        return units, manifest, skipped

    def parse_log(path: Path, fid: str, cap: str) -> Any:
        rec._current_file = fid
        try:
            return real_parse_log(path, fid, cap)
        finally:
            rec._current_file = None

    def parse_line(line: str) -> Any:
        out = real_parse_line(line)
        if isinstance(out, dict):
            failure = json_line_failure(str(out.get("raw", "")))
            if failure:
                rec.log_line_failures.append(f"{rec._current_file or '<unknown file>'}:log-json-failed:{failure}")
        return out

    solver_mod.extract_all, extract_mod.parse_log, extract_mod.parse_line = extract_all, parse_log, parse_line
    try:
        yield rec
    finally:
        solver_mod.extract_all, extract_mod.parse_log, extract_mod.parse_line = (
            real_extract_all, real_parse_log, real_parse_line)


def json_line_failure(raw: str) -> str | None:
    """For a timestamped JSON-dialect log line, the JSON error; None if it parses or is not JSON."""
    m = _TS_LINE.match(raw)
    if not m or not m.group(2).startswith("{"):
        return None
    try:
        json.loads(m.group(2))
    except json.JSONDecodeError as exc:
        return f"{type(exc).__name__}: {exc.msg} at char {exc.pos}"
    return None


def declares_empty_scope(path: Path, load_sql: Callable[[str], Any] | None = None) -> bool:
    """True when a file declares a scope and holds no rows (T38: valid absence evidence).

    JSON: a ``snapshots`` list whose snapshots all name a collection and hold no records; a
    ``service_exports`` map with at least one collection, all empty; or a top-level
    ``collection`` with ``records == []``. SQL (only with the prototype's sandboxed
    ``load_sql``): a non-empty ``snapshot_scope`` table and every other table empty.
    Anything unreadable or of another type declares no scope.
    """
    suffix = path.suffix.lower()
    try:
        if suffix == ".json":
            d = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(d, dict):
                return False
            snaps = d.get("snapshots")
            if isinstance(snaps, list) and snaps:
                return all(isinstance(x, dict) and x.get("collection") and x.get("records") == [] for x in snaps)
            exports = d.get("service_exports")
            if isinstance(exports, dict):
                colls = [rows for c in exports.values() if isinstance(c, dict) for rows in c.values()]
                return bool(colls) and all(rows == [] for rows in colls)
            return isinstance(d.get("collection"), str) and d.get("records") == []
        if suffix == ".sql" and load_sql is not None:
            con = load_sql(path.read_text(encoding="utf-8"))
            try:
                tables = [r[0] for r in con.execute("select name from sqlite_master where type='table'")]
                if "snapshot_scope" not in tables:
                    return False
                if not con.execute('select count(*) from "snapshot_scope"').fetchone()[0]:
                    return False
                return all(not con.execute(f'select count(*) from "{t}"').fetchone()[0]
                           for t in tables if t != "snapshot_scope")
            finally:
                con.close()
    except Exception:  # noqa: BLE001 -- untrusted file: unreadable means "no declared scope"
        return False
    return False


def audit_extraction(rec: Recorder, skipped: list[str], dataset_dir: Path,
                     load_sql: Callable[[str], Any] | None = None,
                     pdf_text: Callable[[Path], str] | None = None,
                     extra_prefixes: Iterable[str] = ()) -> dict[str, Any]:
    """Classify every manifest file; ``failures`` non-empty means: write no output.

    ``skipped`` is the World's final skip list (it also holds alias-scan failures, which are
    added after extraction). ``pdf_text`` is the extractor's own text-layer function, and
    ``extra_prefixes`` its own resource-prefix table (module docstring, T51).
    """
    extra_prefixes = list(extra_prefixes)
    rid_re = resource_id_pattern(extra_prefixes)
    if rec.units is None or rec.manifest is None:
        return {"ok": False, "failures": ["<extractor>:not-instrumented: extract_all was never called"]}
    per_file: dict[str, list[str]] = {}
    for u in rec.units:
        if getattr(u, "file_id", ""):
            per_file.setdefault(u.file_id, []).append(str(u.kind).split(":")[0])
    allowed, refused = [], []
    for x in skipped:
        row = rec.manifest.get(x.split(":")[0])
        if not skip_allowed(x):
            refused.append(x)
        elif row is None:
            refused.append(f"{x}:file-not-in-manifest")
        elif not has_png_signature(dataset_dir / row["file_path"]):
            refused.append(f"{x}:not-a-png-by-content")
        else:
            allowed.append(x)
    allowed, refused = sorted(allowed), sorted(refused)
    skipped_ids = {x.split(":")[0] for x in skipped}
    zero, scope_only, scope_empty, no_rid = [], [], [], []
    for fid, row in sorted(rec.manifest.items()):
        if fid in skipped_ids:
            continue
        kinds = per_file.get(fid, [])
        if not kinds:
            path = dataset_dir / row["file_path"]
            if declares_empty_scope(path, load_sql):
                scope_empty.append(fid)
                continue
            try:
                data = path.read_bytes()
                if not is_text_layer_document(data):  # structured file: T47 rule, refuses
                    zero.append(f"{fid}:zero-units:{row['file_path']}")
                    continue
                text, raw = text_and_raw(path, data, pdf_text)
            except Exception as exc:  # noqa: BLE001 -- an unreadable file is a failure, stated
                zero.append(f"{fid}:zero-units-unreadable:{type(exc).__name__}:{row['file_path']}")
                continue
            if not text.strip():
                zero.append(f"{fid}:zero-units-empty-text:{row['file_path']}")
            elif rid_re.search(raw):
                n = len(set(m.group(0).lower() for m in rid_re.finditer(raw)))
                zero.append(f"{fid}:zero-units-resource-id-unparsed:{n} resource-ID-shaped token(s):{row['file_path']}")
            else:
                no_rid.append(fid)
        elif set(kinds) <= SCOPE_UNIT_KINDS:
            scope_only.append(fid)
    failures = refused + zero + sorted(rec.log_line_failures)
    return {
        "ok": not failures,
        "allowed_skip_reasons": sorted(ALLOWED_SKIP_REASONS),
        "allowed_skips": allowed,
        "refused_skips": refused,
        "zero_unit_files": zero,
        "declared_scope_no_rows_files": scope_empty,
        "no_resource_id_files": no_rid,
        "resource_id_prefixes": resource_prefixes(extra_prefixes),
        "scope_marker_only_files": scope_only,
        "log_line_failures": sorted(rec.log_line_failures),
        "files_in_manifest": len(rec.manifest),
        "failures": failures,
    }


def check_producer(producer: Mapping[str, Any] | None, *, pred_sha256: str | None) -> dict[str, Any]:
    """Judge a producer record for ``evaluate.py score``.

    Statuses, in order of precedence:

    * ``refused``: a skip outside the allow-list, any failure, or an ``evidence_skipped`` /
      ``evidence_failures`` that is not a list (``null`` is not an empty list; note 2). Score
      must refuse.
    * ``unverified``: the record predates the guard (no ``evidence_failures``) or carries no
      ``output_sha256``, so it cannot be tied to the file being scored.
    * ``output-mismatch``: its ``output_sha256`` differs from ``pred_sha256``, the sha256 of
      the file being scored: the record describes another output (verifier F2, T72).
    * ``no-producer-record``: none found.
    * ``ok``: none of the above.

    Only ``ok`` runs may feed a report (T51, T60); the others are listed as excluded.
    """
    base = {"allowed_skips": [], "no_resource_id_files": [], "skip_count": None,
            "output_sha256": None, "pred_sha256": pred_sha256}
    if not producer:
        return {**base, "status": "no-producer-record", "reasons": [
            "no producer.json next to the prediction file: its evidence skips and failures cannot be checked"]}
    skipped_raw, failures_raw = producer.get("evidence_skipped"), producer.get("evidence_failures")
    reasons: list[str] = []
    if not isinstance(skipped_raw, list):
        reasons.append(f"evidence_skipped is {type(skipped_raw).__name__}, not a list")
    skipped = [str(x) for x in skipped_raw] if isinstance(skipped_raw, list) else []
    base = {**base, "allowed_skips": sorted(x for x in skipped if skip_allowed(x)),
            "no_resource_id_files": list(producer.get("evidence_no_resource_id_files") or []),
            "skip_count": producer.get("evidence_skip_count", len(skipped)),
            "output_sha256": producer.get("output_sha256")}
    reasons += [f"skip outside the allow-list: {x}" for x in sorted(x for x in skipped if not skip_allowed(x))]
    if "evidence_failures" in producer:
        if not isinstance(failures_raw, list):
            reasons.append(f"evidence_failures is {type(failures_raw).__name__}, not a list")
        else:
            reasons += [f"failure: {x}" for x in failures_raw]
    if reasons:
        return {**base, "status": "refused", "reasons": reasons}
    if "evidence_failures" not in producer:
        return {**base, "status": "unverified", "reasons": [
            "producer record predates the evidence guard (no evidence_failures field): zero-unit files and "
            "swallowed log-line errors were not checked"]}
    out_hash = producer.get("output_sha256")
    if not isinstance(out_hash, str) or not out_hash:
        return {**base, "status": "unverified", "reasons": [
            "producer record carries no output_sha256: it cannot be tied to the file being scored"]}
    if out_hash != pred_sha256:
        return {**base, "status": "output-mismatch", "reasons": [
            f"producer output_sha256 {out_hash[:16]}... differs from the scored file's sha256 "
            f"{str(pred_sha256)[:16]}...: the record describes another output"]}
    return {**base, "status": "ok", "reasons": []}
