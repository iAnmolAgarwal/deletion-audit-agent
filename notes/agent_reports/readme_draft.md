# README draft report (orch-packager, low)

directed_by 2026-10-25T11:55:27+05:30 (T102). Main's check: `notes/ORGANISER_README.md` is byte-identical to the committed README (`git show HEAD:README.md | cmp`); the DRAFT banner is present; D18_TIE_PICK 27 and T27_LATER_IDENTITY_LOOKUP 6 in `g5-test-20261025T0530` match the draft. For G10: the DEV 19/22 citation uses `g5-dev-iter3-score`, while the canonical G5 run is `g5-dev22-20261025T0530`. Saved verbatim from the agent's final message.

---

I've written the draft README and copied the organiser's original. One thing doesn't fit the record yet: the "I personally reviewed" list names four checkpoints that have no `log.txt` entries so far.

I followed the brief in `readme_brief.md`, which asks for a README draft. I did not run the packaging checks from my standing instructions (the `output.csv` checks, `code.zip`, the secret scan, the trace dry-run), so there is no PASS/FAIL table.

**Files**
- `/Users/anmolagarwal/hackerrank_orchestrate/october26/hackerrank-orchestrate-october26/notes/ORGANISER_README.md` is a verbatim copy of the organiser's README; `cmp` found no differences.
- `/Users/anmolagarwal/hackerrank_orchestrate/october26/hackerrank-orchestrate-october26/README.md` is the new draft. It starts with the required DRAFT line.

**Sections and sources**
1. **How it works:** from `notes/SYSTEM.md`, the T-numbers in `notes/DECISIONS.md` and the module layout under `code/deletion_audit/`. The agent and vision wiring (G7) is marked "in progress", because `pipeline.py` makes no model calls today: every case's intent takes the fail-closed path and the 11 screenshots are skipped as `png-model-needed`.
2. **How to run:** from `--help` and the `__main__.py` docstring, which I checked. The test and lint commands are copied from the brief; I did not run them. No paid call was made and `.env` was not read.
3. **How this was built:** sourced from `log.txt` and `PLAYBOOK.md` §11, item I1. The four checkpoints are the policy module, the validator, the agent loop and tools, and one end-to-end case trace. Since none of them is logged yet, the draft lists them and says G10 adds their timestamps.
4. **Limitations:**
   - T27: the 6 showcase cases tied only by a later log line. The count comes from the flag `T27_LATER_IDENTITY_LOOKUP`, run `g5-test-20261025T0530`.
   - T39: 27 coin-flip tie picks, from the flag `D18_TIE_PICK` in the same run. That run predates G7, so the figure is labelled pre-G7.
   - T53 / D17: generator timing.
   - T60 (3): the identity guard cannot recognise an edited copy of the gold file.
   - The holdout caveat, from the `created` field in `notes/split.json`.
   - DEV 19/22 exact, from run `g5-dev-iter3-score` in `NUMBERS.md`, accepted in T58.
   - The holdout unlock phrase is a constant in the source, from `notes/HOLDOUT_RUN_PROPOSAL.md`.
5. **Reports:** says both reports are not generated yet and points to `NUMBERS.md`.

**Claims I could not tie to code or a ruling, so left out or flagged**
- **The four review checkpoints:** no `log.txt` entry exists for any of them.
- **"I chose":** the only evidence in `log.txt` is the provenance line in the SESSION START entry, which Claude wrote, not the developer. No User Prompt section in the build log shows the developer choosing the method or the three posts in their own words; that choice happened in the prep session. The README cites the SESSION START entry and does not quote the developer.
- **Approval of the roster, tiers and hook (D4c):** this is also only in the SESSION START provenance line, as kit items the prep session drafted. No approval timestamp is in this log.
- **Rows exact:** the account-step loss on case_08 comes from T58. The draft says the 3 lost rows "include" it and does not explain the other two.

**`log.txt` timestamps used**
- `2026-10-25T00:00:30+05:30` (SESSION START)
- `2026-10-24T23:59:53+05:30` (first developer turn)
- `2026-10-25T00:20:00+05:30` (G0, where the hook was installed)

My log entry is appended, and `python3 -I scripts/check_log.py` returned PASS with 0 blocking entries.
