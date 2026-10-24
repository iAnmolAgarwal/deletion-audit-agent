"""G2 follow-up, task 5a: the actual wording of the account delete row behind the 'hand-built' label.

Run: python3 -I -B notes/forensics/f5_handbuilt_wording.py [--run g2f-0152]
Writes runs/<run>/f5_handbuilt_wording.json. Inputs only (no gold). DEV (22, holdout dropped) + test (518).

The first run's table (q1_q3_handbuilt.py) split the +-10-min row's wording into two classes only: 'submit'
("submitted primary profile") and 'other', and the report printed 'other' as "reported the requested operation...".
Here the wording is classified by its full template, with the account ID masked:
  submit    : "Deletion worker submitted primary profile <id> to account_service."
  completed : "Deletion worker reported the requested operation as completed. Target resource: <id>."
  internal  : "Deletion worker completed some internal work but could not confirm the final state. Target resource: <id>."
Feature definitions (applied to every case alike; nothing keyed on case IDs, files or row positions):
  round_ts : requested_at, reported_at and audit_at all at mm:ss = 00:00.
  rowW     : an account delete row (DELETE_RECORD, target account_service) with |offset| <= W min of reported_at.
  padded   : that row's account ID is account_0NN (3-digit zero-padded).
Hand-built forms:
  HB_literal   : not round_ts, row10 with wording 'completed' only (the report's printed wording).
  HB_corrected : not round_ts, row10 with wording 'completed' OR 'internal' (= not 'submit'; the script's real test).
  HB_wording   : row10 with non-submit wording, timestamps ignored.
  HB_wording_W : the same for W in {5, 10, 15, 30, 60, 120} min.
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True
import argparse  # noqa: E402
import json  # noqa: E402
import re  # noqa: E402
from collections import Counter  # noqa: E402

sys.path.insert(0, "/Users/anmolagarwal/hackerrank_orchestrate/october26/hackerrank-orchestrate-october26/notes/forensics")
from common import RUNS, T, World, account_delete_rows, load_cases, off_min  # noqa: E402
from intent import authorizes_deletion  # noqa: E402


def wording(details: str) -> str:
    if "submitted primary profile" in details:
        return "submit"
    if "reported the requested operation as completed" in details:
        return "completed"
    if "completed some internal work but could not confirm the final state" in details:
        return "internal"
    return "UNCLASSIFIED"


def round_ts(s: str) -> bool:
    return s[14:19] == "00:00"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="g2f-0152")
    a = ap.parse_args()
    W = World()
    cases, _ = load_cases()
    ADR = account_delete_rows(W)
    R: dict = {}
    R["account_delete_rows_by_wording"] = dict(Counter(wording(r["details"]) for r in ADR))
    R["wording_by_result"] = {f"{k[0]}|{k[1]}": v for k, v in
                              Counter((wording(r["details"]), r["reported_result"]) for r in ADR).items()}
    R["templates_masked"] = sorted({re.sub(r"account_\d+", "<id>", r["details"]) for r in ADR})
    per_case = {}
    for q in cases:
        rep = T(q["reported_at"])
        ok, _ = authorizes_deletion(q["request_text"])
        rows10 = [r for r in ADR if abs(off_min(r, rep)) <= 10]
        per_case[q["case_id"]] = dict(
            set=q["_set"], authorized=ok, round_ts=all(round_ts(q[k]) for k in ("requested_at", "reported_at", "audit_at")),
            rows10=[dict(activity_id=r["activity_id"], resource_id=r["resource_id"], offset_min=round(off_min(r, rep), 2),
                         result=r["reported_result"], wording=wording(r["details"]), details=r["details"]) for r in rows10],
            padded=any(re.fullmatch(r"account_0\d\d", r["resource_id"]) for r in rows10),
            nonsubmit_within={str(w): any(wording(r["details"]) != "submit" for r in ADR if abs(off_min(r, rep)) <= w)
                              for w in (5, 10, 15, 30, 60, 120)})
    # DEV rows printed in full (the correction)
    R["dev_rows10"] = {c: v["rows10"] for c, v in per_case.items() if v["set"] == "dev" and v["rows10"]}

    def count(pred):
        out = {}
        for s, auth_only in (("dev", False), ("test", True), ("test", False)):
            key = f"{s}{'_authorized' if auth_only else '_all'}"
            hits = [c for c, v in per_case.items() if v["set"] == s and (v["authorized"] or not auth_only) and pred(v)]
            out[key] = dict(n=len(hits), cases=sorted(hits, key=lambda x: int(x[5:])) if s == "dev" or len(hits) <= 20 else None)
        return out

    w10 = lambda v: {r["wording"] for r in v["rows10"]}  # noqa: E731
    R["HB_literal"] = count(lambda v: not v["round_ts"] and "completed" in w10(v))
    R["HB_corrected"] = count(lambda v: not v["round_ts"] and bool(w10(v) - {"submit"}))
    R["HB_wording"] = count(lambda v: bool(w10(v) - {"submit"}))
    for w in (5, 10, 15, 30, 60, 120):
        R[f"HB_wording_{w}"] = count(lambda v, w=w: v["nonsubmit_within"][str(w)])
    # the first run's 4-feature cross-tab, re-done with the 3-way wording (authorized cases)
    ct = Counter()
    for c, v in per_case.items():
        if not v["authorized"]:
            continue
        ct[(v["set"], v["round_ts"], bool(v["rows10"]), tuple(sorted(w10(v))), v["padded"])] += 1
    R["crosstab_authorized"] = [dict(set=k[0], round_ts=k[1], row10=k[2], wording=list(k[3]), padded=k[4], n=n)
                                for k, n in sorted(ct.items(), key=lambda x: (x[0][0], -x[1]))]
    # where do the non-submit rows sit relative to DEV and test reported_at? (no holdout row is read)
    ns = [r for r in ADR if wording(r["details"]) != "submit"]
    place = Counter()
    for r in ns:
        near_dev = any(abs(off_min(r, T(q["reported_at"]))) <= 10 for q in cases if q["_set"] == "dev")
        near_test = any(abs(off_min(r, T(q["reported_at"]))) <= 10 for q in cases if q["_set"] == "test")
        place["dev" if near_dev else ("test" if near_test else "neither_dev_nor_test")] += 1
    R["nonsubmit_rows_within_10min_of"] = dict(place)
    R["per_case_dev"] = {c: v for c, v in per_case.items() if v["set"] == "dev"}
    RUNS.joinpath(a.run).mkdir(parents=True, exist_ok=True)
    (RUNS / a.run / "f5_handbuilt_wording.json").write_text(json.dumps(R, indent=1))
    show = {k: v for k, v in R.items() if k not in ("per_case_dev",)}
    print(json.dumps(show, indent=1))


if __name__ == "__main__":
    main()
