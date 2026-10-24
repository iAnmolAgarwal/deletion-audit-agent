"""G2 follow-up 2, baselines.

Run: python3 -I notes/forensics/g2f2_baseline.py --run g2f2-HHMM
Writes runs/<run>/baseline.json.

1. Harness check: g2f2_lib.solve2 with no hooks equals the prototype's solver.solve on all 540 DEV+test cases,
   without and with the hand vision table.
2. Row/step/field baseline: the prototype DEV replay (must equal g2-q2_reconcile-0137: 22/22, 20/22, 132/134, 908/938).
3. Account baseline: T4 + T26 + T27 + T28 + T29 (AcctEngine defaults; scope DEV+test, holdout inputs excluded,
   S5 = one-to-one matching, ties ordered by requested_at then lower-case email). S1..S4b are compared with the first
   run's saved acct_stages_base.json. Then the baseline's DEV rows (solve2 with the baseline accounts injected
   where they differ from the prototype's) are scored and diffed against the prototype replay.
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True
import argparse  # noqa: E402
import json  # noqa: E402
from collections import Counter  # noqa: E402

sys.path.insert(0, "/Users/anmolagarwal/hackerrank_orchestrate/october26/hackerrank-orchestrate-october26/notes/forensics")
from g2f2_lib import (RUNS, World, AcctEngine, AcctOpts, Hooks, solve2, check_harness, row_diff,  # noqa: E402
                      gold_account, load_cases)
from solver import Opts  # noqa: E402
from score import aggregate, score_case  # noqa: E402
from vision_facts import vision_units  # noqa: E402


def dev_rows(W, cases, gold, hk=None):
    rows, res = [], {}
    for q in sorted((c for c in cases if c["_set"] == "dev"), key=lambda r: r["case_id"]):
        r = solve2(q, W, Opts(), hk or Hooks())
        res[q["case_id"]] = r
        g = gold[q["case_id"]]
        sc = score_case(r.status, r.steps, g["status"], g["steps"])
        sc["case_id"] = q["case_id"]
        sc["exact"] = sc["status_ok"] and sc["steps_ok"]
        rows.append(sc)
    return aggregate(rows), rows, res


def proto_account(r) -> list[str]:
    return sorted({s["resource_id"] for s in r.steps if s["system_id"] == "account_service"})


def engine_hooks(W, cases, picks: dict, eng: AcctEngine, proto: dict) -> Hooks:
    """Inject the engine's account wherever it differs from the prototype's; T27 picks are cited ''."""
    acc, rows, empty = {}, {}, set()
    for c, p in picks.items():
        if c not in proto or proto[c].status == "NOT_APPLICABLE":
            continue
        if p["stage"] == "S1_identifier":
            continue  # same rule as the prototype (identifier link)
        pa = proto_account(proto[c])
        if [p["pick"]] == pa or (p["pick"] is None and not pa):
            continue
        acc[c] = p["pick"]
        rows[c] = eng.info[c]["pick_row"]
        if p["stage"] == "T27_narrowC":
            empty.add((c, p["pick"]))
    return Hooks(accounts=acc, account_rows=rows, empty_cite=empty)


def stage_table(picks, gold, sets=("dev", "test")) -> dict:
    out = {}
    for s in sets:
        cs = [c for c, p in picks.items() if p["set"] == s and p["auth"]]
        st = Counter(picks[c]["stage"] for c in cs)
        row = dict(n=len(cs), stages=dict(sorted(st.items())))
        pk = Counter(picks[c]["pick"] for c in cs if picks[c]["pick"])
        dup_people = {}
        for c in cs:
            if picks[c]["pick"]:
                dup_people.setdefault(picks[c]["pick"], set()).add(picks[c]["person"])
        row["accounts_on_two_people"] = sorted(k for k, v in dup_people.items() if len(v) > 1)
        row["accounts_on_two_cases"] = sorted(k for k, v in pk.items() if v > 1)
        if s == "dev":
            row["correct_by_stage"] = {k: f"{sum(1 for c in cs if picks[c]['stage'] == k and picks[c]['pick'] in gold_account(gold[c]))}/{st[k]}"
                                       for k in sorted(st)}
        row["flags"] = dict(Counter(f for c in cs for f in picks[c]["flags"]))
        out[s] = row
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    a = ap.parse_args()
    out_dir = RUNS / a.run
    out_dir.mkdir(parents=True, exist_ok=True)
    cases, gold = load_cases()
    W = World()
    Wv = World(vision_units=vision_units())
    R: dict = {}
    R["harness_check_novision"] = check_harness(W, cases)
    R["harness_check_vision"] = check_harness(Wv, cases)
    agg, rows, proto_dev = dev_rows(W, cases, gold)
    R["prototype_dev_replay"] = dict(agg, inexact=[r["case_id"] for r in rows if not r["exact"]])
    exp = dict(status_exact=22, case_exact=20, step_tp=132, step_gold=134, step_pred=132, field_hits=908, field_slots=938,
               res_tp=74, res_gold=76)
    for k, v in exp.items():
        assert agg[k] == v, (k, agg[k], v)

    # account baseline
    eng = AcctEngine(W, cases, AcctOpts())
    picks = eng.picks()
    R["account_baseline"] = stage_table(picks, gold)
    R["account_baseline_conflicts"] = eng.conflicts
    # S1..S4b reproduction vs the first run (stage names differ only where T26..T29 act)
    J = json.loads((RUNS / "g2-0137" / "acct_stages_base.json").read_text())["cases"]
    same, diffs = 0, []
    for c, p in picks.items():
        js, jp = J[c]["stage"], J[c]["pick"]
        if js in ("S1_identifier", "S2_timed_unique", "S3_one_to_one", "S4_d17", "S4b_one_to_one_after_d17"):
            if (js, jp) == (p["stage"], p["pick"]):
                same += 1
            else:
                diffs.append((c, js, jp, p["stage"], p["pick"]))
    R["s1_s4b_vs_g2-0137"] = dict(same=same, differ=diffs)
    assert not diffs, diffs[:5]
    # where T26..T29 changed the first run's result
    ch = []
    for c, p in picks.items():
        js, jp = J[c]["stage"], J[c]["pick"]
        if (js, jp) != (p["stage"], p["pick"]):
            ch.append(dict(case=c, set=p["set"], auth=p["auth"], first_run=(js, jp), baseline=(p["stage"], p["pick"]),
                           flags=p["flags"]))
    R["t26_t29_changes_vs_first_run"] = dict(
        dev=[x for x in ch if x["set"] == "dev"],
        test_authorized=len([x for x in ch if x["set"] == "test" and x["auth"]]),
        test_by_kind=dict(Counter(f'{x["first_run"][0]} -> {x["baseline"][0]}' for x in ch if x["set"] == "test" and x["auth"])),
        test_cases=sorted((x["case"] for x in ch if x["set"] == "test" and x["auth"]), key=lambda s: int(s[5:])))
    # NA excluded: same authorized picks?
    eng_na = AcctEngine(W, cases, AcctOpts(na="exclude"))
    pna = eng_na.picks()
    R["na_exclude_changes_authorized_picks"] = sorted(c for c in pna if (pna[c]["stage"], pna[c]["pick"]) != (picks[c]["stage"], picks[c]["pick"]))
    # baseline DEV rows
    proto_all = {q["case_id"]: solve2(q, W, Opts(), Hooks()) for q in cases}
    hk = engine_hooks(W, cases, picks, eng, proto_all)
    agg_b, rows_b, base_dev = dev_rows(W, cases, gold, hk)
    R["account_baseline_dev_rows"] = dict(agg_b, inexact=[r["case_id"] for r in rows_b if not r["exact"]],
                                          injected=sorted(c for c in hk.accounts if c in base_dev))
    R["account_baseline_dev_row_diffs_vs_prototype"] = {c: row_diff(proto_dev[c], base_dev[c]) for c in base_dev
                                                       if row_diff(proto_dev[c], base_dev[c])}
    # baseline test rows vs prototype (no vision), counts only
    tchg = []
    for q in cases:
        if q["_set"] != "test" or q["case_id"] not in hk.accounts:
            continue
        r2 = solve2(q, W, Opts(), hk)
        if row_diff(proto_all[q["case_id"]], r2):
            tchg.append(q["case_id"])
    R["account_baseline_test_rows_changed_vs_prototype"] = dict(n=len(tchg), cases=sorted(tchg, key=lambda s: int(s[5:])))
    (out_dir / "baseline.json").write_text(json.dumps(R, indent=1, default=str))
    print(json.dumps(R, indent=1, default=str)[:12000])


if __name__ == "__main__":
    main()
