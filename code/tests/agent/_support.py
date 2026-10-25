"""Shared builders for the agent tests: fake-transport clients, scripted replies, tiny datasets.

Every value here is made up (``example.test`` emails, ``user_9xxx`` IDs, IDs of nine digits). No
test makes a network call: every client wraps GM's :class:`FakeTransport`, and no test reads
``.env``, ``runs/``, a real cache or any gold file.
"""

from __future__ import annotations

import atexit
import json
import shutil
import tempfile
import weakref
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from deletion_audit.engine import World, build_context, build_world
from deletion_audit.model import (
    BudgetGuard,
    Failure,
    FakeTransport,
    MemoryCallLog,
    ModelClient,
    ReplyCache,
    RetryPolicy,
)

from ..engine_fixtures import Dataset, Person, bundle, case, kv_line

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 24
ADA, BO, CY = "ada@example.test", "bo@example.test", "cy@example.test"
DELETE_TEXT = "Please delete my account and every record you keep about me."
KEEP_TEXT = "Send me a copy of my data. Do not remove anything."


def tmpdir() -> Path:
    """A temporary directory removed when the interpreter exits."""
    path = Path(tempfile.mkdtemp(prefix="agent-test-"))
    atexit.register(shutil.rmtree, str(path), True)
    return path


class Rig:
    """One or more ModelClients on one FakeTransport and one BudgetGuard, each with its own cache root."""

    def __init__(self, script: Sequence[Any], *, clients: int = 1, replay_only: bool = False,
                 dollar_cap: float = 5.0, call_cap: int = 200, root: Path | None = None,
                 transport: FakeTransport | None = None) -> None:
        self.root = root or tmpdir()
        self.transport = transport or FakeTransport(list(script))
        self.log = MemoryCallLog()
        self.budget = BudgetGuard(dollar_cap, call_cap, self.root / "ledger.jsonl")
        self.policy = RetryPolicy(sleep=lambda _s: None)
        self.clients = [
            ModelClient(self.transport, ReplyCache(self.root / f"replies-{i}"), self.budget, self.policy, self.log,
                        replay_only=replay_only, run_id="run-agent-test")
            for i in range(clients)
        ]
        weakref.finalize(self, self.budget.release_run_lock)

    @property
    def client(self) -> ModelClient:
        """The first client."""
        return self.clients[0]

    def sent(self) -> list[dict[str, Any]]:
        """Every body the transport was sent, as plain JSON."""
        return [json.loads(json.dumps(b, default=dict)) for b in self.transport.sent]


def _envelope(content: list[dict[str, Any]], stop_reason: str) -> dict[str, Any]:
    return {
        "id": "msg_test", "type": "message", "role": "assistant", "model": "claude-sonnet-5-5",
        "content": [{"type": "thinking", "thinking": "", "signature": "sig"}, *content],
        "stop_reason": stop_reason, "stop_sequence": None,
        "usage": {"input_tokens": 900, "output_tokens": 300, "cache_creation_input_tokens": 0,
                  "cache_read_input_tokens": 0},
    }


def answer(intent: str = "NOT_DELETION", quote: str = "Send me a copy of my data", *, kind: str = "access",
           answers: Sequence[dict[str, Any]] = (), cannot: Sequence[dict[str, Any]] = (),
           instruction_like: bool = False) -> dict[str, Any]:
    """A final-answer JSON value."""
    return {"intent": intent, "request_kind": kind, "language": "en", "basis_quote": quote,
            "instruction_like_text": instruction_like, "answers": list(answers), "cannot_answer": list(cannot),
            "uncertain_reason": "the text does not say" if intent == "UNCERTAIN" else ""}


def final_reply(value: dict[str, Any], *, stop_reason: str = "end_turn") -> dict[str, Any]:
    """A reply whose last text block is ``value`` as JSON."""
    return _envelope([{"type": "text", "text": json.dumps(value)}], stop_reason)


def audit_input(quote: str = "delete my account", **kw: Any) -> dict[str, Any]:
    """A valid ``audit_case`` input for :data:`DELETE_TEXT`."""
    base = {"intent": "DELETION_REQUEST", "request_kind": "full_deletion", "language": "en", "basis_quote": quote,
            "instruction_like_text": False}
    base.update(kw)
    return base


