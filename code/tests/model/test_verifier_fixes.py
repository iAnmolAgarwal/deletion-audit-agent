"""GM review round 2 (developer decision T85): one test class per verifier finding F1-F5 and notes 1-2."""
from __future__ import annotations

import json
import math
import os
import unittest
from pathlib import Path
from typing import Any

from deletion_audit.model import (
    AnthropicTransport,
    BudgetGuard,
    CacheCorruptError,
    ModelCallFailed,
    ModelRequest,
    PaidRunLocked,
    RequestRejected,
    TransportFailure,
)
from deletion_audit.model.schema_check import check_schema_supported, validate

from ._support import Rig, body, reply, transport_failure

TOOLS = [{"name": "lookup", "description": "d", "input_schema": {"type": "object"}}]
OK = {"intent": "DELETION_REQUEST", "note": "n"}


def ledger_costs(rig: Rig) -> list[float]:
    """The cost_usd of every ledger line, in order."""
    return [json.loads(x)["cost_usd"] for x in rig.ledger.read_text().splitlines()]


class F1DeepFreeze(unittest.TestCase):
    """Nested parts of a built request cannot be changed, and every send re-checks the rules."""

    def test_nested_body_is_read_only(self) -> None:
        """Assigning into a nested mapping or appending to a nested list raises TypeError/AttributeError."""
        req = ModelRequest(body(tools=TOOLS, tool_choice={"type": "auto"}))
        with self.assertRaises(TypeError):
            req.body["tool_choice"]["type"] = "any"
        with self.assertRaises(TypeError):
            req.body["output_config"]["format"]["type"] = "text"
        with self.assertRaises((TypeError, AttributeError)):
            req.body["messages"].append({"role": "user", "content": "x"})

    def test_reply_request_cannot_drift_from_its_key(self) -> None:
        """A reply's request cannot be extended in place; its key stays the reply's key."""
        rig = Rig([reply()])
        out = rig.client.call(ModelRequest(body()))
        with self.assertRaises((TypeError, AttributeError)):
            out.request.body["messages"].append({"role": "assistant", "content": "x"})
        self.assertEqual(out.key, out.request.key())

    def test_send_rechecks_rules(self) -> None:
        """A request whose body breaks a rule after it was built is refused before any send."""
        rig = Rig([reply()])
        req = ModelRequest(body())
        object.__setattr__(req, "body", {**body(), "temperature": 0})
        with self.assertRaises(RequestRejected):
            rig.client.call(req)
        self.assertEqual(rig.transport.calls, 0)
        self.assertEqual(rig.budget.calls, 0)


class F2RefShapeAndExactCompare(unittest.TestCase):
    """$ref with sibling keywords is refused; enum/const compare exactly at every depth."""

    REF_SCHEMA: dict[str, Any] = {
        "$defs": {"S": {"type": "string"}}, "type": "object", "additionalProperties": False,
        "required": ["intent"], "properties": {"intent": {"$ref": "#/$defs/S", "enum": ["DELETION_REQUEST"]}},
    }

    def test_ref_with_siblings_unsupported(self) -> None:
        """The shape is reported by check_schema_supported and rejected when the request is built."""
        self.assertNotEqual(check_schema_supported(self.REF_SCHEMA), [])
        b = body()
        b["output_config"]["format"]["schema"] = self.REF_SCHEMA
        with self.assertRaises(RequestRejected):
            ModelRequest(b)
        plain_ref = {**self.REF_SCHEMA, "properties": {"intent": {"$ref": "#/$defs/S"}}}
        self.assertEqual(check_schema_supported(plain_ref), [])

    def test_validate_refuses_ref_siblings(self) -> None:
        """validate() itself reports a $ref node with siblings instead of skipping them."""
        self.assertNotEqual(validate({"intent": "not_deletion"}, self.REF_SCHEMA), [])

    def test_nested_compare_is_type_exact(self) -> None:
        """[True] is not [1]; {"a": False} is not {"a": 0}; 1.0 is not 1; equal nested values match."""
        self.assertNotEqual(validate([True], {"enum": [[1]]}), [])
        self.assertNotEqual(validate({"a": False}, {"const": {"a": 0}}), [])
        self.assertNotEqual(validate(1.0, {"const": 1}), [])
        self.assertNotEqual(validate({"a": 1, "b": 2}, {"const": {"a": 1}}), [])
        self.assertEqual(validate({"a": [1, "x"]}, {"const": {"a": [1, "x"]}}), [])
        self.assertEqual(validate([True], {"enum": [[1], [True]]}), [])


