"""The two tool-use rates (audit_case; other read-only tools) in the agent report, each with its run ID.

Synthetic runs from ``test_agent_report``'s four test cases; expected counts are written out by hand.
"""
from __future__ import annotations

import unittest

from evaluation.agent_report import AUDIT_CASE_TOOL, READ_ONLY_TOOLS, Spec, rate_text, render_markdown

from .test_agent_report import Base


class TestReadOnlyToolSet(unittest.TestCase):
    def test_read_only_tools_are_the_agents_tools_without_audit_case(self) -> None:
        # the evaluation package keeps its own copy (it never imports the pipeline at report time); this keeps
        # the copy equal to the tool list the agent is actually offered
        from deletion_audit.agent.tools import TOOL_NAMES
        self.assertEqual(set(READ_ONLY_TOOLS), set(TOOL_NAMES) - {AUDIT_CASE_TOOL})

    def test_rate_text(self) -> None:
        self.assertEqual(rate_text(1, 4), "1/4 (0.2500)")
        self.assertEqual(rate_text(0, 0), "0/0")


class TestTwoRates(Base):
    def test_both_rates_are_counted_and_rendered_with_the_run_id(self) -> None:
        self.test_run()
        rep = self.report(Spec(test={"A+": "t-aplus"}))
        n = rep["n_tools"]["test"]["A+"]
        # case_901-903 call audit_case (1, 1 and 2 calls), case_904 does not -> 3 of 4 cases, 4 calls;
        # case_901-903 call read-only tools, case_904 none -> 3 of 4
        self.assertEqual((n["audit_case"]["cases_with_call"], n["audit_case"]["calls"]), (3, 4))
        self.assertEqual(n["cases_with_read_only_tool"], 3)
        md = render_markdown(rep)
        self.assertIn("- Tool-use rate, audit_case: 3/4 (0.7500) cases called audit_case (4 calls); run `t-aplus`.", md)
        self.assertIn("- Tool-use rate, other read-only tools (get_request_context, inspect_evidence, lookup_identity, "
                      "list_activity): 3/4 (0.7500) cases (5 calls other than audit_case); run `t-aplus`.", md)
        self.assertIn("- Cases with a tool name outside both sets: 0.", md)


if __name__ == "__main__":
    unittest.main()
