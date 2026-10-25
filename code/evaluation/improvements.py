"""The "failures found and improvements made" section, generated from the ledger (T111, T113).

The ledger is ``code/evaluation/improvements.json`` (shipped in code.zip): paths, anchors, T-numbers, commits, run IDs and test
names only. **It holds no typed description and no number.** Every quoted line is read from the
anchored file; every metric is computed here from two producer-checked runs; every test is run
here. The format::

    {"entries": [
      {"id": "I01",
       "failure": {"kind": "verifier",               # verifier | redteam | custom_eval | review | judge
                   "path": "notes/verify/g5_verify.md",   # repo-relative .md or .txt file
                   "anchor": "**1. MAJOR:",          # review: the log.txt timestamp of the developer's turn
                   "line": "(a) ...",                 # optional: a line inside the anchored section
                   "case": "case_<n>"},               # redteam and custom_eval only (required there)
       "fix": {"ruling": "T90", "commit": "5819121",     # "PENDING" until main fills it in
               "clause": "(2) G5:"},                      # optional: where in the ruling's row to quote from
       "evidence": {"test": "code/tests/x/test_y.py::Class.test_name"}}
       # or "evidence": {"metric": {"name": "row_exact", "scope": "dev",
       #                            "before_run": "<run id>", "after_run": "<run id>"}}
    ]}

**What the generator quotes.** The anchor must match exactly one line of the file (for
``review``: exactly one ``## [<timestamp>]`` heading of ``log.txt``). The quote is that line (a
heading's text without its ``#``), then either the ``line`` locator's line, which must occur
exactly once in the anchored section, quoted from the locator onwards, or, for a heading, the
first content line under it (bare section labels ending in ``:`` are skipped). Each part is cut at
:data:`QUOTE_MAX` characters; a locator's line and a ruling clause end at their first sentence.
Every cut is marked ``…[cut]``. "Before" is the cited failure itself.

**Evidence.**
* A **test** must exist (found in the file's syntax tree) and pass. It is checked by **running that
  one test at build time** in ``code/`` (one subprocess for all the ledger's tests, each test
  loaded by name, its result recorded on its own); a skipped test or a test that runs nothing is
  not a pass. The record names the git HEAD, the test file's sha256 and whether that file differs
  from HEAD.
* A **metric** is computed from two runs, each of which must pass the producer check
  (``evidence_guard.check_producer`` on its ``output.csv``). It never takes a value from a
  verifier probe. A metric that did not move, or got worse, is shown as such.

**Refused** (the entry is shown as REFUSED with its reasons, and the build reports a
cross-check failure): an unknown key, a missing path or anchor, an anchor or locator that matches
no line or several, a ruling not in ``notes/DECISIONS.md``, a commit not in history
(``git cat-file -e``), a missing or failing test, an unchecked or missing run, an unknown metric
name or a scope the metric does not support. **PENDING** commits are checked in every other
respect and shown as pending, never as an improvement made; they also count as a cross-check
failure, so ``reports.py --publish`` refuses until main fills them in.
"""
from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import custom_cases, runs
from .agent_report import LoadedRun, load_run
from .freeze_check import is_failed_closed
from .gold import GoldCase, load_gold
from .scorer import score_predictions

KINDS: tuple[str, ...] = ("verifier", "redteam", "custom_eval", "review", "judge")
CASE_KINDS: frozenset[str] = frozenset({"redteam", "custom_eval"})
TOP_KEYS: frozenset[str] = frozenset({"entries", "comment"})
ENTRY_KEYS: frozenset[str] = frozenset({"id", "failure", "fix", "evidence"})
FAILURE_KEYS: frozenset[str] = frozenset({"kind", "path", "anchor", "line", "case"})
FIX_KEYS: frozenset[str] = frozenset({"ruling", "commit", "clause"})
METRIC_KEYS: frozenset[str] = frozenset({"name", "scope", "before_run", "after_run"})
PENDING = "PENDING"
QUOTE_MAX = 320
TEXT_SUFFIXES: tuple[str, ...] = (".md", ".txt")
FORBIDDEN_TOP: frozenset[str] = frozenset({"dataset", "cache", ".env", ".git", ".venv"})
LOG_FILE = "log.txt"
ID_RE: re.Pattern[str] = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,31}", re.ASCII)
CASE_RE: re.Pattern[str] = re.compile(r"case_[0-9]+", re.ASCII)
RULING_RE: re.Pattern[str] = re.compile(r"T[0-9]{1,4}", re.ASCII)
COMMIT_RE: re.Pattern[str] = re.compile(r"[0-9a-f]{7,40}", re.ASCII)
TIMESTAMP_RE: re.Pattern[str] = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d", re.ASCII)
TEST_REF_RE: re.Pattern[str] = re.compile(
    r"(?P<path>code/[A-Za-z0-9_/]+\.py)::(?P<name>[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)", re.ASCII)
