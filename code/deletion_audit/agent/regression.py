"""The model-on regression gate: every row that differs from the approved output needs a cause, and
only two kinds of change pass (developer rulings T100 and T101).

Basis, rule by rule:

* **The baseline is the approved file** (T101 (1)). Its path and sha256 are read from
  ``notes/approved_output.json`` at run time, never from a constant, so approving a new file
  changes only that record. **One baseline per split** (developer ruling T117 B2): ``split="test"``
  reads ``approved_outputs.test`` (falling back to the legacy ``approved_output`` key, which the
  freeze check reads), ``split="dev"`` reads ``approved_outputs.dev``; ``split=None`` reads
  ``approved_output``. A split with no entry is refused, never silently swapped. The file's
  sha256 is checked before any row is read; a mismatch, a
  missing file or an unreadable record refuses the gate (:class:`BaselineRefused`), and a refused
  gate stops the run.
* **The cause is decided by recompiling, not by guessing** (T100, main's implementation note).
  For a changed row the pipeline recompiles the case three more times: with the model intent only
  (no image observations), with the image observations only (intent fail-closed, T71 Q2), and
  with both. A recompile *reproduces* the change when its row (status and ``steps_json``) is
  byte-equal to the run's row. Then:

  - ``intent``: the intent-only row reproduces it and the image-only row does not;
  - ``image``: the image-only row reproduces it and the intent-only row does not;
  - ``intent+image``: only both together reproduce it, or each alone does (the change cannot be
    put on one input);
  - ``unexplained``: none of these, which includes a changed row where neither input changed for
    the case (no model intent and no image involved), and a cause whose input did not change.
* **Allowed changes (T101 (2)), and only these:**

  1. ``intent``: the new row is NOT_APPLICABLE with ``[]``, every turn-1 reading (at least two:
     the case's own and each replicate namespace's) answered NOT_DELETION, and the intake
     cross-check agrees (``intake_non_deletion`` true; the cross-check is code over the inputs,
     so it is the same in both replicate runs).
  2. ``image``: every image involved was read OK and its two readings agree, every extracted
     resource ID involved is well-formed and named by another input, and every record of the case
     that waited on an image (``STATE_NEEDS_IMAGE`` in the image-free compile) got its state from
     an image (``notes/SYSTEM.md``: a failed read is never "nothing found").

  An image whose two readings disagree counts as agreeing for one case only under rule (a) below.
* **Candidate assembly by row (developer ruling T118 (2a), (2c)).** A changed row whose cause is
  ``intent``, ``image`` or ``intent+image`` and whose condition fails is ``kept_approved``: the
  output carries the approved file's row for that case, byte for byte, and the gate artifacts
  record it with its reason. It no longer fails the run. Only an ``unexplained`` change is
  ``stop`` (T100), and the gate passes when no ``stop`` remains. Basis: T118 (2): "otherwise its
  rows stay as approved"; "NOT_DELETION texts without an intake row stay as approved (T101)".
  ``intent+image`` is never ``allowed`` (T101 (2) names only the two single-input changes).
* **Rule (a), a disagreeing image (T118 (2a)):** it is accepted for a case only if each reading on
  its own gives the same engine derivation for every record of the case: per record
  ``(system_id, resource_id)``, its state value and the evidence IDs its steps cite, plus the row's
  FAILED_CLOSED reason. The pipeline recompiles the case once per combination of readings of the
  case's disagreeing images (each image's observations built from one reading alone), with the
  run's intent. Fields the engine does not derive from (``status_label``, review only) cannot
  matter, because only the derivation is compared. The merged reading the run used must give the
  same derivation too, so the shipped row is one each reading supports (a conservative addition:
  it can only keep more rows as approved). More than :data:`MAX_DISAGREEING` disagreeing images in
  one case are not enumerated and are not accepted (an explicit failure, never "agree").
* **Expectation, reported but not enforced** (T100): about the 10 non-deletion requests and the
  screenshot-dependent cases change, and nothing else. The Markdown puts the counts by cause next
  to it.

The artifact names case IDs, labels, file IDs, statuses and counts only: no request or evidence
text (``artifacts.py`` rule).
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

Cause = Literal["intent", "image", "intent+image", "unexplained"]
Verdict = Literal["allowed", "kept_approved", "stop"]
CAUSES: tuple[Cause, ...] = ("intent", "image", "intent+image", "unexplained")
GATE_JSON = "regression_vs_engine.json"
GATE_MD = "regression_vs_engine.md"
#: The most disagreeing images in one case that rule (a) enumerates (2**4 = 16 recompiles).
MAX_DISAGREEING = 4
EXPECTATION = ("about the 10 non-deletion requests and the screenshot-dependent cases change, and nothing else "
               "(T100; reported, not enforced)")


class BaselineRefused(ValueError):
    """The approved baseline cannot be used: record unreadable, file missing, or sha256 mismatch."""


@dataclass(frozen=True)
class Row:
    """One output row as written: the status and the exact ``steps_json`` text."""

    status: str
    steps_json: str

    @property
    def n_steps(self) -> int | None:
        """The number of steps, or None when ``steps_json`` is not a JSON list."""
        try:
            value = json.loads(self.steps_json)
        except ValueError:
            return None
        return len(value) if isinstance(value, list) else None


@dataclass(frozen=True)
class Baseline:
    """The approved output, checked against its recorded sha256."""

    record_path: str
    path: str
    sha256: str
    run_id: str | None
    rows: Mapping[str, Row]


def parse_rows(data: bytes) -> dict[str, Row]:
    """``{case_id: Row}`` from ``output.csv`` bytes; a duplicate case or a short row raises BaselineRefused."""
    reader = csv.reader(io.StringIO(data.decode("utf-8")))
    header = next(reader, None)
    if header != ["case_id", "deletion_status", "steps_json"]:
        raise BaselineRefused("the output file has an unexpected header")
    rows: dict[str, Row] = {}
    for line in reader:
        if len(line) != 3 or line[0] in rows:
            raise BaselineRefused("the output file has a short or duplicated row")
        rows[line[0]] = Row(line[1], line[2])
    return rows


def _approved_entry(record: Mapping[str, Any], split: str | None) -> Mapping[str, Any]:
    """The record's entry for ``split`` (module docstring: one baseline per split, T117 B2)."""
    per_split = record.get("approved_outputs") if split is not None else None
    entry: Any
    if isinstance(per_split, Mapping) and split in per_split:
        entry = per_split[split]
    elif split is None or split == "test":
        entry = record["approved_output"]
    else:
        raise KeyError(f"no approved {split} output in the record")
    if not isinstance(entry, Mapping):
        raise TypeError("an approved-output entry is not an object")
    return entry


