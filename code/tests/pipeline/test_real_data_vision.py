"""T112 item 9 on the real inputs (no gold, no model call): a screenshot reading that transcribes
nothing never makes a row COMPLETE.

The G7 verifier's probe ``p4_vision_real.py agree`` gave every screenshot a reading that shows a record
ID with no subject, no marker and every state field ``not_shown``; the base engine turned three such
records into REDACTED / ANONYMIZED compliance claims and their rows COMPLETE (verifier finding 1).
This is the same attack as a property, with no hand-picked IDs: every screenshot, read twice through
GM's FakeTransport, shows every record that waits on an image (STATE_NEEDS_IMAGE in the engine-only
run), with nothing transcribed. No
row may be COMPLETE that the engine-only run (no readings) does not already give as COMPLETE.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from deletion_audit.agent.vision import image_files
from deletion_audit.engine import audit_all, build_context, build_world
from deletion_audit.pipeline import ModelSetup, run, run_vision

from ..agent._support import final_reply
from ._wiring import paid_setup

REPO = Path(__file__).resolve().parents[3]
DATASET = REPO / "dataset"


def bare(shown_id: str) -> dict[str, object]:
    """A record shown by its ID only: nothing transcribed, no marker, every state field not shown."""
    return {
        "shown_id": shown_id,
        "subject_emails": [],
        "subject_phones": [],
        "subject_names": [],
        "subject_user_ids": [],
        "sync_enabled": "not_shown",
        "restore_allowed": "not_shown",
        "marked_deleted": "not_shown",
        "download_available": "not_shown",
        "visible_markers": [],
        "status_label": "",
    }


def statuses(run_dir: Path) -> dict[str, str]:
    lines = (run_dir / "cases.jsonl").read_text(encoding="utf-8").splitlines()
    return {d["case_id"]: d["status"] for d in map(json.loads, lines)}


@unittest.skipUnless((DATASET / "deletion_requests.csv").is_file(), "the participant dataset is not present")
class NothingTranscribedNeverCompletes(unittest.TestCase):
    def test_bare_readings_make_no_row_complete(self) -> None:
        ctx = build_context(DATASET)
        w = build_world(ctx)
        cases = sorted(r.case_id for r in ctx.requests if r.source == "test")
        records = audit_all(ctx, cases, world=w)
        waiting = sorted(
            {
                x.key.resource_id
                for r in records.values()
                for x in r.resources
                if any(f.code == "STATE_NEEDS_IMAGE" for f in x.flags)
            }
        )
        self.assertTrue(waiting)
        reading = {"records": [bare(r) for r in waiting], "unreadable": [], "instruction_like_text": False}
        images = image_files(ctx)
        self.assertTrue(images)
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            cache = t / "replycache"
            script = [final_reply(reading)] * (2 * len(images))
            v = run_vision(DATASET, run_id="vis", model=paid_setup(cache, script), runs_dir=t / "rundirs")
            self.assertEqual(len(v["read_ok"]), len(images))
            run(
                DATASET, run_id="plain", cases="test", runs_dir=t / "rundirs", model=ModelSetup.replay(t / "emptycache")
            )
            run(DATASET, run_id="read", cases="test", runs_dir=t / "rundirs", model=ModelSetup.replay(cache))
            before, after = statuses(t / "rundirs" / "plain"), statuses(t / "rundirs" / "read")
        newly_complete = sorted(c for c, s in after.items() if s == "COMPLETE" and before.get(c) != "COMPLETE")
        self.assertEqual(newly_complete, [])


if __name__ == "__main__":
    unittest.main()
