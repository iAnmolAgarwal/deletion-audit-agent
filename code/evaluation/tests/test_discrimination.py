"""The scorer moves on known-bad predictions and is invariant to key order and whitespace."""
from __future__ import annotations

import unittest
from typing import Any, ClassVar

from evaluation.coherence import load_evidence_index
from evaluation.discrimination import run
from evaluation.gold import load_gold


class TestDiscrimination(unittest.TestCase):
    t: ClassVar[dict[str, dict[str, Any]]]

    @classmethod
    def setUpClass(cls) -> None:
        cls.t = run(load_gold(), sorted(load_evidence_index().files))["table"]

    def test_gold_is_perfect(self) -> None:
        for metric, v in self.t["gold"].items():
            self.assertEqual(v, 1.0, metric)

    def test_reformatting_is_invisible(self) -> None:
        self.assertEqual(self.t["gold_reformatted"], self.t["gold"])

    def test_each_perturbation_moves_its_metric(self) -> None:
        expect_lower = {
            "majority_empty": ["status_accuracy.rate", "row_exact.rate", "step.f1"],
            "drop_last_step": ["row_exact.rate", "step.f1", "sequence_exact.rate"],
            "extra_step": ["row_exact.rate", "step.f1", "sequence_exact.rate"],
            "swap_first_two": ["row_exact.rate", "sequence_exact.rate", "sequence_pairwise_order.rate",
                               "field_on_matched.step_no.rate"],
            "wrong_state": ["row_exact.rate", "field_on_matched.state.rate"],
            "wrong_evidence": ["row_exact.rate", "field_on_matched.evidence_id.rate", "citation_set_exact.rate"],
            "step_no_shift": ["row_exact.rate", "field_on_matched.step_no.rate"],
            "flip_status": ["status_accuracy.rate", "row_exact.rate"],
        }
        for variant, metrics in expect_lower.items():
            for m in metrics:
                self.assertLess(self.t[variant][m], 1.0, f"{variant} {m}")

    def test_order_only_change_keeps_step_f1(self) -> None:
        self.assertEqual(self.t["swap_first_two"]["step.f1"], 1.0)
        self.assertEqual(self.t["flip_status"]["step.f1"], 1.0)


if __name__ == "__main__":
    unittest.main()
