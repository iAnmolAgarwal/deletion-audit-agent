"""Custom eval cases (research/18 C6): spec-derived fixtures scored apart from DEV and holdout.

**Which cases.** A fixture folder under ``code/tests/fixtures/`` (red-team folders one level
deeper) holds a custom eval case when its ``EXPECTED.md`` has a mark line
``**Custom eval case:** yes ...`` or ``**G8 custom eval case:** yes ...`` (bold ``**yes**``
allowed). The mark is read from the file, never from a list in code. When the mark names case
IDs (``yes, case_<n>``), only those are custom cases; otherwise every case the folder's
expectation files hold is.

**What they are scored against**, in this order: the folder's ``expected_output.csv``, then
``expected_partial.csv`` (both in the output layout, read with ``outputs.read_output``), then
the ``cases`` block of ``expected_assertions.json``. A row expectation is scored with
``scorer.score_case``; the custom cases' aggregate uses ``scorer.aggregate``, so the metric
definitions are the DEV ones. An assertion expectation checks the keys
:data:`ASSERTION_KEYS`; any other key is listed as not checked, never passed.

**Which run.** The spec maps a fixture folder to the run that solved it
(``custom_runs``). A custom case whose folder has no run is reported as not run, never as a
zero. Every such run passed the producer check before it gets here (``report_spec``).
"""
from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .agent_report import FIXTURES_ROOT, LoadedRun
from .gold import GoldCase
from .outputs import CASE_ID_RE, OutputFile, OutputRow, read_output
from .scorer import aggregate, score_case

EXPECTED_MD = "EXPECTED.md"
ROW_FILES: tuple[str, ...] = ("expected_output.csv", "expected_partial.csv")
ASSERTIONS_FILE = "expected_assertions.json"
ASSERTION_KEYS: tuple[str, ...] = ("deletion_status", "deletion_status_never", "never_cite", "row_state",
                                   "failed_closed")
MARK_RE: re.Pattern[str] = re.compile(
    r"^\*\*(?:G8 )?custom eval case:\*\*\s*(?:\*\*)?\s*(?P<answer>yes|no)\b(?P<rest>.*)$", re.I | re.M)
IDS_AFTER_YES_RE: re.Pattern[str] = re.compile(r"^((?:\s*(?:,|and)?\s*case_[0-9]+)*)")
STATEMENT_RE: re.Pattern[str] = re.compile(r"(?<!\*)\*(?!\*)([^*\n]{1,400})\*(?!\*)")
PROVISIONAL_RE: re.Pattern[str] = re.compile(r"\*\*Provisional:\*\*\s*\**\s*(yes|no)\b", re.I)
TESTS_RE: re.Pattern[str] = re.compile(r"^\*\*Tests:\*\*\s*(?:-\s*)?(\S[^\n]{0,300})", re.M)


@dataclass(frozen=True)
class Expectation:
    """What one custom case must produce: a row, or a set of assertions."""

    source: str                       # the file it came from, relative to the fixtures root
    row: OutputRow | None = None
    assertions: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class CustomCase:
    """One marked case: where it lives, why it is there, what it expects."""

    folder: str                       # relative to the fixtures root, POSIX form
    case_id: str
    mark_line: str
    statement: str | None
    provisional: str | None
    expectation: Expectation | None
    problem: str | None = None        # why the expectation could not be read


def _rel(p: Path, root: Path) -> str:
    return p.relative_to(root).as_posix()


def _read_rows(path: Path) -> OutputFile | None:
    return read_output(path) if path.is_file() else None


