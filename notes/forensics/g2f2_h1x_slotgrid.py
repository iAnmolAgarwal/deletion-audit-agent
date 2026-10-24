"""G2 follow-up 2, cross-check of H1 x H2 (outside H1's wording, which names the 30-s grid): does the per-slot mod-60
band (H2) split account candidates that the 30-s band cannot?

Run: python3 -I notes/forensics/g2f2_h1x_slotgrid.py --run g2f2-HHMM
Writes runs/<run>/h1x_slotgrid.json.

Grid forms for D17 own-row fit (g2f2_lib.AcctEngine.fits): band30 (prototype), slot (policy rows must sit in their
slot's measured mod-60 band; after rows keep band30), slotpm (slot parity +-1 s).
1. Baseline (T4 + T26..T29) and H1 (V1) under each grid: stage counts, picks that change, DEV correctness.
2. Full-mask pseudo-label test on the inputs: identifier links hidden (mask_s1) and the owner filter off; the label is
   the identifier-linked account (no gold). The slot bands were measured on these same S1 jobs, so a label fitting is
   in-sample; the informative number is how many WRONG candidates each grid rejects (the tie-breaks it gets right).
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True
import argparse  # noqa: E402
import json  # noqa: E402
from collections import Counter  # noqa: E402
from dataclasses import replace  # noqa: E402

sys.path.insert(0, "/Users/anmolagarwal/hackerrank_orchestrate/october26/hackerrank-orchestrate-october26/notes/forensics")
from g2f2_lib import RUNS, World, AcctEngine, AcctOpts, gold_account, load_cases, load_holdout_inputs  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    a = ap.parse_args()
    cases, gold = load_cases()
    hold = load_holdout_inputs()
    W = World()
    R: dict = {}
    base = AcctOpts()
    h1 = replace(base, scope="batch", d17="qualify", with_holdout_inputs=True)
    P = {}
    for name, o, reqs in (("V0", base, cases), ("V1_H1", h1, cases + hold)):
        for g in ("band30", "slot", "slotpm"):
            e = AcctEngine(W, reqs, replace(o, grid=g))
            p = e.picks()
            P[(name, g)] = p
            row = {}
            for s in ("dev", "test", "holdout"):
                cs = [c for c, x in p.items() if x["set"] == s and x["auth"]]
                row[s] = dict(stages=dict(sorted(Counter(p[c]["stage"] for c in cs).items())))
                if s == "dev":
                    row[s]["correct"] = sum(1 for c in cs if p[c]["pick"] in gold_account(gold[c]))
            R[f"{name}|{g}"] = row
    for name in ("V0", "V1_H1"):
        p0 = P[(name, "band30")]
        for g in ("slot", "slotpm"):
            p1 = P[(name, g)]
            ch = [dict(case=c, set=p0[c]["set"], before=(p0[c]["stage"], p0[c]["pick"]), after=(p1[c]["stage"], p1[c]["pick"]))
                  for c in p0 if p0[c]["set"] in ("dev", "test") and p0[c]["auth"] and p0[c]["pick"] != p1[c]["pick"]]
            R[f"{name}|{g}|picks_changed_vs_band30"] = dict(n=len(ch), dev=[x for x in ch if x["set"] == "dev"],
                                                           test=[x for x in ch if x["set"] == "test"])
    # full-mask pseudo-label test
    for mode in ("tiebreak", "qualify"):
        for g in ("band30", "slot", "slotpm"):
            o = replace(base, mask_s1=True, owner=False, d17=mode, grid=g)
            e = AcctEngine(W, cases, o)
            st = Counter()
            for c, d in e.info.items():
                if d["q"]["_set"] != "test" or not e.auth[c] or not d["il_label"]:
                    continue
                ok = d["pick"] == d["il_label"][0]
                st[(d["stage"], ok)] += 1
            dev = Counter()
            for c, d in e.info.items():
                if d["q"]["_set"] == "dev" and d["il_label"]:
                    dev[(d["stage"], d["pick"] in gold_account(gold[c]))] += 1
            R[f"fullmask|{mode}|{g}"] = dict(
                test={k: f"{st[(k, True)]}/{st[(k, True)] + st[(k, False)]}" for k in sorted({k for k, _ in st})},
                dev={k: f"{dev[(k, True)]}/{dev[(k, True)] + dev[(k, False)]}" for k in sorted({k for k, _ in dev})})
    (RUNS / a.run).mkdir(parents=True, exist_ok=True)
    (RUNS / a.run / "h1x_slotgrid.json").write_text(json.dumps(R, indent=1, default=str))
    for k, v in R.items():
        if k.endswith("vs_band30"):
            print(k, "n=", v["n"], [ (x["case"], x["before"], x["after"]) for x in v["test"]][:40])
        else:
            print(k, json.dumps(v))


if __name__ == "__main__":
    main()
