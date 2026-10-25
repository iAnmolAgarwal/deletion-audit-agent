"""Shared builders for the G7 wiring tests: model setups on GM's FakeTransport, cache seeding, approvals.

Every value is made up (the agent tests' synthetic datasets). No test here makes a network call,
reads ``.env``, reads the repo's reply cache or run directories, or opens a gold file: every cache
and run directory is a temporary one.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from deletion_audit.agent.intent import run_turn1
from deletion_audit.agent.tools import tool_definitions
from deletion_audit.model import BudgetGuard, FakeTransport, MemoryCallLog, ModelClient, ReplyCache, RetryPolicy
from deletion_audit.pipeline import ModelSetup, namespace_roots

from ..agent._support import ADA, tmpdir


def paid_setup(cache_dir: Path, script: Sequence[Any], *, dollar_cap: float = 5.0, call_cap: int = 200) -> ModelSetup:
    """A paid setup on a FakeTransport playing ``script``; retries do not sleep."""
    return ModelSetup(FakeTransport(list(script)), BudgetGuard(dollar_cap, call_cap, cache_dir / "ledger.jsonl"),
                      namespace_roots(cache_dir), paid=True, policy=RetryPolicy(sleep=lambda _s: None))


def sent(setup: ModelSetup) -> list[dict[str, Any]]:
    """Every body the setup's FakeTransport was sent."""
    transport = setup.transport
    assert isinstance(transport, FakeTransport)
    return [json.loads(json.dumps(b, default=dict)) for b in transport.sent]


def seed_turn1(cache_dir: Path, text: str, replies: Sequence[dict[str, Any]]) -> None:
    """Cache one turn-1 reply for ``text`` in each namespace, in order (``replies[k]`` -> namespace k)."""
    for root, reply in zip(namespace_roots(cache_dir), replies, strict=True):
        budget = BudgetGuard(1.0, 5, cache_dir / "seed-ledger.jsonl")
        client = ModelClient(FakeTransport([reply]), ReplyCache(root), budget, RetryPolicy(sleep=lambda _s: None),
                             MemoryCallLog(), replay_only=False, run_id="seed")
        try:
            run_turn1(text, tool_definitions(), client)
        finally:
            client.close()


def approve(output: Path, *, plant: tuple[str, str] | None = None) -> Path:
    """An approved-output record (T101) for ``output`` (absolute path). ``plant`` = (case_id, status)
    rewrites that row's status in a copy first, so the baseline differs from the run with no cause."""
    target = output
    if plant is not None:
        lines = output.read_text(encoding="utf-8").splitlines(keepends=True)
        cid, status = plant
        out = []
        for line in lines:
            if line.startswith(cid + ","):
                rest = line.split(",", 2)
                line = ",".join([rest[0], status, rest[2]])
            out.append(line)
        target = output.with_name("planted_output.csv")
        target.write_text("".join(out), encoding="utf-8")
    record = tmpdir() / "approved_output.json"
    sha = hashlib.sha256(target.read_bytes()).hexdigest()
    record.write_text(json.dumps({"approved_output": {"run_id": "synthetic", "path": str(target), "sha256": sha}}),
                      encoding="utf-8")
    return record


def reading(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """A vision reading value."""
    return {"records": list(records), "unreadable": [], "instruction_like_text": False}


def shown(shown_id: str, **state: str) -> dict[str, Any]:
    """One record of a reading: Ada as the subject, the given state fields, the rest ``not_shown``."""
    base = {"shown_id": shown_id, "subject_emails": [ADA], "subject_phones": [], "subject_names": [],
            "subject_user_ids": [], "sync_enabled": "not_shown", "restore_allowed": "not_shown",
            "marked_deleted": "not_shown", "download_available": "not_shown", "visible_markers": [], "status_label": ""}
    base.update(state)
    return base


def cases_jsonl(run_dir: Path) -> dict[str, dict[str, Any]]:
    """``cases.jsonl`` by case ID."""
    lines = (run_dir / "cases.jsonl").read_text(encoding="utf-8").splitlines()
    return {d["case_id"]: d for d in (json.loads(x) for x in lines if x.strip())}


def read_json(path: Path) -> Any:
    """A JSON file."""
    return json.loads(path.read_text(encoding="utf-8"))