RESULT_MARK = "@@IMPROVEMENTS_TEST_RESULT@@"
TEST_TIMEOUT_S = 1800
LABEL_LINE_RE: re.Pattern[str] = re.compile(r"^[A-Z][A-Za-z ()',]{0,60}:$")

# One subprocess runs every ledger test, each loaded by name and run on its own.
RUNNER = f"""
import io, json, sys, unittest
out = {{}}
for tid in sys.argv[1:]:
    suite = unittest.defaultTestLoader.loadTestsFromName(tid)
    res = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(suite)
    out[tid] = {{"ran": res.testsRun, "failures": len(res.failures), "errors": len(res.errors),
                "skipped": len(res.skipped), "ok": res.wasSuccessful() and res.testsRun > 0 and not res.skipped}}
print({RESULT_MARK!r} + json.dumps(out))
"""

TestRunner = Callable[[Sequence[str], Path], dict[str, dict[str, Any]]]
GitRunner = Callable[[Sequence[str]], tuple[int, str]]


@dataclass(frozen=True)
class Metric:
    """A metric the ledger may name: the scopes it is defined on and which way is better."""

    name: str
    scopes: tuple[str, ...]          # "dev" (scored against DEV gold), "test", "custom"
    direction: str | None            # "higher", "lower" or None (a change is reported, never judged)
    measured: str


DEV_RATES: Mapping[str, tuple[str, ...]] = {
    "status_accuracy": ("status_accuracy",), "row_exact": ("row_exact",), "steps_exact": ("steps_exact",),
    "sequence_exact": ("sequence_exact",), "pairwise_order": ("sequence_pairwise_order",),
    "citation_set_exact": ("citation_set_exact",), "field_state": ("field_on_matched", "state"),
    "field_evidence_id": ("field_on_matched", "evidence_id"), "field_step_no": ("field_on_matched", "step_no"),
}
_DEV_MEASURED = "evaluation.scorer.score_predictions on runs/<id>/output.csv against DEV gold (gold.load_gold defaults)"
METRICS: Mapping[str, Metric] = {
    **{n: Metric(n, ("dev",), "higher", f"{_DEV_MEASURED}: published {'.'.join(p)}") for n, p in DEV_RATES.items()},
    "step_f1": Metric("step_f1", ("dev",), "higher", f"{_DEV_MEASURED}: published step.f1"),
    "fail_closed_rows": Metric("fail_closed_rows", ("dev", "test"), None,
                               "cases.jsonl records with row_state FAILED_CLOSED (freeze_check.is_failed_closed)"),
    "custom_passed": Metric("custom_passed", ("custom",), "higher",
                            "custom_cases.score_custom: marked custom cases of the folder that pass their expectation"),
}


@dataclass(frozen=True)
class LedgerEnv:
    """Where the ledger checks read. Production uses the defaults through ``evaluation_report.Context``."""

    repo_root: Path
    runs_root: Path
    gold_path: Path
    fixtures_root: Path
    decisions_md: Path
    python: str = sys.executable
    run_tests: TestRunner | None = None
    git: GitRunner | None = None
    loaded: dict[str, LoadedRun] = field(default_factory=dict)

    @property
    def code_root(self) -> Path:
        """``<repo>/code``: tests are loaded by dotted name from here."""
        return self.repo_root / "code"