def tool_reply(*uses: tuple[str, dict[str, Any]]) -> dict[str, Any]:
    """A reply calling the given tools, in order, with ids ``toolu_1``..."""
    blocks = [{"type": "tool_use", "id": f"toolu_{i + 1}", "name": n, "input": a} for i, (n, a) in enumerate(uses)]
    return _envelope(blocks, "tool_use")


def failure(status: int | None, error_class: str) -> Failure:
    """A scripted transport failure."""
    return Failure(kind="TRANSPORT", error_class=error_class, status=status)


def answer_for(oq_id: str, choice: str, evidence: Sequence[str] = (), note: str = "n") -> dict[str, Any]:
    """One answer entry."""
    return {"oq_id": oq_id, "choice": choice, "evidence_ids": list(evidence), "note": note}


#: The two synthetic cases (ruled shape, built at run time).
C1, C2 = case(9001), case(9002)


# --------------------------------------------------------------------------- datasets
def dataset(*, text_ada: str = DELETE_TEXT, text_bo: str = KEEP_TEXT, image: bytes | None = None,
            intake_for_ada: bool = False) -> Dataset:
    """Ada asks for deletion and has a live account (a finding). Bo has a live account and, by default,
    a request that is not a deletion, with a non-deletion intake row. Optionally a screenshot of a
    connector that the catalog ties to Ada, and an intake row on Ada's account."""
    d = Dataset(people=[Person("user_9001", ADA), Person("user_9002", BO)])
    d.add_request(C1, ADA, request_text=text_ada)
    d.add_request(C2, BO, request_text=text_bo)
    log = (kv_line("2026-05-02T10:00:00Z", service="account_service", trace_id="t1", event="profile_lookup_completed",
                   resource_id="account_900000001", http_status="200", lookup_key=ADA)
           + kv_line("2026-05-02T10:05:00Z", service="account_service", trace_id="t2",
                     event="profile_lookup_completed", resource_id="account_900000002", http_status="200",
                     lookup_key=BO))
    d.add_file("ev_1", "logs/lookup.log", "2026-05-03T00:00:00Z", log)
    d.add_file("ev_late", "records/late.json", "2026-05-09T00:00:00Z",
               bundle(("2026-05-08T00:00:00Z", "account_service", "customer_profiles",
                       [{"resource_id": "account_900000001", "email": ADA, "account_status": "ACTIVE"}])))
    d.add_activity("a_2", "2026-05-02T09:00:00Z", "CLASSIFY_REQUEST", "privacy_intake", "privacy_case_management",
                   "account_900000002", "SUCCESS", "Privacy intake classified request for account_900000002 as "
                   "non-deletion; no destructive action was authorized.")
    d.add_activity("a_9", "2026-05-06T09:00:00Z", "UPDATE_RECORD", "account_service", "account_service",
                   "account_900000001", "SUCCESS", "late update of account_900000001")
    if intake_for_ada:
        d.add_activity("a_3", "2026-05-02T09:30:00Z", "CLASSIFY_REQUEST", "privacy_intake",
                       "privacy_case_management", "account_900000001", "SUCCESS",
                       "Privacy intake classified request for account_900000001 as non-deletion.")
    if image is not None:
        d.add_file("ev_img", "images/console.png", "2026-05-02T11:00:00Z", image)
        d.add_activity("a_4", "2026-05-02T11:07:01Z", "LINK_RESOURCE_IDENTITY", "data_catalog", "integration_service",
                       "data_flow_900000003", "SUCCESS",
                       f"Data catalog linked data_flow_900000003 (data_flow_900000003) to {ADA} and user_9001.")
        d.add_activity("a_5", "2026-05-02T11:07:02Z", "LINK_RESOURCE_IDENTITY", "data_catalog", "object_storage",
                       "object_900000004", "SUCCESS",
                       f"Attachment catalog confirmed object_900000004 (receipt_900000004.pdf) belongs to {ADA}.")
    return d


def world_of(d: Dataset, image_observations: Sequence[Any] = ()) -> World:
    """Write ``d`` to a temporary directory and build the engine's world on it."""
    root = d.write(tmpdir())
    return build_world(build_context(root, image_observations=image_observations))


def fixture_world(name: str) -> World:
    """The engine's world on one committed G5b fixture folder (made-up people and IDs)."""
    root = Path(__file__).resolve().parents[1] / "fixtures" / name
    return build_world(build_context(root))


def bodies_tool_choice(rig: Rig) -> list[str | None]:
    """The tool_choice type of every body sent (None when absent)."""
    return [(b.get("tool_choice") or {}).get("type") for b in rig.sent()]
