"""G2 forensics helpers: holdout-locked loaders and account-candidate primitives.

Holdout lock: gold comes only from research/prototype/devgold.py, which drops holdout rows
before steps_json is parsed. Holdout request rows are dropped here too, so no count uses them.
No rule here is keyed on a case ID, file name or row position.
"""
from __future__ import annotations

import csv
import sys as _sys
_sys.dont_write_bytecode = True  # never write __pycache__ into the read-only kit
import datetime as dt
import sys
from collections import defaultdict
from pathlib import Path

PROTO = Path("/Users/anmolagarwal/hackerrank_orchestrate/october26/research/prototype")
sys.path.insert(0, str(PROTO))

import devgold  # noqa: E402  (holdout-locked loader)
from solver import World, STATUS_TO_RESULT, act_template, TEMPLATE_WINDOWS, sig_match  # noqa: E402

DATASET = Path("/Users/anmolagarwal/hackerrank_orchestrate/october26/hackerrank-orchestrate-october26/dataset")
RUNS = Path("/Users/anmolagarwal/hackerrank_orchestrate/october26/hackerrank-orchestrate-october26/runs")


def T(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def load_cases() -> tuple[list[dict], dict[str, dict]]:
    """DEV (holdout dropped) + 518 test request rows, and DEV gold."""
    dev_req = devgold.load_dev_requests()
    _, hold = devgold.load_split()
    with open(DATASET / "deletion_requests.csv", newline="", encoding="utf-8") as f:
        test_req = list(csv.DictReader(f))
    for r in dev_req:
        r["_set"] = "dev"
    for r in test_req:
        r["_set"] = "test"
    cases = dev_req + test_req
    assert not ({c["case_id"] for c in cases} & hold)
    assert len(dev_req) == 22 and len(test_req) == 518
    return cases, devgold.load_dev_gold()


def gold_account(gold_case: dict) -> list[str]:
    return sorted({s["resource_id"] for s in gold_case["steps"] if s["system_id"] == "account_service"})


def off_min(a: dict, rep: dt.datetime) -> float:
    return (a["_t"] - rep).total_seconds() / 60.0


def account_delete_rows(W: World) -> list[dict]:
    return [a for a in W.acts if a["event_type"] == "DELETE_RECORD" and a["target_system"] == "account_service"]


def id_linked_accounts(W: World, uid: str, q: dict, form: str = "window") -> set[str]:
    """Accounts identifier-linked to uid.
    form 'window': unit line time in [requested_at, audit_at] (prototype R3/R4 form).
    form 'pre_audit': any line time <= audit_at.
    form 'any': any time (no audit filter).
    """
    out = set()
    for u in W.units:
        if uid not in u.users or not u.resource_id:
            continue
        if u.system not in ("account_service", "profile_service"):
            continue
        if form == "window" and not (q["requested_at"] <= u.ts <= q["audit_at"]):
            continue
        if form == "pre_audit" and not (u.ts <= q["audit_at"]):
            continue
        out.add(u.resource_id)
    return out
