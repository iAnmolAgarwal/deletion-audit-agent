"""G2 follow-up 2, hypothesis 4: support category from the deletion worker's action when no attachment cue is visible.

Run: python3 -I notes/forensics/g2f2_h4_support.py --run g2f2-HHMM
Writes runs/<run>/h4_support.json.

Attachment cue = the prototype's category() cues (attachment_pii_scan, ticket_attachments, record_type
SUPPORT_ATTACHMENT, an 'attachment' or 'file' attribute, a customer PDF). Rule under test: when no cue is visible,
a support record whose deletion-worker rows are all DELETE_RECORD is an attachment (rule_06 DELETE); all
REDACT_RECORD is a message (rule_05 REDACT); none or mixed keeps the prototype default (message).
Forms: cue at any time (prototype) vs cue <= audit_at; worker rows at any time, <= audit_at, or inside the case's
template windows (its job).
1. Input cross-tab: cue category x worker action over every support resource (no gold).
2. DEV agreement: gold category (DELETE ops = attachment, REDACT ops = message) vs worker action, per DEV support step.
3. Row effects: solve2 (prototype rules and accounts, vision table on test) with the hook vs without.
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True
import argparse  # noqa: E402
import json  # noqa: E402
from collections import Counter, defaultdict  # noqa: E402

sys.path.insert(0, "/Users/anmolagarwal/hackerrank_orchestrate/october26/hackerrank-orchestrate-october26/notes/forensics")
from g2f2_lib import RUNS, World, Hooks, solve2, row_diff, load_cases, category  # noqa: E402
from solver import Opts  # noqa: E402
from score import aggregate, score_case  # noqa: E402
from vision_facts import vision_units  # noqa: E402  (hand table; test-side counts, as report 15 sec 6)

NAMED = ["case_251", "case_347", "case_443"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    a = ap.parse_args()
    cases, gold = load_cases()
    W = World()
    Wv = World(vision_units=vision_units())
    R: dict = {}
    dwact = defaultdict(set)
    for x in Wv.acts:
        if x["source_system"] == "deletion_worker" and x["resource_id"].startswith("support_"):
            dwact[x["resource_id"]].add(x["event_type"])
    rids = {u.resource_id for u in Wv.units if u.resource_id and u.resource_id.startswith("support_")} | set(dwact)
    tab = Counter()
    targets = []
    for rid in sorted(rids):
        cat = category("support_platform", Wv.by_res.get(rid, [])) if rid in Wv.by_res else "NO_EVIDENCE"
        act = "+".join(sorted(dwact.get(rid, ()))) or "none"
        tab[f"{cat} x {act}"] += 1
        if cat == "SUPPORT_MESSAGE" and act == "DELETE_RECORD":
            targets.append(rid)
    R["input_crosstab_cue_category_x_worker_action"] = dict(tab)
    R["no_cue_delete_resources"] = targets
    # DEV agreement
    dev = sorted((q for q in cases if q["_set"] == "dev"), key=lambda r: r["case_id"])
    agree = []
    for q in dev:
        for s in gold[q["case_id"]]["steps"]:
            if s["system_id"] != "support_platform" or s["phase"] != "VERIFICATION":
                continue
            rid = s["resource_id"]
            ops = {x["operation"] for x in gold[q["case_id"]]["steps"] if x["resource_id"] == rid}
            gcat = "ATTACHMENT(delete)" if ops & {"DELETE_RECORD", "VERIFY_RECORD_ABSENT"} else "MESSAGE(redact)"
            cue_pre = category("support_platform", [u for u in W.by_res.get(rid, []) if u.ts <= q["audit_at"]])
            acts = sorted(dwact.get(rid, ()))
            wcat = {"DELETE_RECORD": "ATTACHMENT(delete)", "REDACT_RECORD": "MESSAGE(redact)"}.get("+".join(acts), "none")
            agree.append(dict(case=q["case_id"], rid=rid, gold=gcat, cue_le_audit=cue_pre, worker=acts, worker_category=wcat,
                              worker_agrees=(wcat == gcat) if wcat != "none" else None))
    R["dev_agreement"] = dict(rows=agree, worker_rows_present=sum(1 for x in agree if x["worker_agrees"] is not None),
                              agree=sum(1 for x in agree if x["worker_agrees"]),
                              disagree=sum(1 for x in agree if x["worker_agrees"] is False),
                              no_cue_rows=sum(1 for x in agree if x["cue_le_audit"] == "SUPPORT_MESSAGE"),
                              no_cue_and_worker_delete=sum(1 for x in agree if x["cue_le_audit"] == "SUPPORT_MESSAGE" and x["worker"] == ["DELETE_RECORD"]))
    # row effects
    base_dev = {q["case_id"]: solve2(q, W, Opts(), Hooks()) for q in dev}
    base_test = {q["case_id"]: solve2(q, Wv, Opts(), Hooks()) for q in cases if q["_set"] == "test"}
    forms = {}
    for cue in ("any", "pre"):
        for wf in ("any", "pre", "job"):
            hk = Hooks(support_cat="worker", cue_form=cue, worker_form=wf)
            sc, devchg = [], {}
            for q in dev:
                r = solve2(q, W, Opts(), hk)
                g = gold[q["case_id"]]
                s = score_case(r.status, r.steps, g["status"], g["steps"])
                s["exact"] = s["status_ok"] and s["steps_ok"]
                s["case_id"] = q["case_id"]
                sc.append(s)
                d = row_diff(base_dev[q["case_id"]], r)
                if d:
                    devchg[q["case_id"]] = d
            ag = aggregate(sc)
            tch, named, flips = [], {}, Counter()
            for q in cases:
                if q["_set"] != "test":
                    continue
                r = solve2(q, Wv, Opts(), hk)
                d = row_diff(base_test[q["case_id"]], r)
                if d:
                    tch.append(q["case_id"])
                    if base_test[q["case_id"]].status != r.status:
                        flips[f"{base_test[q['case_id']].status}->{r.status}"] += 1
                if q["case_id"] in NAMED:
                    named[q["case_id"]] = dict(before=[f"{s['phase']} {s['resource_id']} {s['operation']}" for s in base_test[q["case_id"]].steps if s["system_id"] == "support_platform"],
                                               after=[f"{s['phase']} {s['resource_id']} {s['operation']}" for s in r.steps if s["system_id"] == "support_platform"],
                                               status=(base_test[q["case_id"]].status, r.status))
            forms[f"cue_{cue}|worker_{wf}"] = dict(dev_case_exact=ag["case_exact"], dev_step_tp=ag["step_tp"], dev_field_hits=ag["field_hits"],
                                                  dev_row_changes=devchg, test_cases_changed=len(tch), test_status_flips=dict(flips),
                                                  test_cases=sorted(tch, key=lambda s: int(s[5:])), named=named)
    R["forms"] = forms
    (RUNS / a.run).mkdir(parents=True, exist_ok=True)
    (RUNS / a.run / "h4_support.json").write_text(json.dumps(R, indent=1, default=str))
    print(json.dumps(R, indent=1, default=str)[:9000])


if __name__ == "__main__":
    main()
