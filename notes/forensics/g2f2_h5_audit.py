"""G2 follow-up 2, item 5 (report only): audit_record steps in DEV gold and how each is linked to its person.

Run: python3 -I notes/forensics/g2f2_h5_audit.py --run g2f2-HHMM
Writes runs/<run>/h5_audit.json.

For every DEV case (gold via devgold.py, holdout dropped before parsing): does gold have an audit_record step?
For each gold audit record: every evidence unit naming it, the identifier that links the unit to the request's
person (the matched value's type: user_id, current email, historical email, phone, email hash; and the field it sat
in), the unit's line time vs requested_at and audit_at, and the file's captured_at vs audit_at; activity rows that
name it; whether the case's cited file contains it.
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True
import argparse  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
from collections import Counter  # noqa: E402

sys.path.insert(0, "/Users/anmolagarwal/hackerrank_orchestrate/october26/hackerrank-orchestrate-october26/notes/forensics")
from g2f2_lib import RUNS, World, load_cases, resolve_email  # noqa: E402
from extract import ID_FIELDS  # noqa: E402


def id_type(p, v: str) -> str:
    cur = p.current
    if v == p.user_id.lower():
        return "user_id"
    if v == cur["email"].lower():
        return "email(current)"
    if v in p.emails:
        return "email(historical)"
    if v == cur["phone"].lower():
        return "phone(current)"
    if v in p.phones:
        return "phone(historical)"
    if v == cur["email_hash"].lower():
        return "email_hash(current)"
    if v in p.hashes:
        return "email_hash(historical)"
    return "other"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    a = ap.parse_args()
    cases, gold = load_cases()
    W = World()
    R: dict = {"cases": {}}
    dev = sorted((q for q in cases if q["_set"] == "dev"), key=lambda r: r["case_id"])
    summary = Counter()
    for q in dev:
        c = q["case_id"]
        g = gold[c]
        uid = resolve_email(q["email"], W.idx)
        p = W.people[uid]
        cites = sorted({s["evidence_id"] for s in g["steps"] if s["evidence_id"]})
        audits = [s for s in g["steps"] if s["resource_id"].startswith("audit_record_")]
        row = dict(status=g["status"], requested_at=q["requested_at"], audit_at=q["audit_at"], uid=uid,
                   n_audit_steps=len(audits), cited_files=cites, audit=[])
        for s in audits:
            rid = s["resource_id"]
            units = []
            for u in W.by_res.get(rid, []):
                matched = sorted(i for i in u.ids if W.idx.get(i) == uid)
                fields = sorted(k for k, v in u.attrs.items() if isinstance(v, str) and v.strip().lower() in matched)
                if matched and not fields:
                    fields = ["subject_reference (flat row)"] if u.kind.startswith("flat:") else (
                        ["trace-joined *_started line"] if u.kind.startswith("log:") else ["other"])
                cap = W.manifest[u.file_id]["captured_at"] if u.file_id else ""
                units.append(dict(file=u.file_id, file_captured=cap, kind=u.kind, line_ts=u.ts,
                                  matched=[f"{id_type(p, m)}" for m in matched], matched_fields=fields,
                                  linked_to_this_person=bool(matched),
                                  line_vs_requested=("before" if u.ts < q["requested_at"] else "at/after"),
                                  line_vs_audit=("at/before" if u.ts <= q["audit_at"] else "after"),
                                  file_vs_audit=("at/before" if cap and cap <= q["audit_at"] else "after"),
                                  in_cited_file=u.file_id in cites))
            acts = [(x["activity_id"], x["event_time"], x["event_type"], x["source_system"], x["target_system"])
                    for x in W.acts if x["resource_id"] == rid]
            linked_units = [x for x in units if x["linked_to_this_person"]]
            if not units:
                route = "in no input"
            elif any(x["file_vs_audit"] == "at/before" for x in linked_units):
                route = "identifier-linked line in a pre-audit file"
            elif any(x["line_vs_audit"] == "at/before" for x in linked_units):
                route = "identifier-linked pre-audit line inside a post-audit file (companion)"
            else:
                route = "other"
            summary[route] += 1
            row["audit"].append(dict(step=f"{s['phase']} {s['system_id']} {rid} {s['operation']} cite={s['evidence_id'] or '-'}",
                                     route=route, units=units, activity_rows=acts))
        R["cases"][c] = row
    R["summary"] = dict(
        dev_cases=len(dev),
        cases_with_audit_step=sum(1 for v in R["cases"].values() if v["n_audit_steps"]),
        cases_without_audit_step=sorted(c for c, v in R["cases"].items() if not v["n_audit_steps"]),
        audit_steps=sum(v["n_audit_steps"] for v in R["cases"].values()),
        routes=dict(summary),
        identifier_types=dict(Counter(m for v in R["cases"].values() for x in v["audit"] for u in x["units"] for m in u["matched"])),
        matched_fields=dict(Counter(f for v in R["cases"].values() for x in v["audit"] for u in x["units"] for f in u["matched_fields"])))
    # supplementary (inputs only): test cases whose person has an audit record linked ONLY by a line after audit_at
    from g2f2_lib import solve2, Hooks
    from solver import Opts
    post_only, pre_any, none_any = [], 0, 0
    for q in cases:
        if q["_set"] != "test":
            continue
        uid = resolve_email(q["email"], W.idx)
        if not uid or uid == "AMBIGUOUS":
            continue
        r = solve2(q, W, Opts(), Hooks())
        if r.status == "NOT_APPLICABLE":
            continue
        units = [u for u in W.units if uid in u.users and u.resource_id and u.resource_id.startswith("audit_record_")]
        pre = [u for u in units if q["requested_at"] <= u.ts <= q["audit_at"]]
        post = [u for u in units if u.ts > q["audit_at"]]
        if pre:
            pre_any += 1
        elif post:
            post_only.append(dict(case=q["case_id"], records=sorted({u.resource_id for u in post}),
                                  files=sorted({u.file_id for u in post})))
        else:
            none_any += 1
    R["test_supplement"] = dict(authorized_with_pre_audit_audit_link=pre_any,
                                authorized_with_post_audit_only_audit_link=len(post_only), post_only=post_only,
                                authorized_with_no_audit_link=none_any)
    (RUNS / a.run).mkdir(parents=True, exist_ok=True)
    (RUNS / a.run / "h5_audit.json").write_text(json.dumps(R, indent=1, default=str))
    print(json.dumps(R["summary"], indent=1))
    print(json.dumps({k: v for k, v in R["test_supplement"].items() if k != "post_only"}), R["test_supplement"]["post_only"][:12])
    for c, v in R["cases"].items():
        print(c, v["status"], "audit steps:", v["n_audit_steps"], "cited", v["cited_files"])
        for x in v["audit"]:
            print("   ", x["step"], "|", x["route"])
            for u in x["units"]:
                print("       ", u["file"], u["file_captured"][:16], u["kind"], "line", u["line_ts"][:16], "matched", u["matched"], u["matched_fields"],
                      "line", u["line_vs_audit"], "file", u["file_vs_audit"], "line-vs-req", u["line_vs_requested"], "in-cited", u["in_cited_file"])
            if x["activity_rows"]:
                print("        activity:", x["activity_rows"][:3])


if __name__ == "__main__":
    main()
