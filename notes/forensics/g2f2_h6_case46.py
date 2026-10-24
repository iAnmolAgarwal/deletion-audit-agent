"""G2 follow-up 2, item 6 (no rule change): the inputs around test case_46 and tombstone_17, for the open questions.

Run: python3 -I notes/forensics/g2f2_h6_case46.py --run g2f2-HHMM
Writes runs/<run>/h6_case46.json.

Raw byte search for 'tombstone_17' (word boundary) over every dataset file except sample_output.csv (holdout lock;
holdout rows of sample_deletion_requests.csv are dropped on their first CSV field before the search),
including PDF text layers; PNGs are listed only through the prototype's hand vision table (vision_facts.py).
Times are given relative to case_46's requested_at and audit_at. Also: the same person's other request (DEV case_17,
inputs and its DEV gold row only through devgold.py), and the prototype's row for case_46 with and without vision.
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True
import argparse  # noqa: E402
import json  # noqa: E402
import re  # noqa: E402

sys.path.insert(0, "/Users/anmolagarwal/hackerrank_orchestrate/october26/hackerrank-orchestrate-october26/notes/forensics")
from g2f2_lib import RUNS, DATASET, T, World, Hooks, solve2, load_cases, resolve_email  # noqa: E402
from solver import Opts, unit_state  # noqa: E402
from extract import pdf_text  # noqa: E402
from vision_facts import vision_units, FACTS  # noqa: E402

PAT = re.compile(r"\btombstone_17\b")
import devgold  # noqa: E402
HOLD = devgold.load_split()[1]


def rel(t: str, ref: str) -> str:
    d = (T(t) - T(ref)).total_seconds() / 86400
    return f"{d:+.2f} d"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    a = ap.parse_args()
    cases, gold = load_cases()
    W = World()
    Wv = World(vision_units=vision_units())
    q46 = next(q for q in cases if q["case_id"] == "case_46")
    q17 = next(q for q in cases if q["case_id"] == "case_17")
    R: dict = {}
    uid = resolve_email(q46["email"], W.idx)
    R["case_46_request"] = {k: q46[k] for k in ("requested_at", "reported_status", "reported_at", "audit_at")}
    R["case_46_person"] = uid
    R["same_person_dev_case_17"] = dict(person=resolve_email(q17["email"], W.idx),
                                        **{k: q17[k] for k in ("requested_at", "reported_at", "audit_at", "reported_status")},
                                        gold_status=gold["case_17"]["status"],
                                        gold_steps=[f"{s['phase']} {s['system_id']} {s['resource_id']} {s['operation']} {s['evidence_id'] or '-'}"
                                                    for s in gold["case_17"]["steps"]])
    hits = []
    for p in sorted(DATASET.rglob("*")):
        if not p.is_file() or p.name == "sample_output.csv" or p.suffix.lower() == ".png":
            continue
        try:
            text = pdf_text(p) if p.suffix.lower() == ".pdf" else p.read_text(encoding="utf-8", errors="ignore")
            if p.name == "sample_deletion_requests.csv":  # holdout inputs join H1 only: drop them on the first field
                text = "\n".join(l for l in text.splitlines() if l.split(",", 1)[0] not in HOLD)
        except Exception as e:  # explicit, never silent
            hits.append(dict(file=str(p.relative_to(DATASET)), error=type(e).__name__))
            continue
        for ln, line in enumerate(text.splitlines(), 1):
            if PAT.search(line):
                hits.append(dict(file=str(p.relative_to(DATASET)), line=ln, text=line[:220]))
    R["raw_hits_excluding_sample_output_and_png"] = hits
    R["vision_table_entries"] = [dict(file_id=f, system=s, rid=r, ids=sorted(i), attrs=at) for f, s, r, i, at in FACTS if r == "tombstone_17"]
    man = W.manifest
    for e in R["vision_table_entries"]:
        e["file_path"] = man[e["file_id"]]["file_path"]
        e["captured_at"] = man[e["file_id"]]["captured_at"]
        e["vs_case_46"] = dict(requested=rel(e["captured_at"], q46["requested_at"]), audit=rel(e["captured_at"], q46["audit_at"]))
    obs = []
    for Wx, tag in ((W, "novision"), (Wv, "vision")):
        for u in Wx.by_res.get("tombstone_17", []):
            obs.append(dict(world=tag, file=u.file_id, file_captured=(man[u.file_id]["captured_at"] if u.file_id else ""), kind=u.kind,
                            line_ts=u.ts, users=sorted(u.users), state=unit_state(u),
                            vs_case_46=dict(requested=rel(u.ts, q46["requested_at"]), audit=rel(u.ts, q46["audit_at"])),
                            vs_case_17=dict(requested=rel(u.ts, q17["requested_at"]), audit=rel(u.ts, q17["audit_at"]))))
    R["units"] = obs
    R["activity_rows"] = [dict(id=x["activity_id"], t=x["event_time"], type=x["event_type"], src=x["source_system"], dst=x["target_system"],
                               result=x["reported_result"], details=x["details"][:200],
                               vs_case_46=dict(requested=rel(x["event_time"], q46["requested_at"]), audit=rel(x["event_time"], q46["audit_at"])))
                          for x in W.acts if x["resource_id"] == "tombstone_17"]
    files_naming = sorted({h["file"] for h in hits if "file" in h})
    R["files_naming_it"] = dict(text_files=files_naming, png_via_vision_table=[e["file_id"] for e in R["vision_table_entries"]])
    for Wx, tag in ((W, "novision"), (Wv, "vision")):
        r = solve2(q46, Wx, Opts(), Hooks())
        R[f"prototype_row_case_46_{tag}"] = dict(status=r.status, F=r.trace.get("F"),
                                                steps=[f"{s['phase']} {s['system_id']} {s['resource_id']} {s['operation']} {s['evidence_id'] or '-'}" for s in r.steps],
                                                notes=r.trace.get("notes"))
    (RUNS / a.run).mkdir(parents=True, exist_ok=True)
    (RUNS / a.run / "h6_case46.json").write_text(json.dumps(R, indent=1, default=str))
    print(json.dumps(R, indent=1, default=str))


if __name__ == "__main__":
    main()