# ---- small helpers ----
def _git(env: LedgerEnv, args: Sequence[str]) -> tuple[int, str]:
    if env.git is not None:
        return env.git(args)
    try:
        p = subprocess.run(["git", "-C", str(env.repo_root), *args], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, type(exc).__name__
    return p.returncode, p.stdout


def subprocess_tests(env: LedgerEnv) -> TestRunner:
    """The default runner: one ``python -B -c RUNNER <ids>`` subprocess in ``code/``."""
    def run(ids: Sequence[str], code_root: Path) -> dict[str, dict[str, Any]]:
        if not ids:
            return {}
        try:
            p = subprocess.run([env.python, "-B", "-c", RUNNER, *ids], cwd=str(code_root), capture_output=True,
                               text=True, timeout=TEST_TIMEOUT_S)
        except (OSError, subprocess.SubprocessError) as exc:
            return {i: {"ok": False, "why": f"runner failed ({type(exc).__name__})"} for i in ids}
        lines = [x for x in p.stdout.splitlines() if x.startswith(RESULT_MARK)]
        if not lines:
            return {i: {"ok": False, "why": f"runner gave no result (exit {p.returncode})"} for i in ids}
        got = json.loads(lines[-1][len(RESULT_MARK):])
        return {i: got.get(i, {"ok": False, "why": "no result for this test"}) for i in ids}
    return run


def _cut(s: str, *, sentence: bool = False) -> str:
    """``s`` stripped and cut at :data:`QUOTE_MAX` (marked); with ``sentence``, at the end of its first
    sentence when that comes first (also marked, so a reader knows more follows in the file)."""
    s = s.strip()
    if sentence:
        m = re.search(r"[.;](?=\s)", s)
        if m and m.end() < len(s) and m.end() <= QUOTE_MAX:
            return s[:m.end()] + " …[cut]"
    return s if len(s) <= QUOTE_MAX else s[:QUOTE_MAX].rstrip() + " …[cut]"


def _heading_level(line: str) -> int:
    m = re.match(r"^(#{1,6})\s", line)
    return len(m.group(1)) if m else 0


def _bad_keys(raw: Mapping[str, Any], allowed: frozenset[str], where: str) -> list[str]:
    extra = sorted(set(raw) - allowed)
    return [f"{where}: unknown key(s) {extra}"] if extra else []


# ---- the failure: path, anchor, quote ----
def resolve_text_path(env: LedgerEnv, rel: Any) -> tuple[Path | None, str | None]:
    """A repo-relative .md/.txt file outside dataset/, cache/ and secrets; or (None, why)."""
    if not isinstance(rel, str) or not rel:
        return None, "path must be a repo-relative string"
    p = Path(rel)
    if p.is_absolute() or any(part in ("..", ".") for part in p.parts) or not p.parts:
        return None, f"path {rel!r} must be repo-relative, without '..'"
    if p.parts[0] in FORBIDDEN_TOP or p.name.startswith(".env"):
        return None, f"path {rel!r} is not a citable file (dataset, cache and secrets are never read here)"
    if p.suffix not in TEXT_SUFFIXES:
        return None, f"path {rel!r} must be a .md or .txt file"
    full = env.repo_root / p
    if not full.is_file():
        return None, f"path {rel!r} does not exist"
    return full, None


def locate(text: str, kind: str, anchor: str, line_loc: str | None) -> tuple[dict[str, Any] | None, str | None]:
    """The anchored line, the section it opens and the quote; or (None, why)."""
    lines = text.splitlines()
    if kind == "review":
        if TIMESTAMP_RE.fullmatch(anchor) is None:
            return None, f"review anchor {anchor!r} must be an ISO timestamp (the developer's log.txt turn)"
        hits = [i for i, x in enumerate(lines) if x.startswith(f"## [{anchor}]")]
    else:
        hits = [i for i, x in enumerate(lines) if anchor in x]
    if len(hits) != 1:
        return None, f"anchor {anchor!r} matches {len(hits)} lines (exactly 1 needed)"
    i = hits[0]
    head = lines[i]
    level = _heading_level(head)
    end = len(lines)
    for j in range(i + 1, len(lines)):
        lv = _heading_level(lines[j])
        if (kind == "review" and lines[j].startswith("## [")) or (
                kind != "review" and lv and (level == 0 or lv <= level)):
            end = j
            break
    head_text = head.lstrip("#").strip() if level else head.strip()
    if line_loc is not None:
        found = [j for j in range(i + 1, end) if line_loc in lines[j]]
        if len(found) != 1:
            return None, f"line locator {line_loc!r} matches {len(found)} lines in the anchored section (exactly 1)"
        j = found[0]
        sub = lines[j][lines[j].index(line_loc):]
        return {"anchor_line": i + 1, "quote_line": j + 1, "quote": [_cut(head_text), _cut(sub, sentence=True)]}, None
    if level:
        for j in range(i + 1, end):
            s = lines[j].strip()
            if s and not LABEL_LINE_RE.match(s):
                return {"anchor_line": i + 1, "quote_line": j + 1, "quote": [_cut(head_text), _cut(s)]}, None
        return {"anchor_line": i + 1, "quote_line": None, "quote": [_cut(head_text)]}, None
    return {"anchor_line": i + 1, "quote_line": i + 1, "quote": [_cut(head_text)]}, None


def check_failure(raw: Any, env: LedgerEnv) -> tuple[dict[str, Any], list[str]]:
    """The failure part: kind, path, anchor (and locator), case; with its quote."""
    if not isinstance(raw, Mapping):
        return {}, ["failure must be an object"]
    reasons = _bad_keys(raw, FAILURE_KEYS, "failure")
    kind, rel, anchor, loc, case = (raw.get(k) for k in ("kind", "path", "anchor", "line", "case"))
    out: dict[str, Any] = {"kind": kind, "path": rel, "anchor": anchor, "line": loc, "case": case}
    if kind not in KINDS:
        reasons.append(f"failure kind {kind!r} must be one of {list(KINDS)}")
    if kind in CASE_KINDS:
        if not isinstance(case, str) or CASE_RE.fullmatch(case) is None:
            reasons.append(f"a {kind} failure needs 'case' shaped case_<digits>")
    elif case is not None:
        reasons.append(f"'case' is only for {sorted(CASE_KINDS)} failures")
    if kind == "review" and rel != LOG_FILE:
        reasons.append(f"a review failure is anchored in {LOG_FILE}")
    if not isinstance(anchor, str) or not anchor.strip():
        reasons.append("failure anchor must be a non-empty string")
    if loc is not None and (not isinstance(loc, str) or not loc.strip()):
        reasons.append("failure line locator must be a non-empty string when given")
    full, why = resolve_text_path(env, rel)
    if why:
        reasons.append(why)
    if reasons or full is None:
        return out, reasons
    assert isinstance(anchor, str) and isinstance(kind, str)
    text = full.read_text(encoding="utf-8")
    where, why = locate(text, kind, anchor, loc)
    if why:
        return out, [why]
    assert where is not None
    out.update(where)
    if kind in CASE_KINDS:
        assert isinstance(case, str)
        if re.search(rf"\b{re.escape(case)}\b", text) is None:
            reasons.append(f"{case} is not named in {rel}")
        if kind == "custom_eval":
            found = {(c.folder, c.case_id) for c in custom_cases.discover(env.fixtures_root)}
            try:
                folder = str(full.parent.resolve().relative_to(env.fixtures_root.resolve()))
            except ValueError:
                folder = None
            if folder is None or (folder, case) not in found:
                reasons.append(f"{case} in {rel} is not a marked custom eval case")
    return out, reasons


# ---- the fix: ruling and commit ----
def ruling_quote(decisions_md: Path, ruling: str, clause: str | None = None) -> tuple[str | None, str | None]:
    """(quote, why not) from the ``| <ruling> |`` row of the decisions table: from ``clause`` onwards
    when given (it must occur once in the row), else the row's first bold span."""
    try:
        text = decisions_md.read_text(encoding="utf-8")
    except OSError:
        return None, "notes/DECISIONS.md unreadable"
    for line in text.splitlines():
        if line.startswith(f"| {ruling} |"):
            cell = line.split(" | ")[1] if " | " in line else ""
            if clause is not None:
                if cell.count(clause) != 1:
                    return None, f"clause {clause!r} occurs {cell.count(clause)} times in ruling {ruling} (exactly 1)"
                return _cut(cell[cell.index(clause):].replace("**", ""), sentence=True), None
            m = re.search(r"\*\*(.+?)\*\*", cell)
            return _cut(m.group(1) if m else cell), None
    return None, f"ruling {ruling} has no row in notes/DECISIONS.md"


def check_fix(raw: Any, env: LedgerEnv) -> tuple[dict[str, Any], list[str], bool]:
    """The fix part; returns (data, refusal reasons, pending)."""
    if not isinstance(raw, Mapping):
        return {}, ["fix must be an object"], False
    reasons = _bad_keys(raw, FIX_KEYS, "fix")
    ruling, commit, clause = raw.get("ruling"), raw.get("commit"), raw.get("clause")
    out: dict[str, Any] = {"ruling": ruling, "commit": commit, "clause": clause}
    if clause is not None and (not isinstance(clause, str) or not clause.strip()):
        reasons.append("fix clause must be a non-empty string when given")
    elif not isinstance(ruling, str) or RULING_RE.fullmatch(ruling) is None:
        reasons.append("fix ruling must be a T-number such as T90")
    else:
        q, why = ruling_quote(env.decisions_md, ruling, clause)
        if why:
            reasons.append(why)
        out["ruling_quote"] = q
    if commit == PENDING:
        return out, reasons, True
    if not isinstance(commit, str) or COMMIT_RE.fullmatch(commit) is None:
        reasons.append(f"fix commit {commit!r} must be a hex commit ID or {PENDING!r}")
        return out, reasons, False
    rc, _ = _git(env, ["cat-file", "-e", f"{commit}^{{commit}}"])
    if rc != 0:
        reasons.append(f"commit {commit} is not in history (git cat-file -e)")
        return out, reasons, False
    rc, info = _git(env, ["log", "-1", "--format=%H%x00%s", commit])
    if rc == 0 and "\x00" in info:
        sha, subject = info.strip().split("\x00", 1)
        out.update({"commit_sha": sha, "commit_subject": _cut(subject)})
    return out, reasons, False


# ---- the evidence: a test or a metric ----
def resolve_test(env: LedgerEnv, ref: Any) -> tuple[dict[str, Any] | None, str | None]:
    """``<path>::<name>`` to a loadable unittest ID, found in the file's syntax tree."""
    m = TEST_REF_RE.fullmatch(ref) if isinstance(ref, str) else None
    if m is None:
        return None, f"test {ref!r} must be 'code/<path>.py::<Class.test_name | test_name | Class>'"
    path = env.repo_root / m.group("path")
    if not path.is_file():
        return None, f"test file {m.group('path')} does not exist"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    classes = {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}
    funcs = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}

    def methods(c: ast.ClassDef) -> set[str]:
        return {n.name for n in c.body if isinstance(n, ast.FunctionDef)}

    name = m.group("name")
    module = ".".join(Path(m.group("path")).relative_to("code").with_suffix("").parts)
    if "." in name:
        cls, meth = name.split(".")
        if cls not in classes or meth not in methods(classes[cls]) or not meth.startswith("test"):
            return None, f"test {name} not found in {m.group('path')}"
        target = f"{cls}.{meth}"
    elif name in classes:
        target = name
    elif name.startswith("test"):
        owners = [c for c, node in classes.items() if name in methods(node)]
        if name in funcs:
            owners.append("")
        if len(owners) != 1:
            return None, f"test {name} is defined {len(owners)} times in {m.group('path')} (name it Class.{name})"
        target = f"{owners[0]}.{name}" if owners[0] else name
    else:
        return None, f"test {name} not found in {m.group('path')}"
    rc, dirty = _git(env, ["status", "--porcelain", "--", m.group("path")])
    return {"ref": ref, "path": m.group("path"), "unittest_id": f"{module}.{target}",
            "file_sha256": runs.sha256_file(path), "file_differs_from_head": bool(dirty.strip()) if rc == 0 else None,
            }, None


