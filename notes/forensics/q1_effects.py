"""G2 Q1: DEV effect of the no-candidate options on steps and fields (prototype output, account step removed or kept).

Run: python3 -I notes/forensics/q1_effects.py
For each DEV case where the T4 timed rule finds no candidate (01, 02, 07, 08 in run g2-0137), score the prototype's
prediction (a) as is (= options that pick the gold account) and (b) with the account step dropped and step_no
renumbered (= options that find no account). Status is re-derived from the steps.
"""
import json, sys
sys.path.insert(0, "/Users/anmolagarwal/hackerrank_orchestrate/october26/hackerrank-orchestrate-october26/notes/forensics")
from common import RUNS, World, load_cases
from solver import Opts, solve, validate
from score import score_case
W = World(); cases, gold = load_cases()
J = json.loads((RUNS / "g2-0137" / "acct_stages_base.json").read_text())["cases"]
for q in sorted((c for c in cases if c["_set"] == "dev" and J[c["case_id"]]["stage"] == "NONE"), key=lambda r: r["case_id"]):
    res = solve(q, W, Opts()); g = gold[q["case_id"]]
    keep = score_case(res.status, res.steps, g["status"], g["steps"])
    drop_steps = [dict(s) for s in res.steps if s["system_id"] != "account_service"]
    for i, s in enumerate(drop_steps):
        s["step_no"] = i + 1
    st = "INCOMPLETE" if any(s["phase"] == "FINDING" for s in drop_steps) else "COMPLETE"
    res.steps, res.status = drop_steps, st
    errs = validate(res)
    drop = score_case(st, drop_steps, g["status"], g["steps"])
    print(q["case_id"], "keep: exact", keep["status_ok"] and keep["steps_ok"], "steps", keep["step_tp"], "/", keep["step_gold"], "fields", keep["field_hits"], "/", keep["field_slots"],
          "| drop: status_ok", drop["status_ok"], "steps", drop["step_tp"], "/", drop["step_gold"], "fields", drop["field_hits"], "/", drop["field_slots"], "validator", errs)
