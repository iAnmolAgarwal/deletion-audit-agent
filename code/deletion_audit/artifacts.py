"""Run artifacts under ``runs/<run_id>/``: cases, calls, metrics, usage and the producer record.

Artifacts name IDs, states, flags and counts only: no request text, email, phone or other cell
text (the inputs hold personal data). The producer record follows the contract that
``code/evaluation/evidence_guard.check_producer`` checks: ``output_sha256``, the skip and
failure lists as lists, and a ``png-model-needed`` skip only for a file whose bytes start with
the PNG signature (T72).

G7 wiring additions:

* ``cases.jsonl`` carries the agent's per-case report under ``"agent"`` (G7a's field names, read by
  ``evaluation/agent_report.py``), plus ``instruction_like_text`` at the top level (T95 item 1:
  the code check, the model's flag and their merge), the intent label, and the open questions,
  validated answers and rejections the record holds.
* ``calls.jsonl`` is written by GM's :class:`~deletion_audit.model.JsonlCallLog` as the calls
  happen (:meth:`RunArtifacts.record`); :meth:`RunArtifacts.finish` never truncates it.
* ``usage.json`` is derived from the run's call entries (:func:`usage_from_calls`): what this run
  sent and paid for, and the replies it used with the tokens and cost originally spent on them and
  the runs that bought them (``../CLAUDE.md`` section 5, ``usage_report.md`` (a) and (b)).
"""

from __future__ import annotations

import datetime as dt
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .model import CallLog, CallLogEntry, JsonlCallLog, ReplyCache, usage_cost
from .record import CaseRecord

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
VALIDATOR_PARTS: Mapping[str, str] = {
    "HARD_CONTAINS": "hard",
    "ABSENT_BRANCH": "absent_branches",
    "OTHER_ABSENCE": "flagged",
    "T77_INCOMPLETE_VERIFICATION_EMPTY": "row_rules",
    "T77_COMPLETE_VERIFICATION_CITES": "row_rules",
    "T77_FINDING_CITES": "row_rules",
    "REMEDIATION_EMPTY": "row_rules",
    "COMPLETE_VERIFICATION_ONLY": "row_rules",
}


def now_ist() -> str:
    """Current time, ISO-8601 IST (artifact metadata only; never part of ``output.csv``)."""
    return dt.datetime.now(IST).isoformat(timespec="seconds")


