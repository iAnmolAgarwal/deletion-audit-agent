"""Shared builders for the G7 wiring tests: model setups on GM's FakeTransport, cache seeding, a planted model-free row.

Every value is made up (the agent tests' synthetic datasets). No test here makes a network call,
reads ``.env``, reads the repo's reply cache or run directories, or opens a gold file: every cache
and run directory is a temporary one.
"""

from __future__ import annotations

import contextlib
import dataclasses
import json
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any
from unittest import mock

from deletion_audit.agent.intent import run_turn1
from deletion_audit.agent.tools import tool_definitions
from deletion_audit.model import BudgetGuard, FakeTransport, MemoryCallLog, ModelClient, ReplyCache, RetryPolicy
from deletion_audit.pipeline import ModelSetup, namespace_roots

from ..agent._support import ADA


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


@contextlib.contextmanager
def plant_model_free(case_id: str | None = None) -> Iterator[None]:
    """Patch ``pipeline.model_free_records`` so one case's model-free row (default: the first case) loses
    its last step: the run's row then differs from it with no model input to explain it, so the
    model-change check must mark it ``stop``."""
    from deletion_audit import pipeline

    real = pipeline.model_free_records

    def planted(*args: Any, **kw: Any) -> dict[str, Any]:
        out = real(*args, **kw)
        cid = case_id or sorted(out)[0]
        if not out[cid].steps:
            raise AssertionError(f"{cid} has no step to plant a difference on")
        out[cid] = dataclasses.replace(out[cid], steps=out[cid].steps[:-1])
        return out

    with mock.patch.object(pipeline, "model_free_records", planted):
        yield


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
