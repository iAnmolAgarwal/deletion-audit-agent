"""Synthetic ``runs/<id>/`` directories for the agent-report and freeze-check tests.

Everything here is made up: case IDs in the 9xx range, fictional resource IDs, no dataset
file. Files are written with the stdlib only (``csv``, ``json``, ``hashlib``), never with
the evaluation package's own writers, so the tests do not confirm the code with itself.
"""
from __future__ import annotations

import copy
import csv
import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from evaluation.split import DEV_IDS, HOLDOUT_IDS

ABSENT = object()  # pass as ``vision`` to leave the vision artifact out


def step(resource: str, op: str = "VERIFY_RECORD_ABSENT", ev: str = "evidence_01") -> dict[str, Any]:
    return {"step_no": 1, "phase": "VERIFICATION", "system_id": "account_service", "resource_id": resource,
            "operation": op, "state": "ABSENT", "evidence_id": ev}


def agent(**over: Any) -> dict[str, Any]:
    """A valid agent block (deletion request, no tools); ``over`` replaces top-level keys."""
    base: dict[str, Any] = {
        "mode": "A+",
        "intent": {"label": "DELETION_REQUEST", "source": "MODEL", "committed_key": "k", "final_key": "k",
                   "committed_label": "DELETION_REQUEST", "final_label": "DELETION_REQUEST",
                   "agrees": True, "crosscheck": {"intake_non_deletion": False, "activity_ids": []}},
        "turn1_replicates": ["DELETION_REQUEST", "DELETION_REQUEST"],
        "tool_calls": [],
        "audit_case_calls": 1,
        "answers_applied": [],
        "answers_rejected": [],
        "steps_differ_when_applied": False,
        "status": "OK",
        "flags": [],
    }
    base = copy.deepcopy(base)
    base.update(over)
    return base


_SAME = object()


def intent(label: str | None, source: str = "MODEL", *, intake: bool = False, agrees: bool | None = True,
           committed: str | None = "k", final: str | None = "k", committed_label: Any = _SAME,
           final_label: Any = _SAME) -> dict[str, Any]:
    """An intent block; the committed and final labels default to ``label`` (T92 label fields)."""
    return {"label": label, "source": source, "committed_key": committed, "final_key": final, "agrees": agrees,
            "committed_label": label if committed_label is _SAME else committed_label,
            "final_label": label if final_label is _SAME else final_label,
            "crosscheck": {"intake_non_deletion": intake, "activity_ids": ["activity_1"] if intake else []}}


def tool(name: str, *, is_error: bool = False) -> dict[str, Any]:
    return {"name": name, "args_hash": "h" + name, "is_error": is_error, "evidence_ids": []}


def case(case_id: str, ag: Any = None, *, row_state: str = "VALID", failed_closed: str | None = None,
         flags: Sequence[str] = (), intent_source: str = "MODEL") -> dict[str, Any]:
    """One cases.jsonl line. ``ag=ABSENT`` leaves the agent block out."""
    line: dict[str, Any] = {"case_id": case_id, "status": "COMPLETE", "row_state": row_state,
                            "failed_closed": failed_closed, "flags": [{"code": f, "detail": "x"} for f in flags],
                            "intent_source": intent_source, "n_steps": 1}
    if ag is not ABSENT:
        line["agent"] = agent() if ag is None else ag
    return line


def image(file_id: str, r1: Mapping[str, Any], r2: Mapping[str, Any], agree: bool, dis: Sequence[str],
          rids: Sequence[tuple[str, str, bool, bool]] = ()) -> dict[str, Any]:
    return {"file_id": file_id, "readings": [dict(r1), dict(r2)], "agree": agree, "disagreements": list(dis),
            "flags": [], "resource_ids": [{"system_id": s, "resource_id": r, "well_formed": w, "named_elsewhere": n}
                                          for s, r, w, n in rids]}


def write_csv(path: Path, rows: Mapping[str, tuple[str, list[dict[str, Any]]]]) -> str:
    """Write an output file by hand; return its sha256."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["case_id", "deletion_status", "steps_json"])
        for cid, (status, steps) in rows.items():
            w.writerow([cid, status, json.dumps(steps, separators=(",", ":"))])
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_run(root: Path, run_id: str, rows: Mapping[str, tuple[str, list[dict[str, Any]]]],
              cases: Sequence[Mapping[str, Any]], *, vision: Any = (), skips: Sequence[str] = (),
              usage: Mapping[str, Any] | None = None, mode: str = "A+", producer: Any = None,
              bad_hash: bool = False, fc_count: int | None = None) -> Path:
    """A run directory in the G5 artifact layout plus the agent fields under test."""
    d = root / run_id
    sha = write_csv(d / "output.csv", rows)
    with (d / "cases.jsonl").open("w", encoding="utf-8") as f:
        for c in cases:
            f.write(json.dumps(c) + "\n")
    if vision is not ABSENT:
        (d / "vision.json").write_text(json.dumps(list(vision)), encoding="utf-8")
    prod = {"evidence_failures": [], "evidence_skipped": list(skips), "evidence_skip_count": len(skips),
            "output_sha256": "0" * 64 if bad_hash else sha, "mode": mode}
    if producer is not None:
        prod = producer
    if prod is not ABSENT:
        (d / "producer.json").write_text(json.dumps(prod), encoding="utf-8")
    n_fc = sum(1 for c in cases if c.get("row_state") == "FAILED_CLOSED") if fc_count is None else fc_count
    (d / "metrics.json").write_text(json.dumps({"output_sha256": sha, "failed_closed": {"count": n_fc}}),
                                    encoding="utf-8")
    u = usage or {"model_calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "model_ids": []}
    (d / "usage.json").write_text(json.dumps(u), encoding="utf-8")
    return d


def write_gold(path: Path) -> None:
    """A synthetic gold file: every DEV ID gets one step; holdout rows hold invalid JSON (T48)."""
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["case_id", "deletion_status", "steps_json"])
        for cid in sorted(DEV_IDS):
            w.writerow([cid, "COMPLETE", json.dumps([step("account_" + cid[5:])])])
        for cid in sorted(HOLDOUT_IDS):
            w.writerow([cid, "COMPLETE", "{not json: holdout rows are never parsed"])


def dev_rows() -> dict[str, tuple[str, list[dict[str, Any]]]]:
    """Rows equal to :func:`write_gold`'s DEV answers."""
    return {cid: ("COMPLETE", [step("account_" + cid[5:])]) for cid in sorted(DEV_IDS)}
