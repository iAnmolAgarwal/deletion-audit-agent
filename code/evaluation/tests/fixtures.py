"""Hand-built steps and rows for the scorer and coherence tests."""
from __future__ import annotations

import json
from typing import Any

from evaluation.contract import OPERATIONS
from evaluation.gold import GoldCase
from evaluation.outputs import OutputRow, parse_steps


def st(n: int, op: str, system: str, resource: str, ev: str = "") -> dict[str, Any]:
    """A step with the tabled phase and state for ``op``."""
    phase, state = OPERATIONS[op]
    return {"step_no": n, "phase": phase, "system_id": system, "resource_id": resource,
            "operation": op, "state": state, "evidence_id": ev}


def renumber(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [dict(s, step_no=i) for i, s in enumerate(steps, start=1)]


def row(case_id: str, status: str, steps: Any, raw: str | None = None) -> OutputRow:
    """An OutputRow built the way read_output builds one (serialize, then parse)."""
    raw = raw if raw is not None else json.dumps(steps, separators=(",", ":"))
    parsed, err = parse_steps(raw)
    return OutputRow(case_id, status, parsed, raw, err)


def gold(case_id: str, status: str, steps: list[dict[str, Any]]) -> GoldCase:
    return GoldCase(case_id, status, steps)


def incomplete_example(ev: str = "evidence_01") -> list[dict[str, Any]]:
    """A coherent INCOMPLETE answer: one remaining account, an audit record retained."""
    return [
        st(1, "REPORT_REMAINING_RECORD", "account_service", "account_1", ev),
        st(2, "DELETE_RECORD", "account_service", "account_1"),
        st(3, "VERIFY_RECORD_ABSENT", "account_service", "account_1"),
        st(4, "VERIFY_RECORD_PRESENT", "security_service", "audit_record_1"),
    ]


def complete_example(ev: str = "evidence_03") -> list[dict[str, Any]]:
    return [
        st(1, "VERIFY_RECORD_ABSENT", "account_service", "account_2", ev),
        st(2, "VERIFY_RECORD_ABSENT", "search_service", "search_2", ev),
    ]