def _run(env: LedgerEnv, rid: Any) -> tuple[LoadedRun | None, str | None]:
    try:
        rid = runs.check_run_id(rid)
    except ValueError as exc:
        return None, str(exc)
    if not (env.runs_root / rid).is_dir():
        return None, f"run {rid} has no folder under runs/"
    lr = env.loaded.get(rid) or load_run(env.runs_root, rid)
    env.loaded[rid] = lr
    if lr.producer_check["status"] != "ok":
        return None, f"run {rid} is unchecked: producer check {lr.producer_check['status']}"
    return lr, None


def metric_value(m: Metric, scope: str, run: LoadedRun, gold: Mapping[str, GoldCase] | None,
                 env: LedgerEnv) -> dict[str, Any]:
    """One metric on one checked run: ``{"value": float, "shown": str}``."""
    if m.name == "fail_closed_rows":
        if run.view.record_errors:
            raise ValueError(f"{len(run.view.record_errors)} record error(s) in cases.jsonl")
        n = sum(1 for c in run.view.cases.values() if is_failed_closed(c))
        return {"value": float(n), "shown": f"{n} of {len(run.view.cases)} rows"}
    if m.name == "custom_passed":
        folder = scope.split(":", 1)[1]
        cases = [c for c in custom_cases.discover(env.fixtures_root) if c.folder == folder]
        res = custom_cases.score_custom(cases, {folder: run.run_id}, {run.run_id: run})
        return {"value": float(res["passed"]), "shown": f"{res['passed']} of {res['marked']} passed"}
    assert gold is not None and run.output is not None
    p = score_predictions(run.output.rows, gold)["aggregate"]["published"]
    if m.name == "step_f1":
        f1 = p["step"]["f1"]
        return {"value": f1, "shown": "n/a" if f1 is None else f"{f1:.4f}"}
    x: Any = p
    for k in DEV_RATES[m.name]:
        x = x[k]
    return {"value": x["rate"], "shown": f"{x['n']}/{x['of']}"}


