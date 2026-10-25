"""The report spec: which named run feeds which role of the three generated reports.

A spec is a JSON object (``reports.py --spec <file>``)::

    {
      "report_id": "reports-<YYYYMMDDTHHMM>",       # output folder runs/<report_id>/
      "final_run": "<run id>",                     # the test-set output the deliverable uses
      "dev_run": "<run id>",                       # the DEV run whose scores are the headline
      "previous_run": "<run id>",                  # optional: the final run's predecessor (drift, changed rows)
      "dev_history": ["<run id>", ...],            # optional: earlier DEV runs, oldest first; the last is
                                                   #   the DEV run's predecessor in metrics.json
      "arms": {"dev": {ARM: run}, "test": {ARM: run}, "fixtures": {ARM: {FIXTURE: run}}},
      "custom_runs": {"<fixture folder>": "<run id>"},   # folder relative to code/tests/fixtures
      "usage": {"run": "<run id>", "calls_file": "calls.jsonl"},
      "holdout_run": null,                         # optional: must match a completed record
      "coherence": true,                           # run the coherence checks on final and DEV output
      "final": false                               # true only for the shipped runs: reports.py --publish
                                                   #   refuses a spec without it
    }

``arms`` is :class:`agent_report.Spec`'s mapping (``ARM`` is ``A+``, ``A`` or ``tools_off``).
``usage.run`` defaults to ``final_run``. Unknown keys are refused, so a misspelt role never
silently drops out of a report.

**Unchecked runs never feed a report (T60, T81).** :func:`load_checked` refuses every run
whose producer check (``evidence_guard.check_producer`` against the sha256 of its
``output.csv``) is not ``ok``, the usage run included. There is no exception: a usage run with
no ``output.csv`` is refused (T107). The runs that bought the replies are read through their
call logs and the ledger, never through :func:`load_checked`.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import runs
from .agent_report import LoadedRun, ReportRefused, Spec, load_run, run_path

TOP_KEYS: frozenset[str] = frozenset({"report_id", "final_run", "dev_run", "previous_run", "dev_history", "arms",
                                      "custom_runs", "usage", "holdout_run", "coherence", "final"})
USAGE_KEYS: frozenset[str] = frozenset({"run", "calls_file"})
ARM_KEYS: frozenset[str] = frozenset({"dev", "test", "fixtures"})
DEFAULT_CALLS_FILE = "calls.jsonl"


@dataclass(frozen=True)
class UsageSpec:
    """Which run's call log the usage report reads."""

    run: str
    calls_file: str = DEFAULT_CALLS_FILE


@dataclass(frozen=True)
class ReportSpec:
    """Run IDs per role (module docstring)."""

    report_id: str
    final_run: str
    dev_run: str
    previous_run: str | None = None
    dev_history: tuple[str, ...] = ()
    arms: Spec = field(default_factory=Spec)
    custom_runs: Mapping[str, str] = field(default_factory=dict)
    usage: UsageSpec | None = None
    holdout_run: str | None = None
    coherence: bool = True
    final: bool = False

    @property
    def usage_spec(self) -> UsageSpec:
        """The usage role, defaulting to the final run's own ``calls.jsonl``."""
        return self.usage or UsageSpec(self.final_run)

    def scored_runs(self) -> list[str]:
        """Every run that feeds a score, a count or a drift figure (all must be checked)."""
        ids = [self.final_run, self.dev_run, *self.dev_history, *self.custom_runs.values()]
        if self.previous_run:
            ids.append(self.previous_run)
        return list(dict.fromkeys(ids))

    def input_runs(self) -> list[str]:
        """Every run the spec names, in a stable order, without repeats."""
        ids = [*self.scored_runs(), *self.arms.run_ids(), self.usage_spec.run]
        if self.holdout_run:
            ids.append(self.holdout_run)
        return list(dict.fromkeys(ids))


def _str(raw: Mapping[str, Any], key: str, *, required: bool) -> str | None:
    v = raw.get(key)
    if v is None and not required:
        return None
    if not isinstance(v, str):
        raise ValueError(f"spec {key!r} must be a run ID string")
    return runs.check_run_id(v)


