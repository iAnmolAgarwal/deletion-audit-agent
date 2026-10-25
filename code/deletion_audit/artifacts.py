"""Run artifacts under ``runs/<run_id>/``: cases, calls, metrics, usage and the producer record.

Artifacts name IDs, states, flags and counts only: no request text, email, phone or other cell
text (the inputs hold personal data). The producer record follows the contract that
``code/evaluation/evidence_guard.check_producer`` checks: ``output_sha256``, the skip and
failure lists as lists, and a ``png-model-needed`` skip only for a file whose bytes start with
the PNG signature (T72).
"""

from __future__ import annotations

import datetime as dt
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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


def case_summary(r: CaseRecord) -> dict[str, Any]:
    """One ``cases.jsonl`` line: IDs, states, flags and checks; no cell text."""
    return {
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
    """Collects a run's records and writes its artifact files."""

    run_dir: Path
    records: list[CaseRecord] = field(default_factory=list)

    def case(self, record: CaseRecord) -> None:
        """Add one case record."""
        self.records.append(record)

    def finish(self, output_sha256: str, producer: Mapping[str, Any], runtime_s: float) -> dict[str, Any]:
        """Write ``cases.jsonl``, ``calls.jsonl``, ``metrics.json``, ``usage.json`` and ``producer.json``."""
        self.run_dir.mkdir(parents=True, exist_ok=True)
        recs = sorted(self.records, key=lambda r: r.case_id)
        with (self.run_dir / "cases.jsonl").open("w", encoding="utf-8") as fh:
            for r in recs:
                fh.write(json.dumps(case_summary(r), sort_keys=True, separators=(",", ":")) + "\n")
        (self.run_dir / "calls.jsonl").write_text("", encoding="utf-8")  # G5 makes no model call
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
        write_json(
            self.run_dir / "usage.json",
            {"model_calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "model_ids": []},
        )
        write_json(self.run_dir / "producer.json", dict(producer))
        return metrics