def check_metric(raw: Any, env: LedgerEnv) -> tuple[dict[str, Any], list[str]]:
    """The metric evidence: before and after on two checked runs, and which way it moved."""
    if not isinstance(raw, Mapping):
        return {}, ["evidence metric must be an object"]
    reasons = _bad_keys(raw, METRIC_KEYS, "metric")
    name, scope = raw.get("name"), raw.get("scope")
    out: dict[str, Any] = {k: raw.get(k) for k in ("name", "scope", "before_run", "after_run")}
    m = METRICS.get(name) if isinstance(name, str) else None
    if m is None:
        return out, [*reasons, f"unknown metric name {name!r}; known: {sorted(METRICS)}"]
    base = scope.split(":", 1)[0] if isinstance(scope, str) else None
    if base not in m.scopes or (base == "custom") != (isinstance(scope, str) and ":" in scope):
        reasons.append(f"metric {name} has no scope {scope!r}; scopes: {list(m.scopes)} (custom as custom:<folder>)")
    if base == "custom" and isinstance(scope, str):
        folders = {c.folder for c in custom_cases.discover(env.fixtures_root)}
        if scope.split(":", 1)[1] not in folders:
            reasons.append(f"{scope}: no marked custom eval case lives in that folder")
    if raw.get("before_run") == raw.get("after_run"):
        reasons.append("before_run and after_run must be two different runs")
    before, why_b = _run(env, raw.get("before_run"))
    after, why_a = _run(env, raw.get("after_run"))
    reasons += [w for w in (why_b, why_a) if w]
    if reasons or before is None or after is None:
        return out, reasons
    assert isinstance(scope, str)
    gold = load_gold(env.gold_path) if base == "dev" else None  # DEV only: the loader's defaults
    try:
        vb, va = (metric_value(m, scope, r, gold, env) for r in (before, after))
    except ValueError as exc:
        return out, [f"metric {name} not computed: {exc}"]
    delta = None if vb["value"] is None or va["value"] is None else va["value"] - vb["value"]
    if delta is None:
        moved = "not computed"
    elif abs(delta) < 1e-12:
        moved = "unchanged"
    elif m.direction is None:
        moved = "changed"
    else:
        moved = "improved" if (delta > 0) == (m.direction == "higher") else "worse"
    out.update({"measured": m.measured, "direction": m.direction, "before": vb, "after": va, "delta": delta,
                "moved": moved, "before_sha256": before.producer_check["pred_sha256"],
                "after_sha256": after.producer_check["pred_sha256"]})
    return out, []


