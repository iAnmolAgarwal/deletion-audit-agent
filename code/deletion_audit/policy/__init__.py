"""Policy: data categories and the ``deletion_rules.csv`` decision table (R9-R12, T9, T55, T69)."""

from __future__ import annotations

from .rules import Categorization, PolicyDecision, Rule, RuleTable, categorize, decide, load_rules, violating_states

__all__ = [
    "Categorization",
    "PolicyDecision",
    "Rule",
    "RuleTable",
    "categorize",
    "decide",
    "load_rules",
    "violating_states",
]
