"""G2 Q5: does a DEV gold audit-record number equal another resource number in a co-batched case (same reported_at)?

Run: python3 -I notes/forensics/q5_suffix.py. Tests hypothesis H2 for the two truth-only audit IDs against the
base rate over all DEV gold audit records that do appear in the inputs. Inputs-only link sets (identifier links
in [requested_at, audit_at]) are used for the co-batched cases, so holdout gold is never touched.
"""
import re, sys
from collections import defaultdict
sys.path.insert(0, "/Users/anmolagarwal/hackerrank_orchestrate/october26/hackerrank-orchestrate-october26/notes/forensics")
from common import World, load_cases
from identity import resolve_email
W = World(); cases, gold = load_cases()
by_rep = defaultdict(list)
for q in cases:
    by_rep[q["reported_at"]].append(q)
def linked(q):
    uid = resolve_email(q["email"], W.idx)
    return {u.resource_id for u in W.units if uid in u.users and u.resource_id and q["requested_at"] <= u.ts <= q["audit_at"]}
num = lambda r: (re.search(r"(\d+)$", r) or [None, None])[1]
hits = tot = 0
for q in (c for c in cases if c["_set"] == "dev"):
    for s in gold[q["case_id"]]["steps"]:
        if s["system_id"] != "security_service":
            continue
        n = num(s["resource_id"])
        peers = [p for p in by_rep[q["reported_at"]] if p["case_id"] != q["case_id"]]
        peer_res = set().union(*[linked(p) for p in peers]) if peers else set()
        own = linked(q) - {s["resource_id"]}
        m_peer = sorted(r for r in peer_res if num(r) == n)
        m_own = sorted(r for r in own if num(r) == n)
        in_inputs = s["resource_id"] in W.by_res
        tot += in_inputs; hits += in_inputs and bool(m_peer or m_own)
        print(q["case_id"], s["resource_id"], "in_inputs" if in_inputs else "TRUTH-ONLY", "peers", len(peers), "peer-match", m_peer, "own-match", m_own)
print(f"base rate among in-input audit records: {hits}/{tot} share their number with a co-batched or own resource")