# ---- the ledger ----
def check_ledger(path: Path, env: LedgerEnv) -> dict[str, Any]:
    """Read and check every ledger entry (module docstring); never raises on a bad entry."""
    rel = str(path.relative_to(env.repo_root)) if path.is_relative_to(env.repo_root) else str(path)
    data: dict[str, Any] = {"source": rel, "sha256": None, "entries": [], "problems": [],
                            "tests_checked_by": "each test run by name at build time in code/ "
                                                f"(`{Path(env.python).name} -B -c <runner> <unittest id>`, "
                                                "evaluation/improvements.py RUNNER)",
                            "git_head": None}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        data["problems"].append(f"ledger {rel} does not exist")
        return data
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        data["problems"].append(f"ledger {rel} unreadable ({type(exc).__name__})")
        return data
    data["sha256"] = runs.sha256_file(path)
    rc, head = _git(env, ["rev-parse", "HEAD"])
    data["git_head"] = head.strip() if rc == 0 else None
    if not isinstance(raw, Mapping) or not isinstance(raw.get("entries"), list):
        data["problems"].append("the ledger must be an object with an 'entries' list")
        return data
    data["problems"] += _bad_keys(raw, TOP_KEYS, "ledger")
    seen: set[str] = set()
    pending_tests: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for n, e in enumerate(raw["entries"], start=1):
        entry: dict[str, Any] = {"id": None, "status": "refused", "reasons": []}
        data["entries"].append(entry)
        if not isinstance(e, Mapping):
            entry["reasons"].append(f"entry {n} is not an object")
            continue
        entry["reasons"] += _bad_keys(e, ENTRY_KEYS, f"entry {n}")
        eid = e.get("id")
        if not isinstance(eid, str) or ID_RE.fullmatch(eid) is None or eid in seen:
            entry["reasons"].append(f"entry {n}: id must be a short unique name")
        else:
            seen.add(eid)
            entry["id"] = eid
        entry["failure"], r = check_failure(e.get("failure"), env)
        entry["reasons"] += r
        entry["fix"], r, pending = check_fix(e.get("fix"), env)
        entry["reasons"] += r
        ev = e.get("evidence")
        if not isinstance(ev, Mapping) or len(ev) != 1 or next(iter(ev)) not in ("test", "metric"):
            entry["reasons"].append("evidence must be exactly one of {'test': ...} or {'metric': {...}}")
            entry["evidence"] = {}
        elif "test" in ev:
            t, why = resolve_test(env, ev["test"])
            entry["evidence"] = {"test": t or {"ref": ev["test"]}}
            if why:
                entry["reasons"].append(why)
            else:
                assert t is not None
                pending_tests.append((entry, t))
        else:
            entry["evidence"] = {}
            entry["evidence"]["metric"], r = check_metric(ev["metric"], env)
            entry["reasons"] += r
        entry["status"] = "pending" if pending else "ok"
    runner = env.run_tests or subprocess_tests(env)
    results = runner(sorted({t["unittest_id"] for _, t in pending_tests}), env.code_root)
    for entry, t in pending_tests:
        res = results.get(t["unittest_id"], {"ok": False, "why": "not run"})
        t["result"] = res
        if not res.get("ok"):
            entry["reasons"].append(f"test {t['unittest_id']} did not pass: {res}")
    for entry in data["entries"]:
        if entry["reasons"]:
            entry["status"] = "refused"
    return data