def spec_from_mapping(raw: Mapping[str, Any]) -> ReportSpec:
    """Build and check a :class:`ReportSpec`; raises ValueError on any malformed or unknown key."""
    if not isinstance(raw, Mapping):
        raise ValueError("the spec must be a JSON object")
    unknown = sorted(set(raw) - TOP_KEYS)
    if unknown:
        raise ValueError(f"unknown spec key(s) {unknown}; allowed: {sorted(TOP_KEYS)}")
    report_id = _str(raw, "report_id", required=True)
    final_run = _str(raw, "final_run", required=True)
    dev_run = _str(raw, "dev_run", required=True)
    assert report_id and final_run and dev_run
    hist = raw.get("dev_history") or []
    if not isinstance(hist, list) or not all(isinstance(x, str) for x in hist):
        raise ValueError("spec 'dev_history' must be a list of run IDs")
    arms_raw = raw.get("arms") or {}
    if not isinstance(arms_raw, Mapping) or set(arms_raw) - ARM_KEYS:
        raise ValueError(f"spec 'arms' must be an object with keys among {sorted(ARM_KEYS)}")
    arms = Spec(dict(arms_raw.get("dev") or {}), dict(arms_raw.get("test") or {}),
                {k: dict(v) for k, v in (arms_raw.get("fixtures") or {}).items()})
    custom = raw.get("custom_runs") or {}
    if not isinstance(custom, Mapping) or not all(isinstance(k, str) and isinstance(v, str)
                                                  for k, v in custom.items()):
        raise ValueError("spec 'custom_runs' must map fixture folders to run IDs")
    for folder in custom:
        parts = Path(folder).parts
        if not parts or Path(folder).is_absolute() or any(p in ("..", ".") for p in parts):
            raise ValueError(f"custom_runs folder {folder!r} must be a relative path under code/tests/fixtures")
    usage: UsageSpec | None = None
    u = raw.get("usage")
    if u is not None:
        if not isinstance(u, Mapping) or set(u) - USAGE_KEYS:
            raise ValueError(f"spec 'usage' must be an object with keys among {sorted(USAGE_KEYS)}")
        calls_file = u.get("calls_file", DEFAULT_CALLS_FILE)
        if not isinstance(calls_file, str) or "/" in calls_file or not calls_file.endswith(".jsonl"):
            raise ValueError("usage 'calls_file' must be a bare *.jsonl file name inside the run folder")
        usage = UsageSpec(_str(u, "run", required=True) or final_run, calls_file)
    coherence = raw.get("coherence", True)
    if not isinstance(coherence, bool):
        raise ValueError("spec 'coherence' must be true or false")
    final = raw.get("final", False)
    if not isinstance(final, bool):
        raise ValueError("spec 'final' must be true or false")
    spec = ReportSpec(report_id=report_id, final_run=final_run, dev_run=dev_run,
                      previous_run=_str(raw, "previous_run", required=False),
                      dev_history=tuple(runs.check_run_id(x) for x in hist), arms=arms,
                      custom_runs={k: runs.check_run_id(v) for k, v in custom.items()}, usage=usage,
                      holdout_run=_str(raw, "holdout_run", required=False), coherence=coherence, final=final)
    for rid in spec.arms.run_ids():
        runs.check_run_id(rid)
    if spec.report_id in spec.input_runs():
        raise ValueError(f"report_id {spec.report_id!r} names an input run; give the reports their own ID")
    return spec


def load_spec(path: Path) -> ReportSpec:
    """Read a spec file (module docstring)."""
    return spec_from_mapping(json.loads(path.read_text(encoding="utf-8")))


def load_checked(spec: ReportSpec, runs_root: Path) -> dict[str, LoadedRun]:
    """Load every scored run and the usage run; raise :class:`ReportRefused` naming each unchecked one.

    The holdout run is not loaded here: it is read only through its completed record.
    Arm runs are loaded and checked by ``agent_report.build_report`` itself.
    """
    loaded: dict[str, LoadedRun] = {}
    reasons: list[str] = []
    for rid in spec.scored_runs():
        lr = load_run(runs_root, rid)
        loaded[rid] = lr
        if lr.producer_check["status"] != "ok":
            reasons.append(f"{rid}: producer check {lr.producer_check['status']}: "
                           + "; ".join(lr.producer_check["reasons"]))
    u = spec.usage_spec
    if u.run not in loaded:
        d = run_path(runs_root, u.run)
        if not d.is_dir():
            reasons.append(f"{u.run}: usage run folder does not exist")
        else:
            lr = load_run(runs_root, u.run)
            if lr.producer_check["status"] != "ok":
                reasons.append(f"{u.run}: producer check {lr.producer_check['status']}: "
                               + "; ".join(lr.producer_check["reasons"]))
    if reasons:
        raise ReportRefused(reasons)
    return loaded
