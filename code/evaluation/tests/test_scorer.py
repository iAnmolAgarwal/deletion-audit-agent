"""Each metric on small hand-built fixtures with answers worked out by hand."""
from __future__ import annotations

import json
import unittest

from evaluation.scorer import aggregate, match_steps, pairwise_order, score_case, score_predictions

from .fixtures import complete_example, gold, incomplete_example, renumber, row, st


class TestCaseA_MissingStepAndWrongEvidence(unittest.TestCase):
    """Gold: 4-step INCOMPLETE. Pred: last step missing, finding cites the wrong file."""

    def setUp(self) -> None:
        g = incomplete_example("evidence_01")
        p = [dict(s) for s in g[:3]]
        p[0]["evidence_id"] = "evidence_02"
        self.c = score_case(row("case_a", "INCOMPLETE", p), gold("case_a", "INCOMPLETE", g))

    def test_status_and_row(self) -> None:
        self.assertTrue(self.c["status_ok"])
        self.assertFalse(self.c["steps_exact"])
        self.assertFalse(self.c["row_exact"])

    def test_step_counts(self) -> None:
        self.assertEqual((self.c["step_tp"], self.c["n_pred"], self.c["n_gold"]), (3, 3, 4))
        self.assertEqual(self.c["per_op"]["REPORT_REMAINING_RECORD"], [1, 1, 1])
        self.assertEqual(self.c["per_op"]["VERIFY_RECORD_PRESENT"], [0, 0, 1])

    def test_fields_on_matched(self) -> None:
        self.assertEqual(self.c["field_eq"], {"state": 3, "evidence_id": 2, "step_no": 3})
        self.assertEqual(self.c["field_all_eq"], 2)

    def test_sequence(self) -> None:
        self.assertFalse(self.c["order_exact"])
        self.assertEqual((self.c["order_concordant"], self.c["order_pairs"]), (3, 3))

    def test_citations(self) -> None:
        self.assertEqual((self.c["cite_steps"], self.c["cite_eq"]), (1, 0))
        self.assertFalse(self.c["citation_set_exact"])
        self.assertEqual((self.c["cite_tp"], self.c["cite_pred"], self.c["cite_gold"]), (0, 1, 1))

    def test_prep_definitions(self) -> None:
        self.assertEqual(self.c["prep_tuple_tp"], 2)
        self.assertEqual((self.c["prep_pos_hits"], self.c["prep_pos_slots"]), (6 + 7 + 7, 28))
        self.assertEqual((self.c["res_tp"], self.c["res_pred"], self.c["res_gold"]), (1, 1, 2))

    def test_diff(self) -> None:
        self.assertEqual(self.c["diff"]["missing_steps"],
                         [["VERIFICATION", "VERIFY_RECORD_PRESENT", "security_service", "audit_record_1"]])
        self.assertEqual(self.c["diff"]["extra_steps"], [])
        self.assertEqual(len(self.c["diff"]["field_mismatches"]), 1)


class TestCaseB_OrderOnly(unittest.TestCase):
    """Same steps, swapped and renumbered: only order and step_no are wrong."""

    def setUp(self) -> None:
        g = complete_example()
        p = renumber([g[1], g[0]])
        self.c = score_case(row("case_b", "COMPLETE", p), gold("case_b", "COMPLETE", g))

    def test(self) -> None:
        self.assertTrue(self.c["status_ok"])
        self.assertFalse(self.c["row_exact"])
        self.assertEqual(self.c["step_tp"], 2)
        self.assertEqual(self.c["field_eq"], {"state": 2, "evidence_id": 2, "step_no": 0})
        self.assertFalse(self.c["order_exact"])
        self.assertEqual((self.c["order_concordant"], self.c["order_pairs"]), (0, 1))
        self.assertTrue(self.c["citation_set_exact"])
        self.assertEqual(self.c["prep_tuple_tp"], 2)        # prep tuple ignores step_no and order
        self.assertEqual(self.c["prep_pos_hits"], 2 * 5)    # positional: step_no, phase, operation, state, evidence agree per slot


class TestCaseC_KeyOrderAndWhitespaceIgnored(unittest.TestCase):
    def test(self) -> None:
        g = complete_example()
        raw = json.dumps([dict(reversed(list(s.items()))) for s in g], indent=3)
        c = score_case(row("case_c", "COMPLETE", None, raw=raw), gold("case_c", "COMPLETE", g))
        self.assertTrue(c["row_exact"])
        self.assertTrue(c["order_exact"])


