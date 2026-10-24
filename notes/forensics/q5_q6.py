"""G2 Q5 (UNEXPLAINED gold values) and Q6 (T9 provisional defaults, G1 ambiguities) on DEV.

Run: python3 -I notes/forensics/q5_q6.py [--run g2-0137]
Writes runs/<run>/q5_q6.json. Gold via devgold (holdout dropped before parsing). Raw-byte search skips
sample_output.csv entirely (it is gold, and holds holdout rows).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import zlib
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, "/Users/anmolagarwal/hackerrank_orchestrate/october26/hackerrank-orchestrate-october26/notes/forensics")
from common import DATASET, RUNS, T, World, load_cases  # noqa: E402
from extract import pdf_text  # noqa: E402
from identity import resolve_email  # noqa: E402
from solver import Opts, solve, unit_state  # noqa: E402
from score import aggregate, score_case  # noqa: E402


def raw_search(needles: list[str]) -> dict:
    hits = defaultdict(list)
    for p in DATASET.rglob("*"):
        if not p.is_file() or p.name == "sample_output.csv":
            continue
        b = p.read_bytes()
        blobs = [b]
        if p.suffix.lower() == ".pdf":
            for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", b, re.S):
                try:
                    blobs.append(zlib.decompress(m.group(1)))
                except Exception:
                    pass
            try:
                blobs.append(pdf_text(p).encode())
            except Exception as e:
                hits["_pdf_errors"].append(f"{p.name}:{type(e).__name__}")
        for n in needles:
            if any(n.encode() in x for x in blobs):
                hits[n].append(str(p.relative_to(DATASET)))
    return dict(hits)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="g2-0137")
    a = ap.parse_args()
    W = World()
    cases, gold = load_cases()
    dev = sorted((c for c in cases if c["_set"] == "dev"), key=lambda r: r["case_id"])
    R = {}
    # Q5: re-check truth-only IDs (bare numbers too)
    R["raw"] = raw_search(["audit_record_6645", "audit_record_5569", "6645", "5569"])
    # every DEV gold resource: is it in any input unit/activity row at all?
    act_res = {x["resource_id"] for x in W.acts}
    absent = []
    for q in dev:
        for s in gold[q["case_id"]]["steps"]:
            r = s["resource_id"]
            if r not in W.by_res and r not in act_res:
                absent.append((q["case_id"], r))
    R["gold_resources_in_no_input"] = sorted(set(absent))
    # citation: does the cited file name the resource it is cited for?
    cite = []
    for q in dev:
        for s in gold[q["case_id"]]["steps"]:
            if s["evidence_id"]:
                fu = [u for u in W.file_units.get(s["evidence_id"], []) if u.resource_id == s["resource_id"]]
                if not fu:
                    cite.append((q["case_id"], s["resource_id"], s["evidence_id"]))
    R["cited_file_does_not_name_resource"] = cite
    # Q6: T9 defaults
    uids = {q["case_id"]: resolve_email(q["email"], W.idx) for q in dev}
    t9 = {}
    # (a) support records in DEV gold: what the observation shows
    sup = []
    for q in dev:
        c = q["case_id"]
        p = W.people[uids[c]]
        ids = p.emails | p.phones
        for s in gold[c]["steps"]:
            if s["system_id"] == "support_platform" and s["phase"] != "REMEDIATION":
                obs = W.by_res.get(s["resource_id"], [])
                txt = " ".join(str(u.attrs.get("message_text", "")) for u in obs)
                sup.append(dict(case=c, rid=s["resource_id"], op=s["operation"],
                                kinds=sorted({u.kind for u in obs})[:4],
                                own_id_in_text=any(i and i in txt.lower() for i in ids),
                                requester_fields=sorted({k for u in obs for k in u.attrs if k.startswith("requester") and u.attrs[k] not in (None, "", "null")}),
                                shared_ctx=bool(re.search(r"order|agent|ORD-|courier|parcel", txt, re.I))))
    t9["support"] = sup
    # (b) tombstones / legal holds / backups / flows linked (any time) to DEV users, vs gold
    fam = defaultdict(list)
    for q in dev:
        c = q["case_id"]
        gres = {s["resource_id"] for s in gold[c]["steps"]}
        for u in W.units:
            if uids[c] in u.users and u.system in ("identity_service", "legal_service") and u.resource_id:
                fam[u.system].append((c, u.resource_id, u.ts, u.file_id or u.attrs.get("activity_id"), unit_state(u),
                                      "IN_GOLD" if u.resource_id in gres else "not_in_gold",
                                      "in_window" if q["requested_at"] <= u.ts <= q["audit_at"] else "outside_window"))
    t9["tombstone_legal_links"] = {k: sorted(set(v)) for k, v in fam.items()}
    legal_rows = [x for x in W.acts if x["target_system"] == "legal_service"]
    t9["legal_rows_users"] = sorted({(x["resource_id"], tuple(sorted(W.res_users.get(x["resource_id"], set())))) for x in legal_rows})
    # (c) compliant non-finding verifications in INCOMPLETE gold, by system
    comp = Counter()
    for q in dev:
        g = gold[q["case_id"]]
        if g["status"] != "INCOMPLETE":
            continue
        fres = {s["resource_id"] for s in g["steps"] if s["phase"] == "FINDING"}
        for s in g["steps"]:
            if s["phase"] == "VERIFICATION" and s["resource_id"] not in fres:
                comp[(s["system_id"], s["operation"])] += 1
    t9["incomplete_compliant_verifications"] = {f"{k[0]}|{k[1]}": v for k, v in comp.items()}
    # (d) audit retention vs audit_at for DEV gold audit records
    ret = []
    for q in dev:
        for s in gold[q["case_id"]]["steps"]:
            if s["system_id"] == "security_service":
                rs = sorted({str(u.attrs.get(k)) for u in W.by_res.get(s["resource_id"], []) for k in u.attrs if "retain" in k or "retention" in k})
                ret.append((q["case_id"], s["resource_id"], rs, q["audit_at"]))
    t9["audit_retention"] = ret
    # A7 / R3: lower bound of the discovery window (requested_at) vs none
    for name, o in (("lower_requested_at", Opts()), ("no_lower_bound", Opts(discovery_lower=None))):
        rows = []
        for q in dev:
            res = solve(q, W, o)
            g = gold[q["case_id"]]
            sc = score_case(res.status, res.steps, g["status"], g["steps"])
            sc["case_id"] = q["case_id"]
            rows.append(sc)
        ag = aggregate(rows)
        R[f"A7_{name}"] = dict(case_exact=ag["case_exact"], extra=[(r["case_id"], r["step_extra"]) for r in rows if r["step_extra"]])
    R["t9"] = t9
    (RUNS / a.run / "q5_q6.json").write_text(json.dumps(R, indent=1, default=str))
    print(json.dumps(R, indent=1, default=str)[:9000])


if __name__ == "__main__":
    main()
