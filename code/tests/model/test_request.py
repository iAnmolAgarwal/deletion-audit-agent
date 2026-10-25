"""ModelRequest: build-time rejections and the content-addressed key."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
import unittest
from dataclasses import fields
from pathlib import Path

from deletion_audit.model import ModelRequest, RequestRejected

from ._support import body

CODE_DIR = Path(__file__).resolve().parents[2]


def spec_key(b: dict[str, object]) -> str:
    """The pinned key definition, restated: sha256(canonical JSON + "2023-06-01")."""
    text = json.dumps(b, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "2023-06-01"
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class TestRejections(unittest.TestCase):
    """Bodies the client must never send are refused when the request is built."""

    def test_tool_choice_never_any_or_tool(self) -> None:
        """Forced choices are rejected; auto and none are accepted."""
        tools = [{"name": "lookup", "description": "d", "input_schema": {"type": "object"}}]
        for choice in ({"type": "any"}, {"type": "tool", "name": "lookup"}, {"type": "required"}, "auto"):
            with self.subTest(choice=choice), self.assertRaises(RequestRejected):
                ModelRequest(body(tools=tools, tool_choice=choice))
        for choice in ({"type": "auto"}, {"type": "none"}):
            with self.subTest(choice=choice):
                ModelRequest(body(tools=tools, tool_choice=choice))

    def test_no_sampling_parameters_sent(self) -> None:
        """temperature, top_p and top_k are rejected at any value, including 1.0 and 0."""
        for name, value in (("temperature", 0), ("temperature", 1.0), ("top_p", 0.9), ("top_k", 5)):
            b = body()
            b[name] = value
            with self.subTest(name=name, value=value), self.assertRaises(RequestRejected):
                ModelRequest(b)

    def test_other_rules(self) -> None:
        """Streaming, unknown fields, unpriced models, bad max_tokens and missing format are rejected."""
        no_format = body()
        del no_format["output_config"]["format"]
        no_effort = body()
        del no_effort["output_config"]["effort"]
        unsupported = body()
        unsupported["output_config"]["format"]["schema"] = {"type": "string", "pattern": "^a$"}
        bad = [body(stream=True), body(metadata={}), body(model="claude-other"), body(max_tokens=0),
               body(max_tokens=21_334), no_format, no_effort, unsupported, body(messages=[])]
        for b in bad:
            with self.subTest(b=sorted(b)), self.assertRaises(RequestRejected):
                ModelRequest(b)
        ModelRequest(body(max_tokens=21_333))


class TestKey(unittest.TestCase):
    """The key is a hash of the body and API version only."""

    def test_key_matches_pinned_definition(self) -> None:
        """key() equals sha256 of the canonical body plus the API version string."""
        b = body()
        self.assertEqual(ModelRequest(b).key(), spec_key(b))

    def test_request_has_only_a_body(self) -> None:
        """There is no field a case ID or row index could ride in."""
        self.assertEqual([f.name for f in fields(ModelRequest)], ["body"])

    def test_cache_key_ignores_row_position_changes_with_any_byte(self) -> None:
        """Same body from two different rows: same key. One changed byte: a different key."""
        rows = [("row-17", "Please remove my account."), ("row-3", "Please remove my account.")]
        keys = {ModelRequest(body(text)).key() for _, text in rows}
        self.assertEqual(len(keys), 1)
        reordered = dict(reversed(list(body().items())))
        self.assertEqual(ModelRequest(reordered).key(), ModelRequest(body()).key())
        self.assertNotEqual(ModelRequest(body("Please remove my account!")).key(), ModelRequest(body()).key())
        self.assertNotEqual(ModelRequest(body(max_tokens=1001)).key(), ModelRequest(body()).key())

    def test_key_frozen_against_caller_mutation(self) -> None:
        """Mutating the caller's dict after building does not change the key."""
        b = body()
        original = copy.deepcopy(b)
        req = ModelRequest(b)
        b["messages"][0]["content"][0]["text"] = "changed"
        self.assertEqual(req.key(), spec_key(original))

    def test_same_key_in_two_processes(self) -> None:
        """Two interpreters with different hash seeds compute the same key."""
        script = ("import sys; sys.path.insert(0, sys.argv[1]); "
                  "from deletion_audit.model import ModelRequest; from tests.model._support import body; "
                  "print(ModelRequest(body('Bitte meine Daten löschen 数据')).key())")
        outs = []
        for seed in ("1", "2024"):
            env = {**os.environ, "PYTHONHASHSEED": seed}
            done = subprocess.run([sys.executable, "-B", "-c", script, str(CODE_DIR)], env=env,
                                  capture_output=True, text=True, check=True, timeout=60)
            outs.append(done.stdout.strip())
        self.assertEqual(outs[0], outs[1])
        self.assertEqual(outs[0], spec_key(body("Bitte meine Daten löschen 数据")))


if __name__ == "__main__":
    unittest.main()
