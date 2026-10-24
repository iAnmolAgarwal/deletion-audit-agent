"""G2 Q3 summary: T4 stage counts per variant, deletion-authorized test cases only, DEV split by family.

Run: python3 -I notes/forensics/q3_summary.py [--run g2-0137]
Reads runs/<run>/acct_stages_*.json and runs/<run>/q1_q3.json (features). Family 'handbuilt' = the DEV input
signature found in q1_q3.py: non-round timestamps AND an account delete row within 10 min of reported_at whose
details are not the 'submitted primary profile' template. No case IDs are used as a signal.
"""
from __future__ import annotations
import argparse, json, sys
from collections import Counter, defaultdict
from pathlib import Path
RUNS = Path("/Users/anmolagarwal/hackerrank_orchestrate/october26/hackerrank-orchestrate-october26/runs")

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--run", default="g2-0137"); a = ap.parse_args()
    F = json.loads((RUNS / a.run / "q1_q3.json").read_text())["features"]
    fam = {c: ("handbuilt" if (not f["round_ts"] and f["row10"] and "other" in f["tmpl"]) else "generated") for c, f in F.items()}
    print("family counts:", Counter((F[c]["set"], fam[c], F[c]["authorized"]) for c in F))
    for p in sorted((RUNS / a.run).glob("acct_stages_*.json")):
        J = json.loads(p.read_text())["cases"]
        tag = p.stem.replace("acct_stages_", "")
        dev = defaultdict(lambda: [0, 0])
        for c, v in J.items():
            if v["set"] != "dev":
                continue
            k = (fam[c], v["stage"]); dev[k][0] += 1; dev[k][1] += bool(v["correct"])
        tst = Counter(v["stage"] for c, v in J.items() if v["set"] == "test" and F[c]["authorized"])
        picks = Counter(v["pick"] for c, v in J.items() if v["set"] == "test" and F[c]["authorized"] and v["pick"])
        dup = {r: n for r, n in picks.items() if n > 1}
        ties = Counter(v["tie_size"] for c, v in J.items() if v["set"] == "test" and F[c]["authorized"] and v["stage"] == "S5_flagged")
        print(f"## {tag}\n  DEV (family, stage): resolved/correct", {f"{k[0]}:{k[1]}": f"{n}/{ok}" for k, (n, ok) in sorted(dev.items())})
        print("  test authorized stages:", dict(sorted(tst.items())), " S5 tie sizes:", dict(ties),
              f" accounts picked by >1 test case: {len(dup)} ({sum(dup.values())} cases)")
main()
