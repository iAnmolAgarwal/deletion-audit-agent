"""The split constants mirror notes/split.json exactly."""
from __future__ import annotations

import json
import unittest

from evaluation.paths import SPLIT_JSON
from evaluation.split import DEV_IDS, HOLDOUT_IDS, SPLIT_SEED


class TestSplit(unittest.TestCase):
    def setUp(self) -> None:
        self.js = json.loads(SPLIT_JSON.read_text(encoding="utf-8"))

    def test_dev_equals_json(self) -> None:
        self.assertEqual(DEV_IDS, frozenset(self.js["dev"]))
        self.assertEqual(len(self.js["dev"]), len(set(self.js["dev"])))

    def test_holdout_equals_json(self) -> None:
        self.assertEqual(HOLDOUT_IDS, frozenset(self.js["holdout"]))

    def test_seed_and_sizes(self) -> None:
        self.assertEqual(SPLIT_SEED, self.js["seed"])
        self.assertEqual(len(DEV_IDS), self.js["dev_size"])
        self.assertEqual(len(HOLDOUT_IDS), self.js["holdout_size"])

    def test_disjoint_and_cover_32(self) -> None:
        self.assertFalse(DEV_IDS & HOLDOUT_IDS)
        self.assertEqual(DEV_IDS | HOLDOUT_IDS, {f"case_{i:02d}" for i in range(1, 33)})

    def test_holdout_is_the_briefed_ten(self) -> None:
        holdout_numbers = ("04", "06", "10", "13", "14", "23", "25", "28", "29", "32")
        self.assertEqual(HOLDOUT_IDS, {f"case_{i}" for i in holdout_numbers})


if __name__ == "__main__":
    unittest.main()
