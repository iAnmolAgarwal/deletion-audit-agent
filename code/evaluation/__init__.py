"""Evaluation package: holdout-locked gold loading, scoring, coherence and run artifacts.

Modules:
    paths       repository paths, derived from this file's location
    split       the locked DEV / holdout split (mirror of notes/split.json)
    contract    the output contract tables (operations, phases, statuses, step keys)
    gold        the dev-filtered gold loader (holdout rows dropped before JSON parsing)
    outputs     reading and writing output.csv files
    scorer      case, row, step, field, sequence, citation and resource metrics
    coherence   structural checks on any output file (reports, never fixes)
    drift       predicted distributions against DEV gold distributions
    discrimination  majority baseline and perturbed-gold checks that the scorer moves
    runs        run directory artifacts (config hash, flips, README)
    numbers_md  regenerates the generated block of NUMBERS.md from run artifacts
    evaluate    the command-line entry point
"""
