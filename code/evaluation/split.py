"""The locked DEV / holdout split of the 32 sample cases (mirror of ``notes/split.json``).

Method (copied from ``notes/split.json``): status-stratified systematic sampling over
step-count order; the first seed >= 20261024 such that every operation in the sample
appears in DEV and every operation present in >= 3 sample cases appears in the holdout.
Seed: 20261025. Sizes: 22 DEV, 10 holdout.

Honesty note (also in ``notes/split.json``): the split was made in the prep session on
24 Oct 2026 AFTER the prep forensics agent had read all 32 sample answers, and the
stratification itself used gold status, step count and operations. Rules are re-derived
on DEV only, but a holdout score is therefore an optimistic estimate, not a clean one.

Holdout lock (../CLAUDE.md section 4): nobody opens, prints, diffs or computes on holdout
gold until the developer says "HOLDOUT EVALUATION RUN", once, after freeze. Gold is loaded
only through ``evaluation.gold``. ``tests/test_split.py`` asserts these constants equal the
JSON file, so the two can never drift apart silently.
"""
from __future__ import annotations

SPLIT_SEED: int = 20261025
SPLIT_METHOD: str = (
    "status-stratified systematic sampling over step-count order; first seed >= 20261024 "
    "such that every operation in the sample appears in dev and every operation present "
    "in >=3 sample cases appears in holdout"
)

DEV_IDS: frozenset[str] = frozenset({
    "case_01", "case_02", "case_03", "case_05", "case_07", "case_08", "case_09",
    "case_11", "case_12", "case_15", "case_16", "case_17", "case_18", "case_19",
    "case_20", "case_21", "case_22", "case_24", "case_26", "case_27", "case_30",
    "case_31",
})

HOLDOUT_IDS: frozenset[str] = frozenset({
    "case_04", "case_06", "case_10", "case_13", "case_14", "case_23", "case_25",
    "case_28", "case_29", "case_32",
})

assert len(DEV_IDS) == 22 and len(HOLDOUT_IDS) == 10 and not (DEV_IDS & HOLDOUT_IDS)