def problems(data: Mapping[str, Any]) -> list[str]:
    """Ledger problems, refused entries and PENDING commits, one line each."""
    out = [f"improvements: {p}" for p in data["problems"]]
    for e in data["entries"]:
        if e["status"] == "refused":
            out.append(f"improvements {e['id'] or '?'} refused: " + "; ".join(e["reasons"]))
        elif e["status"] == "pending":
            out.append(f"improvements {e['id']}: fix commit PENDING (not yet committed)")
    return out


# ---- Markdown ----
def _md_cell(s: Any) -> str:
    return str(s).replace("|", "/").replace("\n", " ")


def _evidence_md(e: Mapping[str, Any]) -> str:
    ev = e.get("evidence") or {}
    if "test" in ev:
        t = ev["test"]
        res = t.get("result")
        state = "not run" if res is None else ("**passed**" if res.get("ok") else f"**did not pass** {res}")
        differs = {True: "; this file differs from HEAD", False: "", None: ""}[t.get("file_differs_from_head")]
        return (f"test `{_md_cell(t.get('ref'))}` (`{t.get('unittest_id', '?')}`): {state}, checked by running "
                f"this one test at build time (file sha256 `{str(t.get('file_sha256', '?'))[:12]}`{differs})")
    if "metric" in ev:
        m = ev["metric"]
        if "moved" not in m:
            return f"metric `{m.get('name')}` ({m.get('scope')}): not computed"
        return (f"metric `{m['name']}` ({m['scope']}; {m['measured']}): before {m['before']['shown']} on "
                f"`{m['before_run']}`, after {m['after']['shown']} on `{m['after_run']}`: **{m['moved']}**")
    return "none"