def expectations(folder: Path, root: Path) -> tuple[dict[str, Expectation], list[str]]:
    """Every case the folder's expectation files hold, first file wins; plus read problems."""
    out: dict[str, Expectation] = {}
    problems: list[str] = []
    for name in ROW_FILES:
        f = _read_rows(folder / name)
        if f is None:
            continue
        problems += [f"{_rel(folder / name, root)}: {i}" for i in f.issues]
        for cid in f.order:
            r = f.rows[cid]
            if r.steps is None:
                problems.append(f"{_rel(folder / name, root)}: {cid} steps_json does not parse")
                continue
            out.setdefault(cid, Expectation(_rel(folder / name, root), row=r))
    a = folder / ASSERTIONS_FILE
    if a.is_file():
        try:
            raw = json.loads(a.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            problems.append(f"{_rel(a, root)}: unreadable ({type(exc).__name__})")
            raw = {}
        cases = raw.get("cases") if isinstance(raw, Mapping) else None
        common = raw.get("all_cases") if isinstance(raw, Mapping) else None
        for cid, body in (cases or {}).items():
            if CASE_ID_RE.fullmatch(str(cid)) and isinstance(body, Mapping):
                merged = {**(common if isinstance(common, Mapping) else {}), **body}
                out.setdefault(cid, Expectation(_rel(a, root), assertions=merged))
    return out, problems


def discover(fixtures_root: Path = FIXTURES_ROOT) -> list[CustomCase]:
    """Every case marked as a custom eval case, in folder then case order."""
    found: list[CustomCase] = []
    for md in sorted(fixtures_root.rglob(EXPECTED_MD)):
        text = md.read_text(encoding="utf-8")
        m = next((x for x in MARK_RE.finditer(text) if x.group("answer").lower() == "yes"), None)
        if m is None:
            continue
        folder = md.parent
        rest = m.group("rest")
        lead = IDS_AFTER_YES_RE.match(rest.lstrip(" ,"))
        named = re.findall(r"case_[0-9]+", lead.group(1)) if lead else []
        st = STATEMENT_RE.search(rest)
        plain = re.sub(r"^[\s.,*]+|case_[0-9]+", "", rest).strip(" .*") if not st else ""
        tests = TESTS_RE.search(text)
        statement = st.group(1).strip() if st else (plain or (tests.group(1).strip() if tests else None))
        prov = PROVISIONAL_RE.search(text)
        expected, problems = expectations(folder, fixtures_root)
        ids = named or sorted(expected)
        rel = _rel(folder, fixtures_root)
        if not ids:
            found.append(CustomCase(rel, "<none>", m.group(0).strip(), None, None, None,
                                    "marked, but no expectation file holds a case"))
            continue
        for cid in ids:
            exp = expected.get(cid)
            problem = None if exp else f"no expectation for {cid} in {', '.join([*ROW_FILES, ASSERTIONS_FILE])}"
            if problems and exp is None:
                problem = f"{problem}; read problems: {'; '.join(problems)}"
            found.append(CustomCase(rel, cid, m.group(0).strip(), statement,
                                    prov.group(1).lower() if prov else None, exp, problem))
    return found


def _cited(row: OutputRow | None) -> set[str]:
    if row is None:
        return set()
    return {str(s["evidence_id"]) for s in (row.steps or []) if isinstance(s, Mapping) and s.get("evidence_id")}


def check_assertions(assertions: Mapping[str, Any], row: OutputRow | None,
                     record: Mapping[str, Any] | None) -> dict[str, Any]:
    """Check the supported assertion keys on one predicted row and its ``cases.jsonl`` record."""
    results: dict[str, bool | None] = {}
    if "deletion_status" in assertions:
        results["deletion_status"] = row is not None and row.status == assertions["deletion_status"]
    if "deletion_status_never" in assertions:
        results["deletion_status_never"] = row is not None and row.status not in assertions["deletion_status_never"]
    if "never_cite" in assertions:
        results["never_cite"] = row is not None and not (_cited(row) & set(assertions["never_cite"]))
    if "row_state" in assertions:
        results["row_state"] = None if record is None else record.get("row_state") == assertions["row_state"]
    if "failed_closed" in assertions:
        results["failed_closed"] = None if record is None else (
            (record.get("failed_closed") is not None) == bool(assertions["failed_closed"]))
    not_checked = sorted(set(assertions) - set(ASSERTION_KEYS))
    return {"checked": results, "not_checked": not_checked,
            "passed": all(v is True for v in results.values()) and bool(results)}


def records_by_case(run: LoadedRun) -> dict[str, Mapping[str, Any]]:
    """Raw ``cases.jsonl`` lines by case ID (only row_state and failed_closed are read from them)."""
    out: dict[str, Mapping[str, Any]] = {}
    try:
        text = (run.run_dir / "cases.jsonl").read_text(encoding="utf-8")
    except OSError:
        return out
    for line in text.splitlines():
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(raw, Mapping) and isinstance(raw.get("case_id"), str):
            out.setdefault(raw["case_id"], raw)
    return out


def score_custom(cases: Sequence[CustomCase], custom_runs: Mapping[str, str],
                 loaded: Mapping[str, LoadedRun]) -> dict[str, Any]:
    """Score every custom case against its expectation, from the run its folder maps to."""
    per_case: list[dict[str, Any]] = []
    row_scores: list[dict[str, Any]] = []
    for c in cases:
        base: dict[str, Any] = {"folder": c.folder, "case_id": c.case_id, "mark": c.mark_line,
                                "statement": c.statement, "provisional": c.provisional,
                                "expected_source": c.expectation.source if c.expectation else None}
        if c.expectation and c.expectation.row is not None:
            er = c.expectation.row
            base["expected"] = {"status": er.status, "steps": len(er.steps or [])}
        elif c.expectation and c.expectation.assertions is not None:
            base["expected"] = {"assertions": sorted(c.expectation.assertions)}
        rid = custom_runs.get(c.folder)
        if c.problem or c.expectation is None:
            per_case.append({**base, "result": "expectation unreadable", "problem": c.problem})
            continue
        if rid is None:
            per_case.append({**base, "result": "not run", "run_id": None})
            continue
        run = loaded[rid]
        assert run.output is not None  # a checked run has an output.csv
        pred = run.output.rows.get(c.case_id)
        if c.expectation.row is not None:
            er = c.expectation.row
            sc = score_case(pred, GoldCase(c.case_id, er.status, list(er.steps or [])))
            row_scores.append(sc)
            per_case.append({**base, "run_id": rid, "result": "row exact" if sc["row_exact"] else "row differs",
                             "pred_status": sc["pred_status"], "status_ok": sc["status_ok"],
                             "row_exact": sc["row_exact"], "step_tp": sc["step_tp"], "n_pred": sc["n_pred"],
                             "n_gold": sc["n_gold"], "missing_steps": len(sc["diff"]["missing_steps"]),
                             "extra_steps": len(sc["diff"]["extra_steps"]),
                             "field_mismatches": len(sc["diff"]["field_mismatches"])})
        else:
            assert c.expectation.assertions is not None
            res = check_assertions(c.expectation.assertions, pred, records_by_case(run).get(c.case_id))
            per_case.append({**base, "run_id": rid, "result": "assertions pass" if res["passed"] else
                             "assertions fail", "pred_status": pred.status if pred else "MISSING", **res})
    scored = [p for p in per_case if p["result"] in ("row exact", "row differs", "assertions pass",
                                                       "assertions fail")]
    return {
        "measured": "scorer.score_case on each case's expected row (or the supported assertion keys), from the "
                    "run named for its fixture folder in the spec's custom_runs",
        "cases": per_case,
        "marked": len(per_case),
        "scored": len(scored),
        "not_run": sum(1 for p in per_case if p["result"] == "not run"),
        "passed": sum(1 for p in per_case if p["result"] in ("row exact", "assertions pass")),
        "row_aggregate": aggregate(row_scores)["published"] if row_scores else None,
    }