class TestInvalidAndMissing(unittest.TestCase):
    def test_missing_prediction(self) -> None:
        g = incomplete_example()
        c = score_case(None, gold("case_d", "INCOMPLETE", g))
        self.assertEqual(c["pred_status"], "MISSING")
        self.assertFalse(c["status_ok"] or c["row_exact"])
        self.assertEqual((c["step_tp"], c["n_gold"]), (0, 4))

    def test_unparseable_never_counts_as_empty(self) -> None:
        c = score_case(row("case_e", "NOT_APPLICABLE", None, raw="[{broken"), gold("case_e", "NOT_APPLICABLE", []))
        self.assertTrue(c["status_ok"])
        self.assertFalse(c["pred_valid"])
        self.assertFalse(c["steps_exact"])
        self.assertFalse(c["row_exact"])
        self.assertFalse(c["order_exact"])

    def test_non_list_json_is_invalid(self) -> None:
        c = score_case(row("case_f", "NOT_APPLICABLE", None, raw="{}"), gold("case_f", "NOT_APPLICABLE", []))
        self.assertFalse(c["pred_valid"])

    def test_na_empty_matches(self) -> None:
        c = score_case(row("case_g", "NOT_APPLICABLE", []), gold("case_g", "NOT_APPLICABLE", []))
        self.assertTrue(c["row_exact"])
        self.assertEqual(c["order_pairs"], 0)

    def test_step_no_type_matters(self) -> None:
        g = complete_example()
        p = [dict(s, step_no=str(s["step_no"])) for s in g]
        c = score_case(row("case_h", "COMPLETE", p), gold("case_h", "COMPLETE", g))
        self.assertFalse(c["row_exact"])
        self.assertEqual(c["field_eq"]["step_no"], 0)

    def test_status_wrong_steps_right(self) -> None:
        g = complete_example()
        c = score_case(row("case_i", "INCOMPLETE", g), gold("case_i", "COMPLETE", g))
        self.assertTrue(c["steps_exact"])
        self.assertFalse(c["row_exact"])

    def test_non_object_step(self) -> None:
        g = complete_example()
        c = score_case(row("case_j", "COMPLETE", [g[0], "oops"]), gold("case_j", "COMPLETE", g))
        self.assertEqual((c["step_tp"], c["n_pred"]), (1, 2))


class TestMatching(unittest.TestCase):
    def test_duplicates_match_one_to_one(self) -> None:
        a = st(1, "VERIFY_RECORD_ABSENT", "account_service", "account_1")
        self.assertEqual(match_steps([a], [a, dict(a, step_no=2)]), [(0, 0)])
        self.assertEqual(len(match_steps([a, a], [a, a])), 2)

    def test_pairwise_order(self) -> None:
        self.assertEqual(pairwise_order([(0, 0), (1, 1), (2, 2)]), (3, 3))
        self.assertEqual(pairwise_order([(2, 0), (1, 1), (0, 2)]), (0, 3))
        self.assertEqual(pairwise_order([(0, 0), (2, 1), (1, 2)]), (2, 3))
        self.assertEqual(pairwise_order([(0, 0)]), (0, 0))


class TestAggregate(unittest.TestCase):
    def setUp(self) -> None:
        gi, gc = incomplete_example(), complete_example()
        pa = [dict(s) for s in gi[:3]]
        pa[0]["evidence_id"] = "evidence_02"
        self.gold = {"case_a": gold("case_a", "INCOMPLETE", gi), "case_b": gold("case_b", "COMPLETE", gc),
                     "case_c": gold("case_c", "COMPLETE", gc), "case_d": gold("case_d", "INCOMPLETE", gi)}
        self.preds = {"case_a": row("case_a", "INCOMPLETE", pa),
                      "case_b": row("case_b", "COMPLETE", renumber([gc[1], gc[0]])),
                      "case_c": row("case_c", "COMPLETE", gc),
                      "case_x": row("case_x", "COMPLETE", gc)}          # not in gold: listed, not scored
        self.res = score_predictions(self.preds, self.gold)
        self.p = self.res["aggregate"]["published"]

    def test_case_level(self) -> None:
        self.assertEqual(self.res["aggregate"]["cases"], 4)
        self.assertEqual((self.p["status_accuracy"]["n"], self.p["status_accuracy"]["of"]), (3, 4))
        self.assertEqual(self.p["row_exact"]["n"], 1)
        self.assertEqual(self.p["status_confusion"]["INCOMPLETE"]["MISSING"], 1)
        self.assertEqual(self.p["status_confusion"]["COMPLETE"]["COMPLETE"], 2)
        self.assertEqual(self.res["gold_cases_without_pred"], ["case_d"])
        self.assertEqual(self.res["pred_cases_not_in_gold"], 1)

    def test_step_micro(self) -> None:
        s = self.p["step"]
        self.assertEqual((s["tp"], s["pred"], s["gold"]), (3 + 2 + 2, 3 + 2 + 2, 4 + 2 + 2 + 4))
        self.assertAlmostEqual(s["precision"], 1.0)
        self.assertAlmostEqual(s["recall"], 7 / 12)
        self.assertAlmostEqual(s["f1"], 2 * (7 / 12) / (1 + 7 / 12))
        self.assertEqual(self.p["step_per_operation"]["VERIFY_RECORD_PRESENT"]["recall"], 0.0)

    def test_fields_sequence_citations(self) -> None:
        f = self.p["field_on_matched"]
        self.assertEqual((f["state"]["n"], f["evidence_id"]["n"], f["step_no"]["n"], f["state"]["of"]), (7, 6, 5, 7))
        self.assertEqual(self.p["sequence_exact"]["n"], 1)
        so = self.p["sequence_pairwise_order"]
        self.assertEqual((so["n"], so["of"], so["cases_with_pairs"], so["cases_without_pairs"]), (3 + 0 + 1, 3 + 1 + 1, 3, 1))
        self.assertEqual(self.p["citation_set_exact"]["n"], 2)
        self.assertEqual((self.p["citation_on_cited_steps"]["n"], self.p["citation_on_cited_steps"]["of"]), (4, 5))

    def test_prep_block(self) -> None:
        q = self.res["aggregate"]["prep"]
        self.assertEqual(q["case_exact"]["n"], 1)
        self.assertEqual(q["step_tuple"]["tp"], 2 + 2 + 2)
        self.assertEqual((q["field_positional"]["n"], q["field_positional"]["of"]), (20 + 10 + 14 + 0, 28 + 14 + 14 + 28))

    def test_empty_prf(self) -> None:
        agg = aggregate([])
        self.assertIsNone(agg["published"]["step"]["f1"])


if __name__ == "__main__":
    unittest.main()
