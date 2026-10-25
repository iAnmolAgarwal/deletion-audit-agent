"""ReplyCache and replay: hits make no call, entries hold raw replies only, nothing is overwritten."""
from __future__ import annotations

import json
import unittest

from deletion_audit.model import CacheCorruptError, ModelCallFailed, ModelRequest

from ._support import Rig, body, reply

ENTRY_KEYS = ["api_version", "bought_by_run", "key", "model", "raw", "request", "request_id", "usage",
              "written_at"]


class TestCache(unittest.TestCase):
    """Cache behaviour through the client."""

    def test_cache_hit_makes_no_call(self) -> None:
        """A second call for the same request is served from the cache: 1 send total, 1 ledger line."""
        rig = Rig([reply()])
        first = rig.client.call(ModelRequest(body()))
        second = rig.client.call(ModelRequest(body()))
        self.assertEqual(rig.transport.calls, 1)
        self.assertFalse(first.from_cache)
        self.assertTrue(second.from_cache)
        self.assertEqual(second.raw, first.raw)
        self.assertEqual(second.bought_by_run, "run-test")
        self.assertEqual(len(rig.ledger.read_text().splitlines()), 1)
        self.assertEqual([e.event for e in rig.log.entries], ["send", "cache_hit"])

    def test_cache_stores_raw_replies_only(self) -> None:
        """The entry's raw field is the reply exactly as sent back; no parsed answer is stored."""
        rig = Rig([reply({"intent": "NOT_DELETION", "note": "asks for an export"})])
        req = ModelRequest(body())
        rig.client.call(req)
        entry = json.loads(rig.cache.path_for(req.key()).read_text())
        self.assertEqual(sorted(entry), ENTRY_KEYS)
        self.assertEqual(entry["raw"], reply({"intent": "NOT_DELETION", "note": "asks for an export"}))
        self.assertEqual(entry["usage"], {"input_tokens": 1000, "output_tokens": 500,
                                          "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
                                          "service_tier": "standard"})
        self.assertEqual(entry["model"], "claude-sonnet-5-5")
        self.assertEqual(entry["bought_by_run"], "run-test")
        self.assertEqual(entry["request_id"], "fake-request-1")
        self.assertEqual(entry["request"], body())

    def test_put_never_overwrites(self) -> None:
        """A second put for the same key keeps the first entry byte for byte."""
        rig = Rig([])
        req = ModelRequest(body())
        rig.cache.put(req, reply({"intent": "UNCERTAIN", "note": "a"}), "run-a")
        before = rig.cache.path_for(req.key()).read_bytes()
        rig.cache.put(req, reply({"intent": "NOT_DELETION", "note": "b"}), "run-b")
        self.assertEqual(rig.cache.path_for(req.key()).read_bytes(), before)
        got = rig.cache.get(req.key())
        assert got is not None
        self.assertEqual(got.bought_by_run, "run-a")
        leftovers = [p.name for p in rig.cache.path_for(req.key()).parent.iterdir() if p.name.startswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_corrupt_entry_raises_not_a_miss(self) -> None:
        """A truncated entry, or one whose request hashes elsewhere, raises CacheCorruptError."""
        rig = Rig([])
        req = ModelRequest(body())
        rig.cache.put(req, reply(), "run-a")
        path = rig.cache.path_for(req.key())
        good = path.read_text()
        path.write_text(good[:40])
        with self.assertRaises(CacheCorruptError):
            rig.cache.get(req.key())
        tampered = json.loads(good)
        tampered["request"]["max_tokens"] = 999
        path.write_text(json.dumps(tampered))
        with self.assertRaises(CacheCorruptError):
            rig.cache.get(req.key())

    def test_replay_only_refuses_network(self) -> None:
        """Replay-only: a miss raises REPLAY_MISS with no send and no reservation; a hit replays."""
        rig = Rig([reply()], replay_only=True)
        with self.assertRaises(ModelCallFailed) as ctx:
            rig.client.call(ModelRequest(body()))
        self.assertEqual(ctx.exception.reason, "REPLAY_MISS")
        self.assertEqual(rig.transport.calls, 0)
        self.assertEqual(rig.budget.calls, 0)
        buyer = Rig([reply()], root=rig.root, run_id="run-buyer")
        buyer.client.call(ModelRequest(body()))
        replay = Rig([], root=rig.root, replay_only=True, run_id="run-replay")
        out = replay.client.call(ModelRequest(body()))
        self.assertTrue(out.from_cache)
        self.assertEqual(out.bought_by_run, "run-buyer")
        self.assertEqual(replay.transport.calls, 0)


if __name__ == "__main__":
    unittest.main()
