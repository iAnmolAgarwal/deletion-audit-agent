"""Reply failures: max_tokens, refusals, context window, schema mismatch, bounded repair."""
from __future__ import annotations

import json
import unittest

from deletion_audit.model import ModelCallFailed, ModelRequest, reply_text

from ._support import Rig, body, reply

OK = {"intent": "DELETION_REQUEST", "note": "n"}


class TestReplyFailures(unittest.TestCase):
    """Reply checks and repairs through the client."""

    def test_max_tokens_refusal_context_window_are_failures(self) -> None:
        """max_tokens (even with valid JSON) and refusal are repaired; context window gives up at once."""
        for stop in ("max_tokens", "refusal"):
            with self.subTest(stop=stop):
                rig = Rig([reply(OK, stop_reason=stop), reply(OK)])
                out = rig.client.call(ModelRequest(body()))
                self.assertEqual(rig.transport.calls, 2)
                self.assertEqual(out.stop_reason, "end_turn")
                self.assertIn(("reply_check", 1, "repair", stop, 200), rig.events())
        rig = Rig([reply(OK, stop_reason="model_context_window_exceeded")])
        with self.assertRaises(ModelCallFailed) as ctx:
            rig.client.call(ModelRequest(body()))
        self.assertEqual((ctx.exception.reason, ctx.exception.error_class),
                         ("STRUCTURE_GAVE_UP", "model_context_window_exceeded"))
        self.assertEqual(rig.transport.calls, 1)

    def test_schema_mismatch_repair_bounded_two(self) -> None:
        """Three bad replies: 3 sends (2 repairs), then STRUCTURE_GAVE_UP."""
        bad = [reply({"intent": "MAYBE", "note": "n"}), reply(text="not json"), reply({"intent": "UNCERTAIN"})]
        rig = Rig(bad)
        with self.assertRaises(ModelCallFailed) as ctx:
            rig.client.call(ModelRequest(body()))
        self.assertEqual((ctx.exception.reason, ctx.exception.error_class), ("STRUCTURE_GAVE_UP", "SchemaMismatch"))
        self.assertEqual(rig.transport.calls, 3)
        self.assertEqual([e[2] for e in rig.events() if e[0] == "reply_check"], ["repair", "repair", "give_up"])

    def test_repair_is_a_new_request_with_appended_text(self) -> None:
        """The repair keeps the original messages and adds one text block; its key differs."""
        rig = Rig([reply(OK, stop_reason="refusal"), reply(OK)])
        out = rig.client.call(ModelRequest(body()))
        first, second = rig.transport.sent
        self.assertEqual(second["messages"][0]["content"][0], first["messages"][0]["content"][0])
        self.assertEqual(len(second["messages"][0]["content"]), 2)
        self.assertTrue(second["messages"][0]["content"][1]["text"].startswith("Repair 1:"))
        self.assertNotEqual(out.key, ModelRequest(body()).key())
        self.assertEqual(out.key, ModelRequest(second).key())

    def test_failed_reply_cached_and_replayed_exactly(self) -> None:
        """A replay-only client meets the cached refusal, repairs, and gets the cached repair reply."""
        rig = Rig([reply(OK, stop_reason="refusal"), reply(OK)])
        bought = rig.client.call(ModelRequest(body()))
        replay = Rig([], root=rig.root, replay_only=True)
        again = replay.client.call(ModelRequest(body()))
        self.assertEqual((again.key, again.raw), (bought.key, bought.raw))
        self.assertEqual(replay.transport.calls, 0)

    def test_no_text_and_tool_use_rules(self) -> None:
        """end_turn with no text fails; tool_use passes only when tools are enabled."""
        empty = reply(OK)
        empty["content"] = [{"type": "thinking", "thinking": "", "signature": "s"}]
        rig = Rig([empty, reply(OK)])
        rig.client.call(ModelRequest(body()))
        self.assertIn(("reply_check", 1, "repair", "NoText", 200), rig.events())
        tools = [{"name": "lookup", "description": "d", "input_schema": {"type": "object"}}]
        tool_reply = reply(OK, stop_reason="tool_use")
        tool_reply["content"] = [{"type": "tool_use", "id": "toolu_1", "name": "lookup", "input": {}}]
        rig = Rig([tool_reply])
        out = rig.client.call(ModelRequest(body(tools=tools, tool_choice={"type": "auto"})))
        self.assertEqual(out.stop_reason, "tool_use")
        rig = Rig([tool_reply, reply(OK)])
        rig.client.call(ModelRequest(body(tools=tools, tool_choice={"type": "none"})))
        self.assertIn(("reply_check", 1, "repair", "tool_use", 200), rig.events())

    def test_enum_wrong_case_fails_and_repairs(self) -> None:
        """T84: enum matching is exact. A wrong-case value fails the check and goes to repair;
        the exact value then passes."""
        rig = Rig([reply({"intent": "not_deletion", "note": "n"}), reply(OK)])
        out = rig.client.call(ModelRequest(body()))
        self.assertEqual(rig.transport.calls, 2)
        self.assertEqual([e for e in rig.events() if e[0] == "reply_check"][0][2], "repair")
        self.assertEqual(json.loads(reply_text(out.raw) or "{}")["intent"], "DELETION_REQUEST")

    def test_enum_and_const_are_exact(self) -> None:
        """T84: the checker compares enum and const values exactly (case, type and value)."""
        from deletion_audit.model.schema_check import validate
        enum_schema = {"type": "object", "properties": {"intent": {"type": "string", "enum": ["NOT_DELETION"]}},
                       "required": ["intent"], "additionalProperties": False}
        self.assertEqual(validate({"intent": "NOT_DELETION"}, enum_schema), [])
        self.assertTrue(validate({"intent": "not_deletion"}, enum_schema))
        self.assertTrue(validate({"intent": "Not_Deletion"}, enum_schema))
        const_schema = {"type": "object", "properties": {"v": {"const": "ABSENT"}},
                        "required": ["v"], "additionalProperties": False}
        self.assertEqual(validate({"v": "ABSENT"}, const_schema), [])
        self.assertTrue(validate({"v": "absent"}, const_schema))
        number_schema = {"type": "object", "properties": {"n": {"enum": [1]}},
                         "required": ["n"], "additionalProperties": False}
        self.assertTrue(validate({"n": True}, number_schema))


if __name__ == "__main__":
    unittest.main()
