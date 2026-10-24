"""G2 Q7: input signals that might separate the true account ties left after T4 stages 1-4 (S5 flagged cases).

Run: python3 -I notes/forensics/q7_ties.py [--run g2-0137]
Reads runs/<run>/acct_stages_base.json and q1_q3.json; writes runs/<run>/q7.json. Inputs only (test + DEV);
DEV has no S5 case in the base order, so nothing here has DEV support (stated in the report).
Signals counted per S5 case: why D17 did not separate; whether the request text carries digits (phone
fragments); whether the case's other linked resources share a region/system with a candidate's evidence;
whether candidates have any evidence observation at all; candidate delete-row second offsets.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter

sys.path.insert(0, "/Users/anmolagarwal/hackerrank_orchestrate/october26/hackerrank-orchestrate-october26/notes/forensics")
from common import RUNS, T, World, account_delete_rows, load_cases, off_min  # noqa: E402
from identity import resolve_email  # noqa: E402


def region_of(u) -> set:
    out = set()
    for k in ("region", "source_region", "replica_region"):
        v = u.attrs.get(k)
        if isinstance(v, str) and v:
            out.add(v)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="g2-0137")
    a = ap.parse_args()
    W = World()
    cases, _ = load_cases()
    J = json.loads((RUNS / a.run / "acct_stages_base.json").read_text())["cases"]
    F = json.loads((RUNS / a.run / "q1_q3.json").read_text())["features"]
    ADR = account_delete_rows(W)
    qs = {q["case_id"]: q for q in cases}
    S = Counter()
    rows = []
    for c, v in J.items():
        if v["stage"] != "S5_flagged" or not F[c]["authorized"]:
            continue
        q = qs[c]
        rep = T(q["reported_at"])
        uid = resolve_email(q["email"], W.idx)
        want = {"COMPLETE": "SUCCESS", "PARTIALLY_COMPLETE": "PARTIAL", "NOT_STARTED": "FAILED"}[q["reported_status"]]
        cands = [r for r in ADR if -75 <= off_min(r, rep) <= -44 and r["reported_result"] == want
                 and not (W.res_users.get(r["resource_id"], set()) - {uid})]
        own_units = [u for u in W.units if uid in u.users and q["requested_at"] <= u.ts <= q["audit_at"]]
        own_regions = set().union(*[region_of(u) for u in own_units]) if own_units else set()
        info = []
        for r in cands:
            ev = W.by_res.get(r["resource_id"], [])
            regs = set().union(*[region_of(u) for u in ev]) if ev else set()
            info.append(dict(rid=r["resource_id"], sec=round(off_min(r, rep) * 60 % 60, 1), n_ev=len(ev),
                             files=sorted({u.file_id for u in ev if u.file_id}), regions=sorted(regs),
                             region_overlap=bool(regs & own_regions)))
        digits = bool(re.search(r"\d{3,}", q["request_text"]))
        S["d17:" + str(v["d17"]).split(" ")[0]] += 1
        S["request_text_has_3plus_digits"] += digits
        S["own_units_in_window"] += bool(own_units)
        n_ev = sum(1 for i in info if i["n_ev"])
        S[f"candidates_with_evidence={n_ev}/{len(info)}"] += 1
        ov = sum(1 for i in info if i["region_overlap"])
        if ov == 1:
            S["region_overlap_unique"] += 1
        same_sec = len({i["sec"] for i in info}) < len(info)
        S["candidates_share_second_offset"] += same_sec
        rows.append(dict(case=c, d17=v["d17"], digits=digits, own_regions=sorted(own_regions), cands=info))
    (RUNS / a.run / "q7.json").write_text(json.dumps(dict(summary=S, rows=rows), indent=1))
    print(json.dumps(S, indent=1))
    for r in rows[:6]:
        print(r)


if __name__ == "__main__":
    main()
