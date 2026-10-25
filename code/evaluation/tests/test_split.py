"""The split constants mirror notes/split.json exactly."""
from __future__ import annotations

import json
import unittest
from typing import Any

from evaluation.paths import SPLIT_JSON
from evaluation.split import DEV_IDS, HOLDOUT_IDS, SPLIT_SEED


class TestSplit(unittest.TestCase):
    def setUp(self) -> None:
        # notes/ belongs to the build workspace and is not shipped in code.zip (README).
        self.js: dict[str, Any] | None = (json.loads(SPLIT_JSON.read_text(encoding="utf-8"))
                                         if SPLIT_JSON.exists() else None)

    @property
    def split(self) -> dict[str, Any]:
        if self.js is None:
            self.skipTest("notes/split.json is not shipped (code.zip holds README.md and code/ only)")
        return self.js

    def test_dev_equals_json(self) -> None:
        self.assertEqual(DEV_IDS, frozenset(self.split["dev"]))
        self.assertEqual(len(self.split["dev"]), len(set(self.split["dev"])))

    def test_holdout_equals_json(self) -> None:
        self.assertEqual(HOLDOUT_IDS, frozenset(self.split["holdout"]))

    def test_seed_and_sizes(self) -> None:
        self.assertEqual(SPLIT_SEED, self.split["seed"])
        self.assertEqual(len(DEV_IDS), self.split["dev_size"])
        self.assertEqual(len(HOLDOUT_IDS), self.split["holdout_size"])

    def test_disjoint_and_cover_32(self) -> None:
        self.assertFalse(DEV_IDS & HOLDOUT_IDS)
        self.assertEqual(DEV_IDS | HOLDOUT_IDS, {f"case_{i:02d}" for i in range(1, 33)})

    def test_holdout_is_the_briefed_ten(self) -> None:
        holdout_numbers = ("04", "06", "10", "13", "14", "23", "25", "28", "29", "32")
        self.assertEqual(HOLDOUT_IDS, {f"case_{i}" for i in holdout_numbers})


if __name__ == "__main__":
    unittest.main()