class F3FiniteBudget(unittest.TestCase):
    """Caps and ledger costs must be finite, non-negative numbers."""

    def test_bad_caps_rejected(self) -> None:
        """NaN, infinity, negative, string or bool caps are refused at construction."""
        ledger = Path("unused-ledger.jsonl")
        for dollar, calls, project in ((math.nan, 1, 1.0), (math.inf, 1, 1.0), (-1.0, 1, 1.0), (1.0, 1, math.nan),
                                       (1.0, 1, -0.5), (1.0, -1, 1.0), ("5", 1, 1.0), (1.0, True, 1.0),
                                       (1.0, 1.5, 1.0)):
            with self.subTest(dollar=dollar, calls=calls, project=project), self.assertRaises(ValueError):
                BudgetGuard(dollar, calls, ledger, project)  # type: ignore[arg-type]

    def test_bad_ledger_costs_fail_closed(self) -> None:
        """NaN, Infinity, "nan", negative, bool and missing costs each stop the call as LedgerUnreadable."""
        for line in ('{"cost_usd": NaN}', '{"cost_usd": Infinity}', '{"cost_usd": "nan"}', '{"cost_usd": "0.1"}',
                     '{"cost_usd": -500}', '{"cost_usd": true}', '{"cost": 1}', '[1]'):
            with self.subTest(line=line):
                rig = Rig([reply()], project_cap=110.0)
                rig.ledger.write_text(line + "\n")
                with self.assertRaises(ModelCallFailed) as ctx:
                    rig.client.call(ModelRequest(body()))
                self.assertEqual((ctx.exception.reason, ctx.exception.error_class), ("BUDGET", "LedgerUnreadable"))
                self.assertEqual(rig.transport.calls, 0)

    def test_negative_usage_charged_at_worst_case(self) -> None:
        """A reply reporting negative tokens is never booked as a refund."""
        rig = Rig([reply(input_tokens=-10_000_000, output_tokens=0)])
        rig.client.call(ModelRequest(body(max_tokens=1000)))
        self.assertGreaterEqual(ledger_costs(rig)[0], 1000 * 10 / 1_000_000)


class F4UncertainOutcomeCharged(unittest.TestCase):
    """Sends whose outcome is unknown are charged at the reservation; status rejections at $0."""

    def test_timeouts_and_connection_errors_at_worst_case(self) -> None:
        """Each timeout or dropped connection costs at least max_tokens x $10/M."""
        for cls in ("APITimeoutError", "APIConnectionError"):
            with self.subTest(cls=cls):
                rig = Rig([transport_failure(None, cls), reply(input_tokens=0, output_tokens=0)])
                rig.client.call(ModelRequest(body(max_tokens=1000)))
                costs = ledger_costs(rig)
                self.assertGreaterEqual(costs[0], 1000 * 10 / 1_000_000)
                self.assertEqual(costs[1], 0.0)

    def test_status_rejections_at_zero(self) -> None:
        """408, 409, 429, 529, 500 and 400 rejections are settled at $0."""
        for status in (408, 409, 429, 529, 500, 400):
            with self.subTest(status=status):
                rig = Rig([transport_failure(status, "X"), reply(input_tokens=0, output_tokens=0)])
                try:
                    rig.client.call(ModelRequest(body()))
                except ModelCallFailed:
                    pass
                self.assertEqual(ledger_costs(rig)[0], 0.0)

    def test_connection_lost_mid_reply_is_a_connection_error(self) -> None:
        """A read error while the SDK reads the body becomes a retryable APIConnectionError, charged at worst."""
        import httpx2

        class Raw:
            request_id = "req_x"

            def json(self) -> Any:
                raise httpx2.RemoteProtocolError("peer closed connection without sending complete message body")

        transport = AnthropicTransport(client=_stub(lambda: Raw()))
        with self.assertRaises(TransportFailure) as ctx:
            transport.send({"model": "claude-sonnet-5-5"})
        self.assertEqual((ctx.exception.failure.error_class, ctx.exception.failure.status),
                         ("APIConnectionError", None))


