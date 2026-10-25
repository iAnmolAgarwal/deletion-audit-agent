# Resume point (updated 2026-10-25 ~16:50 IST)

Durable state: `notes/DECISIONS.md` (T1–T126), `log.txt`, `code/approved` → now `notes/approved/` + `notes/approved_output.json`.
Scratchpad = `/private/tmp/claude-501/-Users-anmolagarwal-hackerrank-orchestrate-october26-hackerrank-orchestrate-october26/a5e12cbe-b80b-4f4f-8569-6ab18d22f35c/scratchpad/`.

## Shipped state (do not change without the developer)
- **Shipped output:** root `output.csv` = `runs/cand-test-Aplus-20261025T1352/output.csv`, sha256 `a00ba71a756736cc09a3ef5119b5575d871a2db2c9482d9829333181d5676967` (T120). Every change must replay it byte-identical at 0 sends and keep engine-only DEV `641dbc8d…` / test `cf2a90b0…`.
- **Freeze:** tag `freeze-20261025` = `bca55eb` (pushed). Freeze run `freeze-test-Aplus-20261025T1629`.
- **Holdout (done once, T124):** `holdout-20261025T1628`: status 9/10, rows exact 8/10, step F1 0.974, 18 sends, $0.197868.
- **Reports:** published from `code/evaluation/specs/reports_final.json` (repo-relative); ledger `code/evaluation/improvements.json`.
- **Upload files:** `~/Desktop/oct26_final/` — `code.zip` sha256 `79001ea011d8245e7128c3c8d544e640327444f6178bb2d695c909a797acd196` (from `8568391`), `output.csv` `a00ba71a…`, each with a `.sha256` file.
- **Spend:** ledger total about $15.46 (pass ≈ $13.94 + holdout $0.20 + stage 1 $1.31).
- HEAD after T126 records: see `git log` (last code commit 8568391; later commits are docs/log only).

## Running now (T125 / T126)
- `orch-verifier` (high), directed_by 2026-10-25T16:36:10+05:30, read-only on the upload set: claims vs code, replay from the freeze tag, log completeness. Report only; a BLOCKER goes to the developer.
- `orch-judge` (xhigh), directed_by 2026-10-25T16:42:15+05:30, read-only on the same set (unzipped at scratchpad `judge2/upload`): code score /30 (architecture /9, prompt+tools /9, robustness /7.5, rigor /4.5), output and transcript reads, findings ranked with QUICK marks, over-engineering read.

## Next (T126), after both report
1. One fix round for the judge's QUICK high-value items only, by `orch-builder-core` (high), directed_by 2026-10-25T16:42:15+05:30. Constraints: output.csv byte-identical; engine-only hashes unchanged; both suites pass; nothing touching model requests (prompts, schemas, tool defs/descriptions, tool-result content, EngineBrief.for_model, request builders) or changing a row. Its report lists every code change made after the holdout, with commit.
2. If code changed: a fresh `orch-verifier` (high) on just that diff; then rebuild code.zip (`git archive HEAD` → `zip -qr code.zip README.md code -x "*/__pycache__/*" "*/.venv/*" "*/venv/*" "*/node_modules/*" "*/.git/*" "*/.DS_Store"`), secret-pattern scan, fresh-unzip README command (`python -B code/main.py --run-id demo --set test` → cf2a90b0), replace `~/Desktop/oct26_final/` files with sha256.
3. One short message: the judge's estimate, top findings, what was fixed, the verifier's verdict.

## Rules easy to forget
- Every turn: a log.txt entry by Bash append only; summary 2–5 sentences; check_log after.
- No line starting with "## [" in briefs; a `directed_by` line in every brief; never two agents of one type at once.
- Commits: stage only the paths at hand; secret scan; push to `github`. Never read `.env` into the shell.
- Holdout gold stays locked (the one run is done).
