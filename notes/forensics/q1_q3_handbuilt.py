"""G2 Q1 options and Q3 'hand-built' basis, on DEV (holdout dropped) and the 518 test inputs.

Run: python3 -I notes/forensics/q1_q3_handbuilt.py [--run g2-0137]
Reads runs/<run>/acct_stages_base.json (from acct_stages.py) and writes runs/<run>/q1_q3.json.

Features (inputs only; nothing keyed on case IDs, file names or row positions):
  round_ts   : requested_at, reported_at and audit_at all at minute 00, second 00.
  row10      : an account delete row with |offset| <= 10 min of reported_at.
  tmpl       : the template of that row's details text ("submitted primary profile" vs other).
  padded     : the row10 account id has a 3-digit zero-padded suffix (account_0NN).
Options for cases where the timed rule finds no candidate:
  O1 +-10 min fallback, result-matched only.
  O2 +-10 min fallback, result-matched first, else any result (reopens a T4 'not shipped' item).
  O3 user-owned account at any time: an account identifier-linked to the user in any line
     (including lines after audit_at) or owning a delete row at any time.
  O4 deterministic flagged pick among all unowned account delete rows in [-75,+10] min.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter

sys.path.insert(0, "/Users/anmolagarwal/hackerrank_orchestrate/october26/hackerrank-orchestrate-october26/notes/forensics")
from common import RUNS, T, World, STATUS_TO_RESULT, account_delete_rows, gold_account, id_linked_accounts, load_cases, off_min  # noqa: E402
from identity import resolve_email  # noqa: E402
from intent import authorizes_deletion  # noqa: E402


def round_ts(s: str) -> bool:
    return s[14:19] == "00:00"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="g2-0137")
    a = ap.parse_args()
    W = World()
    cases, gold = load_cases()
    ADR = account_delete_rows(W)
    J = json.loads((RUNS / a.run / "acct_stages_base.json").read_text())["cases"]
    feats, opts = {}, {}
    for q in cases:
        c = q["case_id"]
        uid = resolve_email(q["email"], W.idx)
        rep = T(q["reported_at"])
        want = STATUS_TO_RESULT[q["reported_status"]]
        ok, _ = authorizes_deletion(q["request_text"])
        r10 = [r for r in ADR if abs(off_min(r, rep)) <= 10]
        r10u = [r for r in r10 if not (W.res_users.get(r["resource_id"], set()) - {uid})]
        rt = all(round_ts(q[k]) for k in ("requested_at", "reported_at", "audit_at"))
        tm = sorted({("submit" if "submitted primary profile" in r["details"] else "other") for r in r10})
        pad = any(re.fullmatch(r"account_0\d\d", r["resource_id"]) for r in r10)
        feats[c] = dict(set=q["_set"], authorized=ok, round_ts=rt, row10=bool(r10), row10_unowned=bool(r10u),
                        tmpl=tm, padded=pad, stage=J[c]["stage"])
        if J[c]["stage"] != "NONE":
            continue
        o1 = [r["resource_id"] for r in r10u if r["reported_result"] == want]
        o2 = o1 or [r["resource_id"] for r in r10u]
        own_any = sorted(id_linked_accounts(W, uid, q, "any") |
                         {r["resource_id"] for r in ADR if uid in W.res_users.get(r["resource_id"], set())})
        wide = [r for r in ADR if -75 <= off_min(r, rep) <= 10 and not (W.res_users.get(r["resource_id"], set()) - {uid})]
        wide.sort(key=lambda r: (r["reported_result"] != want, abs(off_min(r, rep) + 60)))
        o4 = [wide[0]["resource_id"]] if wide else []
        g = gold_account(gold[c]) if q["_set"] == "dev" else None
        opts[c] = dict(set=q["_set"], authorized=ok, gold=g, O1=o1, O2=o2[:1] if len(o2) == 1 else o2, O3=own_any, O4=o4,
                       reason=J[c]["reason"])
    (RUNS / a.run / "q1_q3.json").write_text(json.dumps(dict(features=feats, options=opts), indent=1))

    print("== Q3 feature cross-tab (authorized cases only)")
    for s in ("dev", "test"):
        rows = [f for f in feats.values() if f["set"] == s and f["authorized"]]
        ct = Counter((f["round_ts"], f["row10"], tuple(f["tmpl"]), f["padded"]) for f in rows)
        print(f"  {s} n={len(rows)}  (round_ts, row10, row10_templates, padded_id): count")
        for k, v in sorted(ct.items(), key=lambda x: -x[1]):
            print("    ", k, v)
    print("  DEV cases with row10:", sorted(c for c, f in feats.items() if f["set"] == "dev" and f["row10"]))
    print("  DEV cases not round_ts:", sorted(c for c, f in feats.items() if f["set"] == "dev" and not f["round_ts"]))
    print("  test authorized cases with row10:", sorted((c for c, f in feats.items() if f["set"] == "test" and f["row10"] and f["authorized"]), key=lambda x: int(x[5:])))
    print("  test authorized not round_ts:", sorted((c for c, f in feats.items() if f["set"] == "test" and not f["round_ts"] and f["authorized"]), key=lambda x: int(x[5:])))
    print("== Q1 options on no-candidate cases")
    for c, o in sorted(opts.items(), key=lambda x: (x[1]["set"], int(x[0][5:]))):
        print("  ", c, o)
    for opt in ("O1", "O2", "O3", "O4"):
        dv = [o for o in opts.values() if o["set"] == "dev"]
        right = sum(1 for o in dv if len(o[opt]) == 1 and o[opt][0] in o["gold"])
        wrong = sum(1 for o in dv if len(o[opt]) == 1 and o[opt][0] not in o["gold"])
        none_ = sum(1 for o in dv if len(o[opt]) == 0)
        multi = sum(1 for o in dv if len(o[opt]) > 1)
        tt = [o for o in opts.values() if o["set"] == "test" and o["authorized"]]
        touched = sum(1 for o in tt if o[opt])
        print(f"  {opt}: DEV right {right} wrong {wrong} none {none_} multi {multi} | test authorized touched {touched}/{len(tt)}")


if __name__ == "__main__":
    main()