def _stub(make: Any) -> Any:
    """A stand-in SDK client whose messages.with_raw_response.create returns make()."""

    class Stub:
        max_retries = 0

        def __init__(self) -> None:
            self.messages = self
            self.with_raw_response = self

        def create(self, **_kw: Any) -> Any:
            return make()

    return Stub()


class F5EveryFailureLogged(unittest.TestCase):
    """Each failure path leaves a call-log entry with its error class and status."""

    def test_unexpected_transport_exception_logged(self) -> None:
        """A non-TransportFailure exception is re-raised and logged with its class and no status."""

        class Boom:
            def send(self, _body: Any) -> Any:
                raise ValueError("unexpected")

        rig = Rig([])
        rig.client.transport = Boom()
        with self.assertRaises(ValueError):
            rig.client.call(ModelRequest(body()))
        self.assertEqual(rig.events(), [("send", 1, "failed", "ValueError", None)])

    def test_non_json_200_is_malformed_reply_and_logged(self) -> None:
        """AnthropicTransport turns an unreadable 200 body into MalformedReply (status 200); the client logs it."""

        class Raw:
            request_id = "req_y"

            def json(self) -> Any:
                return json.loads("<html>")

        with self.assertRaises(TransportFailure) as ctx:
            AnthropicTransport(client=_stub(lambda: Raw())).send({"model": "claude-sonnet-5-5"})
        self.assertEqual((ctx.exception.failure.error_class, ctx.exception.failure.status), ("MalformedReply", 200))
        rig = Rig([transport_failure(200, "MalformedReply")])
        with self.assertRaises(ModelCallFailed) as fail:
            rig.client.call(ModelRequest(body()))
        self.assertEqual(fail.exception.reason, "NON_RETRYABLE")
        self.assertEqual(rig.events(), [("send", 1, "give_up", "MalformedReply", 200)])

    def test_paid_run_locked_logged(self) -> None:
        """A send without the run lock logs PaidRunLocked with no status."""
        rig = Rig([reply()])
        rig.client.close()
        with self.assertRaises(PaidRunLocked):
            rig.client.call(ModelRequest(body()))
        self.assertEqual(rig.events(), [("error", 1, "failed", "PaidRunLocked", None)])

    def test_cache_corrupt_logged(self) -> None:
        """A corrupt cache entry logs CacheCorruptError with no status."""
        rig = Rig([reply()])
        req = ModelRequest(body())
        rig.client.call(req)
        rig.cache.path_for(req.key()).write_text("{bad")
        rig.log.entries.clear()
        with self.assertRaises(CacheCorruptError):
            rig.client.call(req)
        self.assertEqual(rig.events(), [("error", 1, "failed", "CacheCorruptError", None)])


class Note1CacheFieldsMatchRaw(unittest.TestCase):
    """An entry's model and usage must equal those inside its raw reply."""

    def test_edited_model_or_usage_is_corrupt(self) -> None:
        """Editing either top-level copy makes the entry unreadable."""
        for field, value in (("model", "other-model"), ("usage", {"input_tokens": 1, "output_tokens": 1})):
            with self.subTest(field=field):
                rig = Rig([reply()])
                req = ModelRequest(body())
                rig.client.call(req)
                path = rig.cache.path_for(req.key())
                entry = json.loads(path.read_text())
                entry[field] = value
                path.write_text(json.dumps(entry))
                with self.assertRaises(CacheCorruptError):
                    rig.cache.get(req.key())


class Note2LockFollowsResolvedLedger(unittest.TestCase):
    """Two paths to the same ledger share one lock."""

    def test_symlinked_ledger_shares_the_lock(self) -> None:
        """A guard on a symlink to the held ledger cannot take the lock."""
        rig = Rig([reply()])
        rig.ledger.touch()
        alias = rig.root / "alias.jsonl"
        os.symlink(rig.ledger, alias)
        with self.assertRaises(PaidRunLocked):
            BudgetGuard(1.0, 1, alias).acquire_run_lock()
        dotted = rig.root / "sub" / ".." / rig.ledger.name
        (rig.root / "sub").mkdir()
        with self.assertRaises(PaidRunLocked):
            BudgetGuard(1.0, 1, dotted).acquire_run_lock()
        rig.client.close()


if __name__ == "__main__":
    unittest.main()