def load_baseline(record_path: Path, repo_root: Path, split: str | None = None) -> Baseline:
    """Read the approved-output record, check the file's sha256, and parse its rows (module docstring)."""
    try:
        record = json.loads(Path(record_path).read_text(encoding="utf-8"))
        approved = _approved_entry(record, split)
        rel, sha = str(approved["path"]), str(approved["sha256"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise BaselineRefused(f"the approved-output record is unreadable ({type(exc).__name__})") from exc
    path = Path(rel) if Path(rel).is_absolute() else Path(repo_root) / rel
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise BaselineRefused(f"the approved output file {rel} cannot be read ({type(exc).__name__})") from exc
    actual = hashlib.sha256(data).hexdigest()
    if actual != sha:
        raise BaselineRefused(f"the approved output file {rel} has sha256 {actual[:16]}..., the record says "
                              f"{sha[:16]}...: refused")
    try:
        shown = str(Path(record_path).resolve().relative_to(Path(repo_root).resolve()))
    except ValueError:
        shown = str(record_path)
    return Baseline(shown, rel, sha, approved.get("run_id"), parse_rows(data))


@dataclass(frozen=True)
class IdFacts:
    """One extracted ID of an involved image, with its T88 (2) checks."""

    shown_id: str
    resource_id: str | None
    basis: str
    well_formed: bool
    named_elsewhere: bool


@dataclass(frozen=True)
class RecordView:
    """What the engine derived for one record of a case (rule (a)): its state and cited evidence IDs."""

    system_id: str
    resource_id: str
    state: str | None
    cited: tuple[str, ...]


@dataclass(frozen=True)
class Derivation:
    """The engine's per-record derivation for one case, plus the row's FAILED_CLOSED reason (rule (a))."""

    failed_closed: str | None
    records: tuple[RecordView, ...]

    def as_json(self) -> dict[str, Any]:
        """IDs and states only (``artifacts.py`` rule)."""
        return {"failed_closed": self.failed_closed,
                "records": [{"system_id": r.system_id, "resource_id": r.resource_id, "state": r.state,
                             "cited": list(r.cited)} for r in self.records]}


@dataclass(frozen=True)
class SingleReadingCheck:
    """Rule (a) for one disagreeing image in one case: accepted, why, and each derivation compared."""

    file_id: str
    accepted: bool
    reason: str
    by_readings: tuple[tuple[tuple[tuple[str, int], ...], Derivation], ...] = ()  # ((file, reading 1|2)...), derivation
    merged: Derivation | None = None

    def as_json(self) -> dict[str, Any]:
        """The artifact form: each reading combination with its derivation, and the merged one."""
        return {"file_id": self.file_id, "accepted": self.accepted, "reason": self.reason,
                "by_readings": [{"readings": {f: k for f, k in combo}, **d.as_json()} for combo, d in self.by_readings],
                "merged": self.merged.as_json() if self.merged is not None else None}


def judge_single_readings(files: Sequence[str], derivations: Mapping[tuple[int, ...], Derivation],
                          merged: Derivation | None) -> tuple[SingleReadingCheck, ...]:
    """Rule (a) (module docstring). ``derivations`` maps a reading choice per file of ``files``
    (0 = reading 1, 1 = reading 2) to the case's derivation; a missing combination counts as a
    difference. Image ``i`` is accepted when every pair of combinations that differ only in its
    reading gives the same derivation and every combination equals the merged derivation."""
    n = len(files)
    combos = [c for c in sorted(derivations) if len(c) == n]
    complete = n > 0 and len(combos) == 2 ** n
    all_merged = complete and merged is not None and all(derivations[c] == merged for c in combos)
    shown = tuple((tuple((f, k + 1) for f, k in zip(files, c, strict=True)), derivations[c]) for c in combos)
    out = []
    for i, fid in enumerate(files):
        pairs = [(c, c[:i] + (1,) + c[i + 1:]) for c in combos if c[i] == 0]
        same = complete and all(b in derivations and derivations[a] == derivations[b] for a, b in pairs)
        if not complete:
            reason = "not every reading combination was compiled"
        elif not same:
            reason = "the two readings give different states or cited IDs for a record of the case"
        elif not all_merged:
            reason = "the readings agree with each other but the merged reading the run used derives differently"
        else:
            reason = "each reading alone gives the same state and cited IDs for every record"
        out.append(SingleReadingCheck(fid, same and all_merged, reason, shown, merged))
    return tuple(out)


@dataclass(frozen=True)
class ImageFacts:
    """One image involved in a case: whether both readings succeeded and agree, and its involved IDs.
    ``single`` is rule (a)'s check for a disagreeing image (None when not computed)."""

    file_id: str
    read_ok: bool
    agree: bool | None
    ids: tuple[IdFacts, ...] = ()
    single: SingleReadingCheck | None = None

    @property
    def usable(self) -> bool:
        """Read OK, and its readings agree or rule (a) accepted it for this case."""
        return self.read_ok and (self.agree is True or (self.agree is False and self.single is not None
                                                         and self.single.accepted))


@dataclass(frozen=True)
class CaseEvidence:
    """What the gate needs about one changed row: the recompiles and the inputs that may explain it."""

    case_id: str
    after: Row
    intent_only: Row
    image_only: Row
    both: Row
    intent_changed: bool  # the case has a model intent decision (not the fail-closed one)
    intent_label: str | None
    intent_source: str
    turn1_labels: tuple[str | None, ...]
    intake_non_deletion: bool
    images: tuple[ImageFacts, ...] = ()
    waiting_resources: tuple[str, ...] = ()  # records flagged STATE_NEEDS_IMAGE in the image-free compile
    image_resources: tuple[str, ...] = ()  # records an involved image gave an observation for
    loop_status: str | None = None  # the agent loop's status (OK, FINALIZED_AT_CAP, FAILED); None: not known


def classify(ev: CaseEvidence) -> tuple[Cause, str]:
    """The cause of one changed row, and how it was decided (module docstring)."""
    ri, rm, rb = ev.intent_only == ev.after, ev.image_only == ev.after, ev.both == ev.after
    seen = f"reproduced by: intent-only {ri}, image-only {rm}, both {rb}"
    if not ev.intent_changed and not ev.images:
        return "unexplained", f"neither input changed for this case; {seen}"
    if ri and not rm:
        if ev.intent_changed:
            return "intent", seen
        return "unexplained", f"the intent-only compile reproduces it but the case has no model intent; {seen}"
    if rm and not ri:
        if ev.images:
            return "image", seen
        return "unexplained", f"the image-only compile reproduces it but no image is involved; {seen}"
    if ri and rm:
        if ev.intent_changed and ev.images:
            return "intent+image", f"each input alone reproduces it, so it cannot be put on one; {seen}"
        return "unexplained", f"both compiles reproduce it without both inputs changing; {seen}"
    if rb and ev.intent_changed and ev.images:
        return "intent+image", seen
    return "unexplained", seen


def _intent_condition(ev: CaseEvidence) -> tuple[bool, str]:
    """T101 (2a), plus T109 (b): the case's agent loop did not fail (a loop status that is FAILED, or
    not known, never allows an intent change, whatever turn 1 said)."""
    parts = []
    loop_ok = ev.loop_status is not None and ev.loop_status != "FAILED"
    parts.append(f"agent loop status {ev.loop_status} is not FAILED: {loop_ok}")
    na = ev.after.status == "NOT_APPLICABLE" and ev.after.steps_json == "[]"
    parts.append(f"new row NOT_APPLICABLE with []: {na}")
    readings = ev.turn1_labels
    reps = len(readings) >= 2 and all(label == "NOT_DELETION" for label in readings)
    parts.append(f"turn-1 readings {list(readings)} all NOT_DELETION (at least 2): {reps}")
    parts.append(f"intake cross-check intake_non_deletion: {ev.intake_non_deletion}")
    return loop_ok and na and reps and ev.intake_non_deletion, "; ".join(parts)


def _image_condition(ev: CaseEvidence) -> tuple[bool, str]:
    """T101 (2b), plus the waiting-record check (module docstring)."""
    bad_images = sorted(i.file_id for i in ev.images if not i.usable)
    by_rule_a = sorted(i.file_id for i in ev.images if i.read_ok and i.agree is False and i.usable)
    bad_ids = sorted({f"{i.file_id}:{x.resource_id or '(unusable id)'}:{x.basis}" for i in ev.images for x in i.ids
                      if not (x.well_formed and x.named_elsewhere and x.resource_id)})
    missing = sorted(set(ev.waiting_resources) - set(ev.image_resources))
    ok = bool(ev.images) and not bad_images and not bad_ids and not missing
    def part(text: str, bad: Sequence[str]) -> str:
        """One condition: whether it holds, and what broke it."""
        return f"{text}: {not bad}" + (f" (not: {list(bad)})" if bad else "")

    parts = [f"images involved {sorted(i.file_id for i in ev.images)}",
             part("read OK with agreeing readings", bad_images)
             + (f" (disagreeing but accepted by T118 rule (a): {by_rule_a})" if by_rule_a else ""),
             part("extracted IDs well-formed and named elsewhere", bad_ids),
             part("records waiting on an image got an image state", missing)]
    return ok, "; ".join(parts)


def verdict(cause: Cause, ev: CaseEvidence) -> tuple[Verdict, str]:
    """``allowed`` only for the two T101 changes whose conditions hold; an explained change whose
    condition fails is ``kept_approved`` (T118 (2a), (2c)); only an unexplained change is ``stop`` (T100)."""
    if cause == "intent":
        ok, why = _intent_condition(ev)
        return ("allowed" if ok else "kept_approved"), why
    if cause == "image":
        ok, why = _image_condition(ev)
        return ("allowed" if ok else "kept_approved"), why
    if cause == "intent+image":
        return "kept_approved", "an intent+image change is never allowed (T101 (2)); the approved row is kept (T118)"
    return "stop", "an unexplained change stops the run (T100)"


@dataclass
class GateResult:
    """The gate's outcome for one run."""

    baseline: dict[str, Any]
    rows_compared: int
    changed: list[dict[str, Any]] = field(default_factory=list)
    refusal: str | None = None
    assembled: dict[str, Row] = field(default_factory=dict)  # the output rows: kept-approved rows replaced

    @property
    def stops(self) -> list[dict[str, Any]]:
        """The changed rows marked ``stop``."""
        return [r for r in self.changed if r["verdict"] == "stop"]

    @property
    def kept(self) -> list[dict[str, Any]]:
        """The changed rows whose approved row is kept (T118)."""
        return [r for r in self.changed if r["verdict"] == "kept_approved"]

    @property
    def passed(self) -> bool:
        """No refusal and no ``stop`` row."""
        return self.refusal is None and not self.stops

    def as_json(self) -> dict[str, Any]:
        """The artifact body (canonical: rows in case order, counts sorted)."""
        return {
            "kind": "regression-vs-engine",
            "baseline": self.baseline,
            "rows_compared": self.rows_compared,
            "changed_rows": len(self.changed),
            "by_cause": {c: sum(1 for r in self.changed if r["cause"] == c) for c in CAUSES},
            "by_verdict": dict(sorted(Counter(r["verdict"] for r in self.changed).items())),
            "passed": self.passed,
            "refusal": self.refusal,
            "kept_approved_cases": [r["case_id"] for r in self.kept],
            "expectation": EXPECTATION,
            "rows": self.changed,
        }

    def summary(self) -> dict[str, Any]:
        """The producer-record summary."""
        body = self.as_json()
        keys = ("baseline", "rows_compared", "changed_rows", "by_cause", "by_verdict", "passed", "refusal",
                "kept_approved_cases")
        return {k: body[k] for k in keys} | {"stop_cases": [r["case_id"] for r in self.stops]}


def run_gate(baseline: Baseline | BaselineRefused, after: Mapping[str, Row],
             evidence_for: Callable[[str], CaseEvidence]) -> GateResult:
    """Compare ``after`` with the baseline and judge every changed row (module docstring).

    ``evidence_for`` is called only for a changed row. A refused baseline, or a run whose case set
    differs from the baseline's, gives a refused result with no row judged and nothing assembled.
    Otherwise ``assembled`` is ``after`` with each ``kept_approved`` row replaced by the baseline's
    row (T118: byte for byte).
    """
    if isinstance(baseline, BaselineRefused):
        return GateResult({"checked": False}, 0, refusal=str(baseline))
    info = {"checked": True, "record": baseline.record_path, "path": baseline.path, "sha256": baseline.sha256,
            "run_id": baseline.run_id}
    if set(after) != set(baseline.rows):
        extra, lost = len(set(after) - set(baseline.rows)), len(set(baseline.rows) - set(after))
        return GateResult(info, 0, refusal=f"the run's cases differ from the baseline's ({extra} not in the "
                                           f"baseline, {lost} missing from the run)")
    result = GateResult(info, len(after))
    for cid in sorted(after, key=_case_order):
        before, now = baseline.rows[cid], after[cid]
        result.assembled[cid] = now
        if before == now:
            continue
        ev = evidence_for(cid)
        cause, how = classify(ev)
        decided, condition = verdict(cause, ev)
        if decided == "kept_approved":
            result.assembled[cid] = before
        result.changed.append({
            "case_id": cid, "cause": cause, "decided_by": how, "verdict": decided, "condition": condition,
            "kept_approved": decided == "kept_approved",
            "intent_label": ev.intent_label, "intent_source": ev.intent_source,
            "turn1_labels": list(ev.turn1_labels), "intake_non_deletion": ev.intake_non_deletion,
            "image_file_ids": sorted(i.file_id for i in ev.images),
            "single_reading_checks": [i.single.as_json() for i in ev.images if i.single is not None],
            "before": {"status": before.status, "n_steps": before.n_steps},
            "after": {"status": now.status, "n_steps": now.n_steps},
            "output": {"status": result.assembled[cid].status, "n_steps": result.assembled[cid].n_steps},
        })
    return result


def _case_order(case_id: str) -> tuple[int, str]:
    """Numeric case order (``case_<digits>``), then the text."""
    digits = case_id.rpartition("_")[2]
    return (int(digits) if digits.isdigit() else -1, case_id)


def render_markdown(result: GateResult, run_id: str) -> str:
    """A short review page: the verdict, counts by cause next to the expectation, one line per changed row."""
    body = result.as_json()
    lines = [f"# Model-on regression gate: run {run_id}", "",
             f"- Baseline: `{body['baseline'].get('path')}` sha256 `{str(body['baseline'].get('sha256'))[:16]}...` "
             f"(from `{body['baseline'].get('record')}`; checked: {body['baseline'].get('checked')}).",
             f"- Rows compared: {body['rows_compared']}; changed: {body['changed_rows']}.",
             f"- **Passed: {body['passed']}**" + (f"; refusal: {body['refusal']}" if body["refusal"] else ""), "",
             "| cause | changed rows |", "|---|---|"]
    lines += [f"| {c} | {n} |" for c, n in body["by_cause"].items()]
    lines += ["", f"Expected: {EXPECTATION}. Verdicts: {body['by_verdict'] or '{}'}.",
              f"Kept as approved (T118; the output carries the approved row): {body['kept_approved_cases'] or 'none'}.",
              ""]
    if result.changed:
        lines += ["| case | cause | verdict | intent label | images | before | after | condition |",
                  "|---|---|---|---|---|---|---|---|"]
        for r in result.changed:
            before, after = r["before"], r["after"]
            lines.append(f"| {r['case_id']} | {r['cause']} | {r['verdict']} | {r['intent_label']} | "
                         f"{', '.join(r['image_file_ids']) or '-'} | {before['status']} ({before['n_steps']}) "
                         f"| {after['status']} ({after['n_steps']}) | {r['condition']} |")
        lines.append("")
    checks = [(r["case_id"], c) for r in result.changed for c in r["single_reading_checks"]]
    if checks:
        lines += ["## Disagreeing images: rule (a) (T118 (2a))", "",
                  "| case | image | accepted | reason | per reading: (resource, state, cited) |",
                  "|---|---|---|---|---|"]
        for cid, c in checks:
            per = "; ".join(
                f"{b['readings']}: fc={b['failed_closed']} "
                + ", ".join(f"({x['resource_id']}, {x['state']}, {'+'.join(x['cited']) or '-'})" for x in b["records"])
                for b in c["by_readings"])
            lines.append(f"| {cid} | {c['file_id']} | {c['accepted']} | {c['reason']} | {per} |")
        lines.append("")
    return "\n".join(lines)


def write_gate(run_dir: Path, result: GateResult, run_id: str) -> tuple[Path, Path]:
    """Write ``regression_vs_engine.json`` and ``.md`` under ``run_dir``; return both paths."""
    run_dir.mkdir(parents=True, exist_ok=True)
    js, md = run_dir / GATE_JSON, run_dir / GATE_MD
    js.write_text(json.dumps(result.as_json(), indent=1, sort_keys=True) + "\n", encoding="utf-8")
    md.write_text(render_markdown(result, run_id), encoding="utf-8")
    return js, md


def image_facts(file_ids: Sequence[str], records: Mapping[str, Any],
                resources: frozenset[str]) -> tuple[ImageFacts, ...]:
    """Facts for the involved images. ``records`` maps file ID to the vision step's ``ImageReadRecord``;
    involved IDs are the usable IDs naming one of ``resources`` plus every ID that looked like a
    resource ID but did not fit (``malformed`` or ``ambiguous``). A file the vision step has no record
    of counts as not read."""
    out = []
    for fid in sorted(set(file_ids)):
        rec = records.get(fid)
        if rec is None:
            out.append(ImageFacts(fid, False, None))
            continue
        ids = tuple(IdFacts(c.shown_id, c.resource_id, c.basis, c.well_formed, c.named_elsewhere) for c in rec.ids
                    if (c.resource_id and c.resource_id in resources) or c.basis in ("malformed", "ambiguous"))
        out.append(ImageFacts(fid, rec.status == "OK", rec.agree, ids))
    return tuple(out)