def render_section(data: Mapping[str, Any], number: int = 11) -> list[str]:
    """The report section, from :func:`check_ledger`'s dict only."""
    ents = data["entries"]
    n_ok = sum(1 for e in ents if e["status"] == "ok")
    n_pend = sum(1 for e in ents if e["status"] == "pending")
    n_ref = sum(1 for e in ents if e["status"] == "refused")
    L = [f"## {number}. Failures found and improvements made", "",
         f"Generated from the ledger `{data['source']}` (sha256 `{str(data['sha256'])[:16]}`), which holds paths, "
         "anchors, T-numbers, commits, run IDs and test names only. Each failure is quoted from its anchored file "
         "(\"before\" is the failure itself); each fix names its ruling (quoted from `notes/DECISIONS.md`) and its "
         "commit (checked with `git cat-file -e`); each piece of evidence is a test run here or a metric computed "
         f"here from two producer-checked runs. Tests: {data['tests_checked_by']}; git HEAD "
         f"`{str(data['git_head'])[:12]}`.", "",
         f"Entries: {len(ents)}; improvements made (fix committed, evidence checked): {n_ok}; fix not yet "
         f"committed (PENDING): {n_pend}; refused: {n_ref}.", ""]
    L += [f"- **Ledger problem:** {p}" for p in data["problems"]]
    if not ents:
        L += ["The ledger holds no entries.", ""]
        return L
    L += ["| id | failure (kind, file) | fix (ruling, commit) | evidence | status |", "|---|---|---|---|---|"]
    for e in ents:
        f, x = e.get("failure") or {}, e.get("fix") or {}
        ev = e.get("evidence") or {}
        evk = "test" if "test" in ev else "metric" if "metric" in ev else "none"
        commit = x.get("commit")
        commit_s = "PENDING" if commit == PENDING else f"`{str(x.get('commit_sha') or commit)[:7]}`"
        L.append(f"| {e['id'] or '?'} | {f.get('kind')}, `{_md_cell(f.get('path'))}`"
                 f"{(' ' + str(f.get('case'))) if f.get('case') else ''} | {x.get('ruling')}, {commit_s} | {evk} | "
                 f"{e['status']} |")
    L.append("")
    for e in ents:
        f, x = e.get("failure") or {}, e.get("fix") or {}
        L.append(f"### {e['id'] or '?'} ({e['status']})")
        where = f"`{f.get('path')}`" + (f" line {f['quote_line']}" if f.get("quote_line") else "")
        if f.get("quote"):
            L.append(f"- **Failure (before)**, {f.get('kind')}"
                     f"{(' ' + str(f.get('case'))) if f.get('case') else ''}, quoted from {where}: "
                     + " / ".join(f"\"{_md_cell(q)}\"" for q in f["quote"]))
        else:
            L.append(f"- **Failure:** {f.get('kind')} in `{f.get('path')}`: not located")
        rq = f" \"{_md_cell(x['ruling_quote'])}\"" if x.get("ruling_quote") else ""
        if x.get("commit") == PENDING:
            cm = "commit **PENDING**: not counted as an improvement made until main records the commit"
        elif x.get("commit_sha"):
            cm = f"commit `{x['commit_sha'][:12]}` \"{_md_cell(x.get('commit_subject', ''))}\""
        else:
            cm = f"commit `{x.get('commit')}`"
        L.append(f"- **Fix:** {x.get('ruling')}{rq}; {cm}.")
        L.append(f"- **Evidence (after):** {_evidence_md(e)}.")
        L += [f"- **REFUSED:** {_md_cell(r)}" for r in e["reasons"]]
        L.append("")
    return L