def write_json(path: Path, obj: Any) -> None:
    """Canonical JSON (sorted keys) with a trailing newline."""
    path.write_text(json.dumps(obj, indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8")


def case_summary(r: CaseRecord, agent: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """One ``cases.jsonl`` line: IDs, states, flags and checks; no cell text. ``agent`` is the
    agent's per-case report (module docstring); without one the line has no agent fields."""
    line = {
        "case_id": r.case_id,
        "status": r.status,
        "row_state": r.row_state,
        "failed_closed": r.failed_closed,
        "identity": r.identity.status,
        "intent_source": r.intent.source,
        "account": None
        if r.account is None
        else {"resource_id": r.account.resource_id, "stage": r.account.stage, "candidates": list(r.account.candidates)},
        "citation": {"file_id": r.citation.file_id, "rule": r.citation.rule},
        "resources": [
            {
                "system_id": x.key.system_id,
                "resource_id": x.key.resource_id,
                "link": x.link_basis,
                "state": x.state.value,
                "state_basis": x.state.basis,
                "time_basis": x.state.time_basis,
                "category": x.category.category,
                "category_basis": x.category.basis,
                "outcome": x.decision.outcome,
                "rule_id": x.decision.rule_id,
                "depends_on": sorted(x.state.depends_on),
            }
            for x in r.resources
        ],
        "failed_dependencies": sorted(r.failed_dependencies),
        "flags": [{"code": f.code, "detail": f.detail} for f in r.flags],
        "checks_failed": [{"rule": c.rule, "severity": c.severity, "step_no": c.step_no} for c in r.checks if not c.ok],
        "n_steps": len(r.steps),
    }
    if agent is not None:
        line.update({
            "agent": dict(agent),
            "intent_label": r.intent.label,
            "instruction_like_text": agent.get("instruction_like_text"),
            "open_questions": list(r.open_questions),
            "answers": list(r.answers),
            "rejected": list(r.rejected),
        })
    return line


def _reply(key: str, roots: Sequence[Path]) -> Any:
    """The cached reply for ``key`` from the first of ``roots`` that holds it, or None."""
    for root in roots:
        hit = ReplyCache(root).get(key)
        if hit is not None:
            return hit
    return None


def usage_from_calls(calls: Sequence[CallLogEntry], roots: Sequence[Path],
                     namespaces: Sequence[int | None] | None = None) -> dict[str, Any]:
    """``usage.json`` from a run's call entries (module docstring).

    * ``model_calls``, ``input_tokens``, ``output_tokens``, ``cost_usd``: this run's send attempts
      and what they were billed (each send's settled cost as logged; a failed send logs $0).
    * ``model_ids``: the model of every reply the run used (a cache hit or a successful send),
      read from the reply cache entry.
    * ``replies_used``: those replies with the tokens and cost originally spent on them (priced
      from the stored ``usage``) and the runs that bought them. ``namespaces[i]`` is the index in
      ``roots`` of the reply cache ``calls[i]`` was made through, so the same request read in two
      namespaces counts as two replies; without it every root is searched for each key once.
    """
    sends = [c for c in calls if c.event == "send"]
    ns = list(namespaces) if namespaces is not None else [None] * len(calls)
    if len(ns) != len(calls):
        raise ValueError("namespaces must name one cache root per call entry")
    used = sorted({(c.key, -1 if n is None else n) for c, n in zip(calls, ns, strict=True)
                   if c.outcome == "ok" and c.event in ("cache_hit", "send")})
    found = (_reply(k, roots if n < 0 else roots[n:n + 1]) for k, n in used)
    replies = [r for r in found if r is not None]
    bought_by = Counter(r.bought_by_run for r in replies)
    return {
        "model_calls": len(sends),
        "input_tokens": sum(int(c.usage.get("input_tokens", 0)) for c in sends),
        "output_tokens": sum(int(c.usage.get("output_tokens", 0)) for c in sends),
        "cost_usd": round(sum(c.cost_usd for c in calls), 6),
        "model_ids": sorted({r.model for r in replies}),
        "replies_bought": sum(1 for c in sends if c.outcome == "ok"),
        "cache_hits": sum(1 for c in calls if c.event == "cache_hit"),
        "replay_misses": sum(1 for c in calls if c.event == "replay_miss"),
        "give_ups": sum(1 for c in calls if c.outcome == "give_up"),
        "replies_used": {
            "count": len(replies),
            "missing_from_cache": len(used) - len(replies),
            "input_tokens": sum(int(r.usage.get("input_tokens", 0)) for r in replies),
            "output_tokens": sum(int(r.usage.get("output_tokens", 0)) for r in replies),
            "cost_usd": round(sum(usage_cost(r.model, r.usage) for r in replies), 6),
            "bought_by_runs": dict(sorted(bought_by.items())),
        },
        "measured": "calls.jsonl entries of this run; replies_used priced from each reply cache entry's usage",
    }


def validator_counts(records: Sequence[CaseRecord]) -> dict[str, Any]:
    """Validator counts by part: hard containment, ABSENT branches, flagged absence, row rules."""
    parts: dict[str, Counter[str]] = {
        p: Counter() for p in ("hard", "absent_branches", "flagged", "row_rules", "other")
    }
    failing: dict[str, list[str]] = {}
    for r in records:
        for c in r.checks:
            part = VALIDATOR_PARTS.get(c.rule, "other")
            parts[part]["checked"] += 1
            parts[part]["pass" if c.ok else "fail"] += 1
            if not c.ok:
                failing.setdefault(f"{part}:{c.rule}", []).append(r.case_id)
    return {
        "by_part": {k: dict(sorted(v.items())) for k, v in parts.items()},
        "failing_cases": {k: sorted(set(v)) for k, v in sorted(failing.items())},
    }


@dataclass
class RunArtifacts:
    """Collects a run's records and call entries and writes its artifact files.

    It is also the run's :class:`~deletion_audit.model.CallLog` (G3 section 5 ``RunArtifacts.call``):
    every entry is appended to ``calls.jsonl`` through GM's ``JsonlCallLog`` at once, kept for
    ``usage.json``, and passed on to ``extra_log`` when one is given.
    """

    run_dir: Path
    records: list[CaseRecord] = field(default_factory=list)
    agents: dict[str, dict[str, Any]] = field(default_factory=dict)
    calls: list[CallLogEntry] = field(default_factory=list)
    extra_log: CallLog | None = None
    call_namespaces: list[int | None] = field(default_factory=list)

    def case(self, record: CaseRecord, agent: Mapping[str, Any] | None = None) -> None:
        """Add one case record and, when the agent ran, its per-case report."""
        self.records.append(record)
        if agent is not None:
            self.agents[record.case_id] = dict(agent)

    def start_calls(self) -> None:
        """Begin a fresh ``calls.jsonl`` (a re-used run ID never mixes two runs' calls)."""
        self.run_dir.mkdir(parents=True, exist_ok=True)
        (self.run_dir / "calls.jsonl").write_text("", encoding="utf-8")
        self.calls.clear()
        self.call_namespaces.clear()

    def call(self, entry: CallLogEntry, namespace: int | None = None) -> None:
        """Log one model-call entry (``calls.jsonl``, memory, ``extra_log``); ``namespace`` is the index of
        the reply cache the call went through, when the caller knows it (see :func:`usage_from_calls`)."""
        self.calls.append(entry)
        self.call_namespaces.append(namespace)
        JsonlCallLog(self.run_dir / "calls.jsonl").record(entry)
        if self.extra_log is not None:
            self.extra_log.record(entry)

    def record(self, entry: CallLogEntry) -> None:
        """The :class:`~deletion_audit.model.CallLog` protocol: the same as :meth:`call`."""
        self.call(entry)

    def namespace_log(self, namespace: int) -> CallLog:
        """A :class:`~deletion_audit.model.CallLog` for one reply namespace's client."""
        return _NamespaceLog(self, namespace)

    def usage(self, roots: Sequence[Path]) -> dict[str, Any]:
        """``usage.json`` for the calls logged so far (:func:`usage_from_calls`)."""
        return usage_from_calls(self.calls, roots, self.call_namespaces)

    def finish(self, output_sha256: str, producer: Mapping[str, Any], runtime_s: float,
               usage: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Write ``cases.jsonl``, ``metrics.json``, ``usage.json`` and ``producer.json``; create an empty
        ``calls.jsonl`` when no call was logged (never truncate one)."""
        self.run_dir.mkdir(parents=True, exist_ok=True)
        recs = sorted(self.records, key=lambda r: r.case_id)
        with (self.run_dir / "cases.jsonl").open("w", encoding="utf-8") as fh:
            for r in recs:
                line = case_summary(r, self.agents.get(r.case_id))
                fh.write(json.dumps(line, sort_keys=True, separators=(",", ":")) + "\n")
        calls_path = self.run_dir / "calls.jsonl"
        if not calls_path.exists():
            calls_path.write_text("", encoding="utf-8")
        failed = Counter(r.failed_closed for r in recs if r.failed_closed)
        metrics = {
            "cases": len(recs),
            "status": dict(sorted(Counter(r.status for r in recs).items())),
            "failed_closed": {
                "count": sum(failed.values()),
                "by_reason": dict(sorted(failed.items())),
                "cases": sorted(r.case_id for r in recs if r.failed_closed),
            },
            "account_stages": dict(sorted(Counter(r.account.stage for r in recs if r.account).items())),
            "flags": dict(sorted(Counter(f.code for r in recs for f in r.flags).items())),
            "validator": validator_counts(recs),
            "runtime_s": round(runtime_s, 3),
            "output_sha256": output_sha256,
        }
        write_json(self.run_dir / "metrics.json", metrics)
        write_json(self.run_dir / "usage.json", dict(usage) if usage is not None else usage_from_calls(self.calls, ()))
        write_json(self.run_dir / "producer.json", dict(producer))
        return metrics


@dataclass(frozen=True)
class _NamespaceLog:
    """Passes a client's entries to the run's artifacts with the client's namespace."""

    arts: RunArtifacts
    namespace: int

    def record(self, entry: CallLogEntry) -> None:
        """Log ``entry`` under this namespace."""
        self.arts.call(entry, self.namespace)
