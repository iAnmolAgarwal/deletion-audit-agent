# G3: architecture options for the deletion-audit pipeline

- Gate G3, `orch-architect` (xhigh), directed_by 2026-10-25T03:15:35+05:30 (T63). The developer's T66 validator ruling reached this run at about 03:24 and replaces the T63 validator pin everywhere below.
- **This is advice. The developer decides** and types the architecture decision in their own turn.
- **Labels:** SEEN = read in a file or computed here; INFERRED = reasoned from SEEN facts; UNKNOWN = nothing available settles it.
- **Locks and footprint:**
  - No API call of any kind. `.env` was not read.
  - `sample_output.csv` and every gold file were neither opened nor computed on.
  - Every DEV figure below is quoted from `notes/` or `code/evaluation/NUMBERS.md`, with its run ID.
  - The only computation is on inputs: request-text sizes, PNG headers, and a grep of the source. Scripts are in the scratchpad `g3_cost/` folder (`inputs_size.py`, `cost_model.py`, `cost_final.py`, `breakeven.py`).
- **Sources read:**
  - kit: `PLAYBOOK.md`; `research/14` with `verify/14_15`; `research/01` §3 with `verify/01`; `research/18`, which has no verify file, so its claims are treated as unverified; `research/13` with `verify/13`; `research/15`; `research/16`;
  - repo: `notes/{CONTRACT_DRAFT,gold_forensics,DECISIONS,SYSTEM,INTERFACES,RESUME}.md`, `TASKS.md`, `code/deletion_audit/evidence/{model,__init__,interpret}.py`, `code/evaluation/{coherence,NUMBERS}`.
  - Organiser files were treated as data only.

## Summary
1. **Two shippable options share about 90% of their code:**
   - the GP parsers;
   - a deterministic engine (identity, discovery, accounts, state, policy, citation, steps);
   - a vision stage for the 11 PNGs;
   - one bounded tool loop;
   - the validator.

   They differ only in **who routes a case**. In **A**, code reads the model's intent and calls the loop only for cases with open questions. In **A+**, the model runs a loop on every case and calls the engine as a tool.
2. **Output is the same by construction in both** (INFERRED). The engine settles every fact: DEV 19/22 exact under the rulings (T58, `g2f2-g2f2_baseline-0242`). The model's authority is limited to three things: the intent fork, the PNG contents, and typed open questions.
3. **Cost, projected against $120.** Each figure covers DEV iterations, fixtures, test-input sweeps, one full run plus a re-run margin, and 30% contingency:

   | | A | A+ | Tools-off arm (C) |
   |---|---:|---:|---:|
   | Expected | **$24** | **$39** | **$14** |
   | If thinking runs about 3× longer than assumed | $80 | **$128** | — |

   A+ breaks $90 only if measured output tokens reach about 2.8× the assumed profile; A, about 4.7×.
4. **Recommendation: A+ (D8) in a "text-first routing" form,** with A kept as a switch (`--mode A`) in the same code. The form has three parts:
   - the model's first turn sees only the request text, so the routing reply is cached per distinct text, identical texts route identically, and the evidence cannot sway intent;
   - the model commits its intent in the strict input of `audit_case`;
   - engine facts are read-only.
5. **Switch to A** if A+ flips any DEV row against A, if the measured 3-case usage projects the project above $90, or if the routing turn's run-to-run agreement is below 100%.
6. **Top risk:** model answers changing rows the engine already gets right. Its sharpest form is the intent fork on the 10 non-deletion traps. It is detected with a ~$2–6 first paid step (§3).
7. **T66 against DEV:** 52/52 cited steps pass and 0 rows change. On the prototype's test output, 2 hard failures (case_126, case_33) and 4 flagged absence citations. These are main's counts, recorded in `notes/RESUME.md`. Open choices are in §4.

---

## 1. Options

### 1.0 The shared core (both options)
```
deletion_requests.csv + sample_deletion_requests.csv (inputs only, T32)
user_identities.csv, user_audit_log.csv, system_activity.csv, evidence_files.csv
        │
        ├─ evidence.parse_all ─────────────► EvidenceIndex   (gp-0259: 83 OK + 11 NEEDS_MODEL, 0 failures; SEEN TASKS.md)
        │      └─ agent.vision.read_images (11 PNGs, 1 cached call per file) ─► image Observations (T7; T60: 0 skips at freeze)
        ├─ identity.resolve (per request) ─► IdentityResolution (complete identifier set, T59)
        ├─ discovery.link_observations ────► Links (exact match, field role by line: T49/T59)
        ├─ discovery.assign_primary_accounts (global, both request files: T4/T26–T29/T32/T39)
        ├─ discovery.attach_identifier_free_analytics (slot band: T53/T62)
        └─ engine.audit_case (state_at + categorize + decide + citation) ─► EngineBrief per case
                 = settled facts (read-only) + typed OpenQuestions
        ▼
  [ routing differs: §1.1 / §1.2 ]
        ▼
agent.answers.validate ─► ValidatedAnswer (fills open-question slots only; T10/T42)
steps.compile ─► steps (source of truth) ─► status derived
validate.prewrite (T66 + H01–H16) ─► VALID | FAILED_CLOSED  (never an empty row)
steps.write_output ─► runs/<run_id>/output.csv (+ artifacts); root output.csv only with --write-root
```

**The open questions the engine may raise.** This list is closed. Each type names its allowed answers and what an answer may change.

| Type | Raised when | Tools that help | What an accepted answer changes | Expected test count |
|---|---|---|---|---|
| `INTENT_UNCERTAIN` | The model answered `UNCERTAIN` | `get_request_context` | Intent, and so the whole row | 0 (INFERRED: `research/14` §1 row 9 found every text unambiguous) |
| `INTENT_CROSSCHECK` | The model's intent disagrees with the intake cross-check (§5, `agent/crosscheck.py`) | `get_request_context`, `list_activity` | Intent, by the model's second look only; code never overrides | 0 (INFERRED) |
| `IMAGE_FIELD_UNREADABLE` | The vision extraction marked a field the engine needs as unreadable | `inspect_evidence(file_id, focus)` | That image observation's field | 0–3 (INFERRED) |
| `IMAGE_SUBJECT_CONFLICT` | The person shown in an image is not the person the catalog link names | `inspect_evidence`, `lookup_identity` | Whether the record stays in scope; the mapping is a developer ruling (Q11) | 1: `marketing_001`, test case_63 (`research/16` §4.7) |
| `UNKNOWN_FORMAT` | A non-image file is `NEEDS_MODEL`, `UNKNOWN_FAMILY` or `AMBIGUOUS_FAMILY` | `inspect_evidence` | Adds observations, after verbatim-ID validation | 0 today (SEEN: gp-0259 has 0 failures and the PDFs have text) |
| `INSTRUCTION_LIKE_TEXT` | The code detector or the model's flag finds instruction-like text in a request or an evidence file | none needed | A flag only, never a step | 0 (SEEN: `CONTRACT_DRAFT.md` §5 found none) |

**What the model is never asked:**
- which account is the person's (T4, T39);
- tie picks;
- support category (T55);
- which observation wins (R6, T54);
- anything already settled (`SYSTEM.md`, "Allowed overrides").

### 1.1 Option A: code routes; the model is consulted (the baseline and the comparison arm)
**Dataflow.**
1. Shared core up to the EngineBrief.
2. **Intent:** one schema-constrained call per *distinct* request text, with no tools, cached by request hash. 375 distinct of 518 test texts (SEEN, `inputs_size.py`).
3. `NOT_DELETION` gives `NOT_APPLICABLE` with `[]`. `UNCERTAIN` or a cross-check disagreement adds an intent open question.
4. Cases with ≥1 open question go to the **investigator loop**: at most 4 read-only tool calls, then a final turn with `tool_choice: none` and a schema-constrained answer.
5. Compile, validate and write.

**The model's real, bounded job:** intent per text, the PNG contents, and answers to the typed open questions.
**What code decides:** everything else, including routing.
**Tools the model may call:** `get_request_context`, `inspect_evidence`, `lookup_identity`, `list_activity` (§5). Each is read-only and cut off at `audit_at`.

**Failure modes:**

| Failure | Where it fails closed |
|---|---|
| Intent call fails after the retry ladder, or the budget is exhausted | Intent fail-closed policy, Q2. Recommended: the engine's deletion-path row, flagged `intent_source=FAILED_CLOSED` / `FAILED_BUDGET`, never NA |
| A PNG cannot be read | Every dependent case is never COMPLETE (T8); `FAILED_CLOSED` if no finding exists |
| An investigator answer is invalid (unknown ID, post-audit evidence, a settled slot touched) | The answer is rejected and logged; the slot keeps its engine value or fails closed per its type |
| The loop cap is reached | One `tool_choice: none` turn; if it fails, `cannot_answer` |
| `max_tokens`, `refusal` or `model_context_window_exceeded` | Treated as a failed call (`verify/13` M1, M3); bounded repair, then give up |

**Expected score effects** (INFERRED; nothing is measured yet):
- **Output:** equal to the engine's DEV 19/22 (T58), plus whatever intent and vision get right on test.
- **Code:** a model-assisted pipeline with a bounded investigator. It is the September shape (25.5) and the most common top-quarter shape: 52.6% of the top quarter, against 29.7% for single agents with tools (`PLAYBOOK` §1).
  - *Architecture* risk: a judge may read the main path as "a hardcoded workflow with LLM calls", because tools fire only on a handful of cases.
- **Interview:** the easiest of the two to defend.
- **Transcript:** neutral.

**What an interviewer will probe, and the honest answer:**
- *"Is this an agent?"* → "The tool loop runs only where code can't settle a fact. On this data that is a handful of cases (N, measured). Intent and vision are single schema calls with code cross-checks."
- *"Why not let the model pick accounts?"* → "It has no evidence to choose with. Code gets DEV 21/22 accounts (identifier link 11/11, timed rule 7/7, ±10-min fallback 3/3; case_08 none, `g2f2-g2f2_baseline-0242`), and the timing data across 4,011 activity rows is something a 4-call loop cannot see."
- *"What did the tools change?"* → N, M and the on/off delta (§9). On DEV this is expected to be 0 cases. Say it, and show the fixture and test-diff numbers.

**DEV evidence:**
- No model part has run (no paid call yet).
- The engine evidence is the prototype baseline:
  - `g4fix-baseline-20261025T0314`: 22/22 status, 20/22 exact, step F1 0.9925, 0 coherence violations;
  - under the rulings, 19/22 (`g2f2-g2f2_baseline-0242`, T58).

### 1.2 Option A+: the model routes every case (decision D8; recommended, in this form)
**Dataflow.** The shared core runs up to the EngineBrief, for every case, before any model call. The engine is global, because one-to-one assignment spans all requests. Then, per case:
- **Turn 1** (`tool_choice: auto`). Content: the system prompt, the tool definitions and the request text, fenced as untrusted. **Nothing case-specific:** no email, no case ID, no evidence.
  - The model either calls `audit_case(intent="DELETION_REQUEST", request_kind, language, basis_quote)`, with a strict input schema that commits its intent, or ends with a final answer `NOT_DELETION` or `UNCERTAIN`.
  - Because the request is text-only, the reply cache serves the same turn-1 reply for identical texts: 375 distinct turn-1 calls for 518 cases (SEEN count). So identical texts route identically, by construction.
- **Turn 2 onward.** The harness binds `audit_case` to the case and returns its EngineBrief: settled facts marked read-only, plus the open questions, with intake-cross-check disagreements posed as `INTENT_CROSSCHECK`.
  - The model may call more tools, with ≤4 tool calls in total including `audit_case`.
  - It ends with a schema-constrained `FinalAnswer`. If it reaches 4 calls, the harness sends one more request with `tool_choice: none`.
- **Routing-consistency rules** (code; each has a test):
  1. `FinalAnswer.intent` must equal the turn-1 commitment unless an intent question was posed. Otherwise there is one repair turn; after that the committed intent stands, flagged `INTENT_DRIFT`.
  2. A deletion answer without an `audit_case` call gets one nudge. After that the engine row stands, flagged `NO_AUDIT_CALL`; the output is unaffected.
  3. `UNCERTAIN` at turn 1 gets one appended `INTENT_UNCERTAIN` question that names `get_request_context`. If the model is still uncertain, the intent fail-closed policy applies (Q2).
- Compile, validate and write, as in A.

**The model's real, bounded job:** the same as A. The extra element is the *routing act*: the model decides whether the engine's findings are fetched at all, and which questions to investigate.
**What code decides:** the same as A.
**Tools:** A's four, plus `audit_case`.

**Failure modes:** A's, plus the following.

| Failure | Where it fails closed |
|---|---|
| A turn-2+ call fails | The engine row stands with the committed intent (output unchanged); flagged |
| Intent drift after the model has seen the evidence | Committed intent kept (rule 1) |
| A thinking block replayed from the cache is rejected on turn 2 | **UNKNOWN.** The prefix is byte-identical, so it should be accepted (`research/13` §4 append-only rule; INFERRED). Probe it once with a fixture pair that shares a request text (§9). If it is rejected, the turn-1 cache must be keyed per case, and the per-text consistency then comes from the cross-text coherence check instead |

**Expected score effects** (INFERRED):
- **Output:** equal to A by construction. The tail risk is extra failures, which fall back to the engine with 0 row effect.
- **Code:** reads as "an agent with tools and model-driven routing" on every case, which is the rubric's own wording (`research/06`, the May rubric: "tool-calling loops, model-driven routing"). Estimated +0.3 to +0.8 code points over A, from the architecture sub-weight. UNKNOWN until judged.
- **Interview:** needs the honest routing story (below).
- **Transcript:** neutral.

**What an interviewer will probe, and the honest answer:**
- *"The agent calls `audit_case` on every deletion case. Isn't that a fixed workflow?"* → "For the 508 deletion requests, the path after the fork is the same, by design. The model's authority is the fork and the open questions. Accuracy lives in the deterministic engine (DEV 19/22 from code alone). The model routes 10 requests to NA without fetching the evidence, and it investigates N cases. Changed steps: M. Tools on vs off: X."
- *"Why can't the model see the case on turn 1?"* → "Intent comes from the request text alone. Evidence that records exist must not talk the model into a deletion. Text-only also makes identical requests route identically, from the cache."
- *"The engine runs before the model asks. Is `audit_case` real?"* → "The computation is global (one-to-one assignment across all requests), so it runs once. The tool gives the model access to the case's findings, and the model decides whether to ask."

**DEV evidence:** as for A. DEV cannot separate A from A+, because no DEV case has an open question (INFERRED: no DEV case needs a PNG, `research/15` §1; DEV has no NA, `CONTRACT_DRAFT.md` F04b).

### 1.3 Not options: the tools-off arm (C) and the free-form agent (B)
- **C (model for intent and vision only; no loop)** is the **tools-off measurement arm** and the over-budget fallback, not a ship candidate. Shipping it would break two T63 pins: "uncertain routes to a tool", and "tools on vs off" has no "on". It is still projected, as the floor.
- **B (free-form tool agent that decides facts)** is rejected. It contradicts T10 and T42 (no model override of settled facts) and `research/14` §4.5. It is the most variable and has no output upside.

### 1.4 Side by side
| | A | A+ (text-first) |
|---|---|---|
| Who routes | Code, on the model's intent and the open questions | The model: the fork, then tool choice |
| Model calls in one full run (expected) | 375 intent + 11 vision + ~20 loops × ~4 ≈ 466 | 375 turn-1 + 508 turn-2 + 11 vision + ~20 loops × ~3 ≈ 954 |
| Output | Engine (DEV 19/22) + intent + vision | Same |
| Code, architecture sub-score (INFERRED) | Model-assisted pipeline | Agent with model-driven routing; +0.3 to +0.8 |
| Extra code over A | — | `audit_case` tool, routing-consistency checks, a turn-1 builder (~150–250 lines) |
| Cost, expected / token-stress | $24 / $80 | $39 / $128 |
| Interview difficulty | Low | Medium (the "fixed workflow" probe) |

---

## 2. Cost against the $120 budget
**Budget:** $120, the $20 balance plus the $100 Max credit confirmed on 24 Oct (`PLAYBOOK` §5). Prices: Sonnet 5.5 at $2 in / $10 out per million tokens; 5-minute cache write $2.50; cache read $0.10; Batch 50% off. Thinking cannot be disabled and is billed as output (`research/13` §0 and §2; `verify/13` C04 and C20–C26, CONFIRMED).

**Assumptions** (INFERRED unless marked; **replace them with the measured `usage` of 3 DEV cases before any wider run**, per `PLAYBOOK` §5 rule 2):

| Item | Value |
|---|---|
| Test request texts | 518 rows, **375 distinct**, median about 69 tokens, 24 with CJK text (SEEN counts; tokens assume 3 characters per token for Latin script and 1.3 tokens per CJK character) |
| PNGs | 11 images, 1,500–1,800 px wide, about 1,782–2,795 visual tokens each, **28,692 in total** (SEEN dimensions; formula from `research/13` §6) |
| Shared prefix | Intent: 1,800 tokens (system plus schema). A+ turn 1: 3,300 (adds 5 tools and the 286-token tool overhead; the 286 is SEEN in `research/13` §2) |
| Output per call (thinking + answer) | Turn 1 or intent: 450 (high 1,500). Turn 2: 500 (high 1,500). Each loop turn: 700 (high 1,500). Vision: 1,500 (high 4,000) |
| `audit_case` result | 800 tokens (high 2,000) |
| Prefix cache-read share | 95% (high 70%). Caching needs ≥512 tokens, and a first response before the parallel calls (`research/13` §7) |
| Cases with open questions in a full run | 20 (high 60) |
| Cache hits | Free: an unchanged request replays at $0 |
| Planned iterations (new requests only) | DEV: 9 prompt revisions + 3 replicates. Fixtures: 10. Test-input sweeps (no gold): routing/intent 1 + 1 replicate; vision 3; loops 2. Full runs: 2 (one, plus one re-run margin). Then +30% |

**Unit cost per call (expected / high):**
| Call | Expected | High |
|---|---:|---:|
| Intent (A) | $0.0052 | $0.0167 |
| Turn 1 (A+) | $0.0055 | $0.0180 |
| Turn 2 (A+) | $0.0083 | $0.0248 |
| Vision, per PNG | $0.0206 | $0.0464 |
| One open-question loop | $0.052 | $0.19 |

**One full 518-case run, by stage (expected):**
- **A:** intent $1.93 + vision $0.23 + loops $1.03 = **$3.19**.
- **A+:** turn 1 $2.06 + turn 2 $4.19 + vision $0.23 + loops $1.04 = **$7.51**.
- High token profile: A $18.28; A+ $31.43.

**Projection** (`cost_final.py`; total includes the 30% contingency):
| Bound | Option | DEV 22 × 12 | Fixtures | Test sweeps | 2 full runs | +30% | **Total** |
|---|---|---:|---:|---:|---:|---:|---:|
| Expected | A | 2.60 | 2.63 | 6.62 | 6.39 | 5.47 | **23.71** |
| Expected | A+ | 4.87 | 3.50 | 6.87 | 15.03 | 9.08 | **39.34** |
| Expected | C (arm) | 1.36 | 0.57 | 4.55 | 4.32 | 3.24 | **14.03** |
| Token-stress (thinking about 3×, planned iterations) | A | 9.01 | 9.50 | 21.76 | 21.23 | 18.45 | **79.97** |
| Token-stress | A+ | 15.92 | 12.17 | 22.68 | 47.42 | 29.46 | **127.66** |
| Worst (stress tokens and stress iterations) | A / A+ | | | | | | 221.77 / 284.21: the guard stops these |

**Break-even** (`breakeven.py`: every output-token figure scaled together):

| Option | Exceeds $90 at | Exceeds $120 at |
|---|---:|---:|
| A+ | 2.80× | 3.80× |
| A | 4.65× | 6.30× |

**The 3-DEV-case measurement therefore decides A+'s budget fit.**

**Over-budget policy** (in code, `model/budget.py`):
- **Caps.** Every live call reserves its worst case (estimated input × $2/M + `max_tokens` × $10/M) against a per-run dollar cap and call cap. Proposed caps:

  | Run | Dollar cap | Call cap |
  |---|---:|---:|
  | DEV | $3 | 200 |
  | Fixtures | $2 | 150 |
  | Test sweep | $12 | 600 |
  | Full run, A+ | $30 | 1,500 |
  | Full run, A | $20 | 800 |

  A project ledger also stops at **$110**, keeping $10 in reserve.
- **When a cap is hit:**
  - the call raises `ModelCallFailed(reason="BUDGET")`;
  - the remaining cases take the deterministic engine's output with `model_answer=FAILED_BUDGET` logged;
  - **a row is never left empty.**
- **Scheduling, so the cap bites the least valuable calls first:**
  1. vision (11 calls);
  2. intent or turn 1, for every case;
  3. open-question loops;
  4. A+ confirmation turns.

  A budget failure before step 2 finishes falls under the intent fail-closed policy (Q2).

**Batch API:**
- **The frozen run should not use it.** G9's clean-cache run replays the kept reply cache and makes no API call at all.
- **The paid run that fills the cache** uses Batch only if the 3-case measurement projects the project total above **$80**. In that case:
  - turn 1 or intent plus vision go in one batch (~386 requests; saves $1.14 expected, $3.62 high per run);
  - A+ turn 2 goes in a second round (saves $2.10 expected, $6.30 high);
  - loops stay synchronous.
- **Otherwise stay synchronous.** A second client path (submit, poll, errored and expired items, `custom_id` mapping, up to 24 h per round) is not worth $1–3 per run.
- **Either way,** the batch client writes into the same reply cache under the same request key, and the pipeline reads only through the cache.

---

## 3. Recommendation
**Ship A+ in the text-first routing form (§1.2),** with A as `--mode A` and the tools-off arm as `--mode tools_off`, all in one codebase.

**Why:**
1. It matches D8 and T10 ("the code score still needs a visible agent") at no output cost. Settled slots are read-only, failures fall back to the engine, and intent is fixed before evidence is seen.
2. It is affordable at the expected profile ($39 of $120), and the 3-case measurement checks this before anything wide runs.
3. A is a switch, not a rewrite. The A-vs-A+ comparison costs only the turn-2 calls, because both arms share turn 1 when A is built on the same turn-1 request.

**Switch to A** if any of these holds:
- A+ changes any DEV row (status or row-exact) against A;
- the 3-case measurement projects the project total above $90;
- turn-1 replicate agreement is below 100% over DEV, the fixtures and the 375 test texts;
- `INTENT_DRIFT` fires on any case after its repair turn.

**The single biggest risk.** Model answers change rows the engine already gets right; A+ adds 518 conversations of exposure. The sharpest form is the intent fork:
- 10 test texts are non-deletion traps (`research/16` §1.1);
- in one of them (case_533) the ledger shows the account FOUND, so a misread produces a destructive plan for an account the person wants kept.

**How to detect it early.** Make G7's first paid step (about $2–6) the turn-1 routing alone, over the 375 distinct test texts, the 22 DEV texts and the fixtures. Run it twice, in separate cache namespaces. Require:
1. 100% replicate agreement;
2. the intake cross-check table at 508 deletion / 10 non-deletion agreements (INFERRED target: the CLASSIFY_REQUEST rows fall on exactly the 10 non-deletion texts, `gold_forensics.md` trap table);
3. fixture F1 (the negation trap) correct.

Then, in every later run, compile each case twice, with model answers applied and withheld. The differing cases (M) must be exactly the cases with an open question.

---

## 4. Conflicts: pinned requirements and rulings against DEV
### 4.1 The validator (T66 replaces T63 pin 3)
**The rule as ruled** (the developer's words, sent by main at about 03:24):
- **Hard.** A step that says a record still exists (a FINDING, or a record kept under a hold) must cite a file that contains that resource.
- **`VERIFY_RECORD_ABSENT`** may cite any of these:
  - a file that contains the resource;
  - a file whose declared scope covers its system;
  - a file that lists records of the resource's own system but not this one.
- **Any other absence citation** is flagged and counted, never changed.
- **Every step:** the ID exists in the index and was captured at or before `audit_at`. NOT_APPLICABLE rows are validated too, and `audit_id` citations are accepted.

**Counts.** Main's, from scratchpad `gpq/validator_t66.py` and `validator_t66b.py`, recorded in `notes/RESUME.md`. Not recomputed here. Not yet recorded as T66 in `DECISIONS.md`.

**DEV gold: 52/52 cited steps pass; 0 flagged; 0 time or index failures; 0 row changes.**
- hard: 34/34 contain the resource;
- `VERIFY_RECORD_ABSENT`: 7 (4 contain, 1 scope-covered, 2 same-system listing: case_01 and case_02 citing evidence_54);
- other verifications: 11/11 contain.
- The DEV baseline `g4fix-baseline-20261025T0314` gives the same counts.

**Prototype test output (518 rows):**

| Part | Without vision | With the vision table |
|---|---|---|
| Hard | 865 steps: 863 contain, **2 fail** | 875 steps: 863 contain, 10 cite images that need G7, the same 2 fail |
| `VERIFY_RECORD_ABSENT` | 152 steps: 85 contain, 30 scope, 33 same-system, **4 flagged** (case_543/545/547/549, accounts citing evidence_52, a failover replica holding only other systems' records) | 151 steps: 84 / 30 / 33, the same 4 flagged |
| Other verifications | 224/224 contain | 225 steps, of which 1 does not contain the resource: case_46 `VERIFY_RECORD_REDACTED tombstone_17` citing evidence_67 |

The 2 hard failures:
- **case_126:** `REPORT_REMAINING_RECORD account_8819` citing evidence_87;
- **case_33:** `REPORT_REMAINING_RECORD export_1842` citing evidence_18.

**What the counts mean for the design, and the choices:**
1. **case_126 is already resolved by T54** (INFERRED from `gold_forensics.md` H3: under `sql_strict` the row becomes COMPLETE). Its verifications cite evidence_87, which scopes `account_service`, so they pass the second ABSENT branch. G5 must show this with a test. It is not a choice.
2. **case_33.** `export_1842` appears in no evidence file. evidence_18 holds its alias `NST-2026-0718-1842`, which the LINK row `activity_4009` ties to the resource and to user_18 (`research/15` §3.5 item 3; RESUME). DEV is not affected. **Choices for a hard failure** (Q3):

   | Choice | What happens | Test rows |
   |---|---|---|
   | (a) | "Contains" includes an alias that a LINK_RESOURCE_IDENTITY row at or before `audit_at` ties to the resource. One rule, tested in both directions | 1 passes |
   | (b) | Cite the LINK activity row instead. Its `event_time` must be ≤ `audit_at` (UNKNOWN here). The coherence check S10 then flags an activity citation | 1 changed citation |
   | (c) | Keep the finding and its citation; mark the row `FAILED_CLOSED(HARD_CITATION)`, status stays INCOMPLETE | 1 flagged |

   **Never drop the finding.** Dropping it turns INCOMPLETE into COMPLETE, the error the developer cares most about avoiding (`SYSTEM.md`).
3. **The 4 flagged ABSENT citations are kept unchanged and counted**, as ruled. `metrics.json` lists them by case. Freeze reads 3 of them (D17).
4. **Images under the hard check.** For a PNG citation, "contains" means the validated, cached vision extraction lists the resource ID. Ten hard steps depend on this (vision row). Containment for an image is therefore only as good as G7's extraction, and the agreement checks in §9 measure that.
5. **Main's open question** (Q4): do REDACTED, ANONYMIZED, DATA_FLOW_DISABLED and RESTORE_BLOCKED verifications fall under the hard check? The rule does not name them. Only case_46 is affected (`tombstone_17` with evidence_67, the known case_46 question, `gold_forensics.md` item 6).

### 4.2 Other pinned requirements (T63) checked against DEV
| Pin | DEV basis | Conflict? |
|---|---|---|
| Intent is the model's call; "please verify my deletion is complete" counts as deletion | `CONTRACT_DRAFT.md` A12: settled as deletion on case_21, 26 and 27 | None |
| Cross-check flags only | The CLASSIFY_REQUEST intake rows: DEV 0, test 10, the same 10 as the non-deletion texts (`gold_forensics.md` trap table) | **DEV cannot test the non-deletion branch.** It rests on fixture F1 and the test-input agreement table. A model misread that survives the second look still ships, because no override is allowed. That is the developer's pin; flagged as a residual risk |
| "Uncertain" routes to a tool or a fail-closed row | 0 DEV cases expected (INFERRED) | None. Fixture-only |
| Unresolved identity has a defined outcome, never NA | 22/22 DEV and 518/518 test emails resolve (`CONTRACT_DRAFT.md` §2) | **No schema-valid row exists** when nothing is found: INCOMPLETE needs a finding and COMPLETE needs citations. Outcome in §6 and Q5: discovery by the raw request email and its hash, then `FAILED_CLOSED(IDENTITY_UNRESOLVED)` |
| Reported effect (N, M, on/off, agreement table) | No DEV case has an open question (INFERRED) | **On DEV, N and M will be about 0 and the delta 0.** The effect shows on fixtures and in test-input diffs. Report it that way (§9) |
| Fake-client tests; two-process sha256; no snapshot or self-confirming tests | GP's required real-data test on evidence_51 asserts a structural property, not a snapshot (`INTERFACES.md` §4 rule 2) | None |
| No sample case IDs in source comments; docstring lint; failed calls logged | SEEN: 0 `case_\d+` hits in `code/deletion_audit/**/*.py`. `code/evaluation/split.py` and evaluation tests hold case IDs by design | **Scope:** lint `code/deletion_audit/**` and `agent/prompts/` only (Q8). `split.py` must hold the IDs (`PLAYBOOK` D4) |
| Start from the September build plus C1–C6 | §11 | Three September pieces conflict with today's rules: a cache key containing `request_id` (vs `../CLAUDE.md` §5), a forced `emit_result` tool (400 on Sonnet 5.5, `research/13` §4), and Hypothesis (not installed, SEEN). All three change |

### 4.3 Rulings against DEV or against each other
| Ruling | Conflict | DEV / test rows | Proposed handling |
|---|---|---|---|
| T8 / T40 / T60 (an unparsed dependency is never COMPLETE) vs H03 (INCOMPLETE needs ≥1 finding) | A failed dependency in a case with no finding has no schema-valid status | DEV 0; test 0 after G7 (T60 zero skips; gp-0259 has 0 failures) | `FAILED_CLOSED` as an enumerated row class: INCOMPLETE with the validated steps, its reason logged, H03 reported as hard by coherence. Freeze requires a count of 0 or a developer acknowledgement (Q5) |
| T27 (account step `VERIFY_RECORD_ABSENT` with `""`) vs H09 (COMPLETE verifications must cite) | A T27 case that comes out COMPLETE would carry an uncited verification | 0 expected: all 6 T27 cases are expected INCOMPLETE (`research/16` §4.7, INFERRED, pending vision) | If one is COMPLETE: cite through T66's ABSENT branches from pre-audit files only; otherwise flag and count (Q6) |
| T9 "follow `deletion_rules.csv` literally" vs DEV | rule_14 says RETAIN, but gold does BLOCK_RESTORE → VERIFY_RESTORE_BLOCKED (2 DEV backups). rule_05's condition is not observable in 3 of 4 REDACT cases (`gold_forensics.md` Q6) | DEV 2 backups + 3 redactions | The policy module maps actions and does not gate on conditions; backups follow the restore-risk path. Already reported in G2; the G5 tests pin it |
| A legal hold that names no resource (evidence_27) vs T9 "the hold rule's operation applies" | No step at all, rather than VERIFY_PRESENT | DEV: 0 RETAIN steps for 5 people in the register (RESUME (d); **awaiting main's own count**) | `policy` returns `NO_STEP` for a register entry with no resource ID; a resource-level hold gives VERIFY_PRESENT under T66's hard check |
| T5 / T53 / T62 (generator-timing rules) vs `PLAYBOOK` D3 ("its reason") | Data basis only, no domain basis | DEV 4/4 analytics (`g2f2-g2f2_h2_analytics-0242`) | No change. README statements (T5, T53) |

---

## 5. Recommended option: modules and typed interfaces (G5, GM, G7)
**Built on GP's pinned interface** (`notes/INTERFACES.md` §2 and §3; `code/deletion_audit/evidence/model.py`, SEEN): `Observation`, `SnapshotScope`, `FileParse`, `EvidenceIndex`, `Identifier`, `Locator`, `ActivityRow`, `IdentityRow`, `AuditLogRow`.

**Environment** (SEEN this run):
- **Installed:** Python 3.14.7, `pdfplumber` 0.11.10.
- **Not installed:** `anthropic`, `pydantic`, `python-dotenv`, `pytest`, `hypothesis`, `ruff`, `mypy`.
- **So:** GM pins `anthropic==2.3.0` (`verify/13` H1), which brings `pydantic` and `httpx2` (INFERRED from `verify/13` M2). Tests stay on `unittest`. Property tests use seeded generators. Installing ruff and mypy needs the developer's OK (Q9).

**Each T63 pin, where it lives and the test that holds it:**

| Pin | Interface | Test (§7) |
|---|---|---|
| 1. Intent | `agent/intent.py` (A) / `agent/loop.py` turn 1 (A+); `IntentAnswer.intent` includes `UNCERTAIN`; `agent/crosscheck.py` flags only; `agent/prompts/intent.md` defines verify-requests as deletion and uses made-up IDs; `model/cache.py` stores raw replies | `test_intent_is_model_answer_crosscheck_flags_only`, `test_prompt_defines_verify_request_as_deletion`, `test_uncertain_routes_to_tool_or_failed_closed`, `test_prompt_examples_use_made_up_ids`, `test_cache_stores_raw_replies_only` |
| 2. Reported effect | `artifacts.py` (`tool_calls`, `answers_applied`) + `evaluation/agent_report.py` | `test_agent_report_counts_from_artifacts` |
| 3. Validator (T66) | `validate/prewrite.py` | `test_hard_citation_contains_resource`, `test_absent_citation_branches`, `test_other_absence_citation_flagged_not_changed`, `test_na_rows_validated`, `test_audit_id_citation_accepted` |
| 4. Unresolved identity | `identity/resolve.py` (`status="UNRESOLVED"`) → `validate/prewrite.py` FailedClosed | `test_unresolved_identity_defined_outcome_never_na` |
| 5. Tests | `model/transport.py` `FakeTransport`; `pipeline.run(replay_only=True)` | `test_retry_ladder_fake_client`, `test_cache_hit_makes_no_call`, `test_give_up_single_place`, `test_two_process_output_sha256_equal`, `test_no_test_reads_runs_or_cache_as_expected` |
| 6. Hygiene | `model/client.py` → `artifacts.CallLogEntry(error_class, status)` | `test_no_case_ids_in_pipeline_source`, `test_core_modules_have_docstrings`, `test_failed_call_logs_error_class_and_status` |
| 7. Code structure | §11 | the verifier gate |

**Signatures** (stdlib frozen dataclasses for engine types; pydantic only for model reply schemas):
```python
# ---- inputs/requests.py  (new; T32: both request files, never sample_output.csv)
ReportedStatus = Literal["COMPLETE", "PARTIALLY_COMPLETE", "NOT_STARTED"]
@dataclass(frozen=True)
class DeletionRequest:
    case_id: str; email: Identifier; requested_at: str; reported_status: ReportedStatus
    reported_at: str; audit_at: str; request_text: str
    source: Literal["test", "sample"]          # which file; sample rows compete in assignment, never output
def load_requests(dataset_dir: Path) -> tuple[DeletionRequest, ...]: ...

# ---- identity/resolve.py
@dataclass(frozen=True)
class IdentifierSet:
    user_id: str | None
    emails: frozenset[str]; phones: frozenset[str]; email_hashes: frozenset[str]   # every one ever held, up to audit_at (T59)
    def matches(self, ident: Identifier) -> bool: ...        # exact match on normalized value only (T49)
@dataclass(frozen=True)
class IdentityResolution:
    status: Literal["CURRENT", "HISTORICAL", "UNRESOLVED"]
    identifiers: IdentifierSet                     # UNRESOLVED: {request email, sha256(lower(email))} only
    via_audit_ids: tuple[str, ...]                 # user_audit_log rows that resolved an old email (citable IDs)
def resolve(req: DeletionRequest, identities: Sequence[IdentityRow],
            audit_log: Sequence[AuditLogRow]) -> IdentityResolution: ...

# ---- discovery/links.py
@dataclass(frozen=True)
class Window: requested_at: str; audit_at: str
@dataclass(frozen=True)
class Link:
    observation: Observation
    basis: Literal["record_identifier", "trace_lookup", "link_row", "image_extraction"]
    matched: Identifier
    in_window: bool        # line/record time in [requested_at, audit_at] (R3/R4)
    citable: bool          # file captured_at <= audit_at (F21, equality allowed)
def link_observations(person: IdentityResolution, index: EvidenceIndex,
                      activity: Sequence[ActivityRow], window: Window) -> tuple[Link, ...]: ...

# ---- discovery/accounts.py   (global: one call for all requests of both files)
AccountStage = Literal["S1_IDENTIFIER", "S2_TIMED", "T26_HAND_BUILT", "S3_ONE_TO_ONE", "S4_FINGERPRINT",
                       "S4B_ONE_TO_ONE", "S5_TIE_PICK", "T27_LATER_LOOKUP", "T28_NONE"]
@dataclass(frozen=True)
class Flag: code: str; detail: str          # detail names IDs and counts only, never cell text
@dataclass(frozen=True)
class AccountAssignment:
    case_id: str; resource_id: str | None; stage: AccountStage
    candidates: tuple[str, ...]; activity_ids: tuple[str, ...]; flags: tuple[Flag, ...]
@dataclass(frozen=True)
class AccountConfig:            # values and basis live in config.py's tunables table
    window_min: tuple[int, int] = (-75, -44); hand_built_min: int = 10
    result_map: Mapping[str, str] = ...; tie_order: Literal["sha256_user_id"] = "sha256_user_id"
def assign_primary_accounts(requests: Sequence[DeletionRequest], people: Mapping[str, IdentityResolution],
                            activity: Sequence[ActivityRow], links: Mapping[str, tuple[Link, ...]],
                            cfg: AccountConfig) -> Mapping[str, AccountAssignment]: ...

# ---- discovery/analytics.py   (T5/T29/T53/T62)
@dataclass(frozen=True)
class AnalyticsClaim: case_id: str; resource_id: str; slot: int; residual_s: int; anchor_stage: AccountStage; flags: tuple[Flag, ...]
def attach_identifier_free_analytics(assignments: Mapping[str, AccountAssignment], requests: Sequence[DeletionRequest],
                                     people: Mapping[str, IdentityResolution], activity: Sequence[ActivityRow],
                                     index: EvidenceIndex, bands: SlotBands) -> Mapping[str, tuple[AnalyticsClaim, ...]]: ...

# ---- state/reconstruct.py   (R5, R6, R8, T50, T54)
StateValue = Literal["PRESENT", "ABSENT", "IDENTIFIABLE", "ANONYMIZED", "REDACTED", "EXPOSED_PII",
                     "FLOW_ENABLED", "FLOW_DISABLED", "RESTORABLE", "RESTORE_BLOCKED", "RETAINED"]
@dataclass(frozen=True)
class ResourceKey: system_id: str; resource_id: str
@dataclass(frozen=True)
class ResourceState:
    key: ResourceKey; value: StateValue
    basis: Literal["latest_observation", "omission_in_declared_scope", "default_absent", "image_extraction"]
    deciding: Locator | None; decided_at: str | None
    depends_on: frozenset[str]          # file_ids whose parse status this state relies on (T8 propagation)
def state_at(key: ResourceKey, links: Sequence[Link], scopes: Sequence[SnapshotScope], audit_at: str) -> ResourceState: ...

# ---- policy/rules.py   (deletion_rules.csv; T9 provisional defaults; T55)
@dataclass(frozen=True)
class Categorization:
    category: str                       # a deletion_rules.csv data_category, or DATA_FLOW
    basis: Literal["content_cue", "worker_action", "resource_type"]; flag: Flag | None
@dataclass(frozen=True)
class PolicyDecision:
    rule_id: str | None; outcome: Literal["FINDING", "COMPLIANT", "NO_STEP"]
    finding_op: str | None; remediation_op: str | None; verification_op: str | None
def load_rules(dataset_dir: Path) -> RuleTable: ...
def categorize(key: ResourceKey, links: Sequence[Link], activity: Sequence[ActivityRow], audit_at: str) -> Categorization: ...
def decide(state: ResourceState, cat: Categorization, rules: RuleTable) -> PolicyDecision: ...

# ---- engine.py   (composes the above; the deterministic auditor; also the audit_case tool's backend)
@dataclass(frozen=True)
class OpenQuestion:
    oq_id: str                               # sha256(case_id, type, subject)[:12], never a row index
    type: Literal["INTENT_UNCERTAIN", "INTENT_CROSSCHECK", "IMAGE_FIELD_UNREADABLE",
                  "IMAGE_SUBJECT_CONFLICT", "UNKNOWN_FORMAT", "INSTRUCTION_LIKE_TEXT"]
    subject: str                             # file_id or resource_id the question is about
    allowed_choices: tuple[str, ...]; slot: str | None      # the only slot an answer may fill
@dataclass(frozen=True)
class EngineBrief:
    case_id: str; settled: tuple[ResourceFinding, ...]; citation: CitationPlan
    open_questions: tuple[OpenQuestion, ...]; flags: tuple[Flag, ...]
    def for_model(self) -> str: ...          # compact JSON; IDs and states only; marked read-only
def audit_all(ctx: AuditContext) -> Mapping[str, EngineBrief]: ...

# ---- steps/  (citation.py, compile.py, order.py, serialize.py)
@dataclass(frozen=True)
class CitationPlan: file_id: str | None; rule: Literal["R14_linked", "R14_fallback_same_system", "none"]
@dataclass(frozen=True)
class Step:
    step_no: int; phase: Literal["FINDING", "REMEDIATION", "VERIFICATION"]; system_id: str
    resource_id: str; operation: str; state: str; evidence_id: str        # "" where the spec says so
def choose_citation(person: IdentityResolution, links: Sequence[Link], req: DeletionRequest, index: EvidenceIndex) -> CitationPlan: ...
def compile_steps(intent: "IntentDecision", resources: Sequence[ResourceFinding], citation: CitationPlan) -> tuple[Step, ...]: ...
def derive_status(intent: "IntentDecision", steps: Sequence[Step]) -> Literal["COMPLETE", "INCOMPLETE", "NOT_APPLICABLE"]: ...
def write_output(records: Sequence["CaseRecord"], path: Path) -> str: ...   # LF, compact JSON, numeric case order; returns sha256

# ---- validate/prewrite.py   (T66 + G1 H01–H16; reports, never edits a step)
@dataclass(frozen=True)
class CheckResult: rule: str; severity: Literal["hard", "flag"]; ok: bool; step_no: int | None; detail: str
@dataclass(frozen=True)
class ValidationContext:
    citable_time: Mapping[str, str]                    # file_id / activity_id / audit_id -> time
    file_resources: Mapping[str, frozenset[ResourceKey]]    # incl. image-extraction observations
    file_scope_systems: Mapping[str, frozenset[str]]        # declared scopes only (T50)
    file_listed_systems: Mapping[str, frozenset[str]]       # systems with >=1 record in the file
    file_status: Mapping[str, str]
def validate_row(record: "CaseRecord", ctx: ValidationContext) -> tuple[CheckResult, ...]: ...

# ---- model/  (GM gate)
@dataclass(frozen=True)
class ModelRequest:
    body: Mapping[str, Any]     # model, system, tools, tool_choice, messages, output_config{format, effort}, max_tokens
    def key(self) -> str: ...   # sha256(canonical_json(body) + anthropic-version); no case_id, no row index
@dataclass(frozen=True)
class ModelReply: key: str; raw: Mapping[str, Any]; model: str; usage: Mapping[str, int]
                  stop_reason: str; request_id: str | None; from_cache: bool; bought_by_run: str
class ModelCallFailed(Exception):
    reason: Literal["TRANSPORT_GAVE_UP", "NON_RETRYABLE", "BUDGET", "CALL_CAP", "REPLAY_MISS", "STRUCTURE_GAVE_UP"]
    error_class: str; status: int | None
class Transport(Protocol):
    def send(self, body: Mapping[str, Any]) -> Mapping[str, Any]: ...   # AnthropicTransport (SDK, max_retries=0) | FakeTransport
class ModelClient:
    def __init__(self, transport: Transport, cache: ReplyCache, budget: BudgetGuard, policy: RetryPolicy,
                 log: CallLog, *, replay_only: bool, run_id: str) -> None: ...
    def call(self, req: ModelRequest) -> ModelReply: ...   # cache -> budget -> send/ladder -> cache.put -> log
class RetryPolicy:          # THE one place that decides retry / repair / give up
    def decide(self, failure: Failure, attempt: int) -> Retry | Repair | GiveUp: ...
class ReplyCache:
    def __init__(self, root: Path) -> None: ...
    def get(self, key: str) -> ModelReply | None: ...
    def put(self, req: ModelRequest, raw: Mapping[str, Any], run_id: str) -> None: ...   # atomic, never overwrites
class BudgetGuard:
    def __init__(self, dollar_cap: float, call_cap: int, ledger: Path, project_cap: float = 110.0) -> None: ...
    def reserve(self, req: ModelRequest) -> Reservation: ...      # raises ModelCallFailed(BUDGET | CALL_CAP)
    def settle(self, res: Reservation, usage: Mapping[str, int]) -> float: ...

# ---- agent/  (G7)
class IntentAnswer(BaseModel):                 # reply schema; extra="forbid"; enums compared case-insensitively
    intent: Literal["DELETION_REQUEST", "NOT_DELETION", "UNCERTAIN"]
    request_kind: Literal["full_deletion", "verify_deletion", "scoped_deletion", "access", "correction",
                          "export", "marketing_opt_out", "account_help", "other"]
    language: str; basis_quote: str            # code checks: basis_quote is a substring of the request text
    instruction_like_text: bool
class FinalAnswer(IntentAnswer):
    answers: list[OQAnswer]; cannot_answer: list[OQCannot]
class OQAnswer(BaseModel): oq_id: str; choice: str; evidence_ids: list[str]; note: str
class OQCannot(BaseModel): oq_id: str; reason: Literal["NO_EVIDENCE", "CONFLICTING", "UNREADABLE", "OUT_OF_SCOPE"]
@dataclass(frozen=True)
class CrossCheck: intake_non_deletion: bool; activity_ids: tuple[str, ...]   # CLASSIFY_REQUEST rows for the person
@dataclass(frozen=True)
class IntentDecision:
    label: Literal["DELETION_REQUEST", "NOT_DELETION", "UNCERTAIN"] | None
    source: Literal["MODEL", "MODEL_AFTER_TOOLS", "FAILED_CLOSED", "FAILED_BUDGET"]
    committed_key: str | None; final_key: str | None; crosscheck: CrossCheck; agrees: bool | None
def intake_crosscheck(req: DeletionRequest, person: IdentityResolution, activity: Sequence[ActivityRow],
                      links: Sequence[Link]) -> CrossCheck: ...
def read_images(index: EvidenceIndex, client: ModelClient) -> tuple[EvidenceIndex, tuple[ImageReadRecord, ...]]: ...
@dataclass(frozen=True)
class LoopCaps: max_tool_calls: int = 4; max_requests: int = 6; max_wall_s: float = 180.0; no_repeat: bool = True
@dataclass(frozen=True)
class ToolCallRecord: name: str; args_hash: str; is_error: bool; evidence_ids: tuple[str, ...]
@dataclass(frozen=True)
class AgentOutcome:
    case_id: str; intent: IntentDecision; final: FinalAnswer | None
    tool_calls: tuple[ToolCallRecord, ...]; reply_keys: tuple[str, ...]
    status: Literal["OK", "FINALIZED_AT_CAP", "FAILED"]; flags: tuple[Flag, ...]
def run_case(brief: EngineBrief, req: DeletionRequest, client: ModelClient, tools: "ToolRegistry",
             caps: LoopCaps, mode: Literal["A+", "A", "tools_off"]) -> AgentOutcome: ...
def validate_answers(outcome: AgentOutcome, brief: EngineBrief, ctx: ValidationContext) -> tuple[ValidatedAnswer | Rejection, ...]: ...

# ---- agent/tools.py   (read-only; case-bound by the harness; each result names its evidence IDs)
#   audit_case(intent, request_kind, language, basis_quote)   A+ only; returns EngineBrief.for_model()
#   get_request_context()                    reported_status, dates, intake rows <= audit_at, same-person request count
#   inspect_evidence(file_id, focus: Literal["records", "identity", "state"])   re-read of an image/PDF captured <= audit_at
#   lookup_identity(value)                   current and historical identities for an email, phone or hash
#   list_activity(identifier_or_resource)    activity rows with event_time <= audit_at
#   (query_snapshot(file_id, sql): build only if UNKNOWN_FORMAT ever names a SQL file; 0 today)

# ---- record.py / artifacts.py / pipeline.py
def run(dataset_dir: Path, *, run_id: str, cases: Sequence[str] | Literal["test"],
        mode: Literal["A+", "A", "tools_off"], replay_only: bool, write_root: bool = False) -> "RunSummary": ...
class RunArtifacts:
    def case(self, record: "CaseRecord") -> None: ...      # runs/<id>/cases.jsonl
    def call(self, entry: "CallLogEntry") -> None: ...     # runs/<id>/calls.jsonl: key, attempt, from_cache, error_class, status, usage, cost
    def finish(self, output_sha256: str) -> "RunSummary": ...   # metrics.json, usage.json, producer.json
```

---

## 6. The canonical per-case record (every output field derives from it)
```python
@dataclass(frozen=True)
class ResourceFinding:
    key: ResourceKey
    link_basis: str                    # identifier | trace | link_row | image | timed_account | fingerprint | slot_band | tie_pick | t27
    state: ResourceState
    category: Categorization
    decision: PolicyDecision
    answered_by: str | None            # oq_id when a validated model answer filled this resource's open slot

@dataclass(frozen=True)
class CaseRecord:
    case_id: str
    request: DeletionRequest
    intent: IntentDecision
    identity: IdentityResolution
    account: AccountAssignment | None
    resources: tuple[ResourceFinding, ...]       # sorted by (system_id, resource_id)
    citation: CitationPlan
    open_questions: tuple[OpenQuestion, ...]
    answers: tuple[ValidatedAnswer, ...]
    rejected: tuple[Rejection, ...]
    failed_dependencies: frozenset[str]          # file_ids with a non-OK parse that some state depends on
    steps: tuple[Step, ...]                      # = compile_steps(intent, resources, citation): the source of truth
    checks: tuple[CheckResult, ...]
    flags: tuple[Flag, ...]

    @property
    def status(self) -> str:                     # derived, never stored
        return derive_status(self.intent, self.steps)

    @property
    def row_state(self) -> Literal["VALID", "FAILED_CLOSED"]: ...
```

**Derivation:**
- `NOT_APPLICABLE` ⇔ `intent.label == "NOT_DELETION"` from a validated model reply, and then `steps == ()`.
- Otherwise, `INCOMPLETE` ⇔ at least one FINDING step.
- Otherwise `COMPLETE`, which holds verification steps only, each cited.

**`FAILED_CLOSED`** (Q5): status INCOMPLETE, never COMPLETE and never NA; steps are the validated subset. It is used for:
- an unparsed dependency in a case with no finding (T8);
- an unresolved identity with nothing found;
- a hard citation failure under choice (c).

The reason is an enum, counted in `metrics.json`, and coherence reports H03.

**Intent fail-closed** (Q2, recommended): the engine's deletion-path row, flagged `intent.source=FAILED_CLOSED` or `FAILED_BUDGET`.

---

## 7. Hard invariants as test names
**Row and step** (G1 H01–H16, now in the pipeline's own validator as well as in `evaluation/coherence.py`):
- `test_status_derived_from_steps` (NA ⇔ `[]` ∧ model `NOT_DELETION`; INCOMPLETE ⇔ ≥1 FINDING; COMPLETE ⇔ cited verifications only)
- `test_step_numbers_consecutive_from_one`
- `test_operation_phase_state_table`
- `test_steps_sorted_phase_operation_system_resource`
- `test_no_duplicate_step_keys`
- `test_finding_remediation_verification_one_to_one`
- `test_evidence_empty_for_incomplete_remediation_and_verification`
- `test_every_cited_id_in_index_and_not_after_audit_at` (equality allowed)
- `test_hard_citation_contains_resource` (T66)
- `test_absent_citation_branches` (contains / scope / same-system listing)
- `test_other_absence_citation_flagged_not_changed`
- `test_na_rows_validated`
- `test_audit_id_citation_accepted`
- `test_output_one_row_per_case_numeric_order_lf_compact_json`
- `test_every_row_valid_or_failed_closed_never_empty`
- `test_failed_closed_never_complete_never_na`
- `test_hard_failure_never_drops_a_finding`

**Safety** (T42 and `research/18` C3/C4):
- `test_post_audit_evidence_never_cited`
- `test_unparsed_dependency_never_complete`
- `test_legal_hold_never_deleted`
- `test_complete_never_with_live_record_active_flow_or_restore_path`
- `test_retain_class_never_gets_delete`
- `test_instruction_like_text_flagged_never_followed` (planted-injection fixture F9)

**Identity and discovery:**
- `test_identity_case_insensitive_current_and_historical`
- `test_unresolved_identity_defined_outcome_never_na`
- `test_own_key_old_email_hash_links` (T59)
- `test_lookalike_never_links` (T49)
- `test_multi_resource_multi_person_pdf_page_never_links` (RESUME c)
- `test_account_order_s1_s2_t26_t27_t28`
- `test_timed_window_bounds_inclusive`
- `test_result_match_required_no_mismatch_fallback`
- `test_one_owner_per_person_shared_account_allowed` (T29)
- `test_tie_pick_max_matching_sha256_user_id` (T39)
- `test_fingerprint_precision_fixture_one_second` (T5)
- `test_slot_band_analytics_follow_job_account_flagged` (T53, T62)
- `test_t27_identity_only_never_discovers_never_cites`
- `test_t27_not_applied_to_audit_records` (T56)
- `test_assignment_reads_both_request_files_never_gold` (T32)

**State and policy:**
- `test_latest_observation_wins_same_time_violating`
- `test_omission_in_declared_scope_absent`
- `test_sql_inventory_never_rules_out_replica_copy`
- `test_support_records_never_cover_attachments` (T54)
- `test_plain_export_never_proves_absence` (T50)
- `test_support_category_cue_else_worker_action_flagged` (T55)
- `test_backup_follows_restore_path_not_present` (rule_14 vs DEV)
- `test_hold_register_without_resource_gives_no_step`

**Model and agent** (all on `FakeTransport`; no test makes a paid call):
- `test_intent_is_model_answer_crosscheck_flags_only`
- `test_prompt_defines_verify_request_as_deletion`
- `test_uncertain_routes_to_tool_or_failed_closed`
- `test_prompt_examples_use_made_up_ids` (no dataset ID or email in `agent/prompts/`)
- `test_cache_stores_raw_replies_only`
- `test_turn1_request_is_text_only` (A+: no email, case ID or evidence in turn 1)
- `test_answer_never_changes_settled_fact`
- `test_loop_cap_four_tool_calls_then_tool_choice_none`
- `test_no_repeated_identical_tool_call`
- `test_tool_choice_never_any_or_tool`
- `test_no_sampling_parameters_sent`
- `test_max_tokens_refusal_context_window_are_failures`
- `test_schema_mismatch_repair_bounded_two`
- `test_retry_ladder_fake_client`: 408, 409, 429, 529, `InternalServerError` (including 503 and 504, `verify/13` WRONG #2), `APIConnectionError` and `APITimeoutError` are retried; 400, 401, 402, 403, 404 and 413 are not
- `test_retry_after_header_honoured`
- `test_cache_hit_makes_no_call`
- `test_cache_key_ignores_row_position_changes_with_any_byte`
- `test_give_up_single_place`
- `test_failed_call_logs_error_class_and_status`
- `test_budget_cap_rows_take_engine_output_failed_budget`
- `test_replay_only_refuses_network`
- `test_routing_consistency_drift_and_no_audit_call` (A+)

**Determinism and hygiene:**
- `test_two_process_output_sha256_equal` (two subprocesses, different `PYTHONHASHSEED`, replay-only fixture cache)
- `test_no_case_ids_in_pipeline_source` (`code/deletion_audit/**`, `agent/prompts/**`)
- `test_core_modules_have_docstrings` (stdlib `ast`: every module, public class and public function in the core packages)
- `test_no_test_reads_runs_or_cache_as_expected` (no expected value is read from `runs/` or `cache/`: no snapshot or self-confirming tests)
- `test_no_stdlib_shadowing` (extends the G4 test to `deletion_audit`)

---

## 8. Where caching, determinism and retries live
- **Reply cache: `model/cache.py`.** Content-addressed files under `cache/replies/<key[:2]>/<key>.json`, gitignored and kept across clean-cache runs.
  - **Key:** sha256 of the canonical JSON of the full request body plus the `anthropic-version` header. It never includes the case ID or row position.
  - **Entry:** the raw reply as returned, the model ID, the original `usage`, the run that bought it, and the time written. **Raw replies only:** no parsed intent and no derived fact.
  - Failed replies (`max_tokens`, `refusal`) are stored too. Their repair appends a message, which makes a new request with a new key, so every replay is exact.
  - Replicates for run-to-run agreement use a separate cache root (`cache/replies-replica-k/`), not a key change.
- **Derived caches: `cache/derived/`** holds the parsed index and the image observations. It is deleted on every clean-cache run.
- **Determinism:**
  - `pipeline.py` sorts cases numerically, files in manifest order and observations in locator order, and serialises canonically.
  - `config.py` fixes the model ID, `output_config.effort` (`medium` for routing, intent and loops; to be confirmed by the 3-case probe), `max_tokens` (4,096 for turn 1 and intent; 8,000 for loops and vision; under the 21,333 non-streaming limit, `research/13` §0.5) and the prompt files.
  - Requests carry no clock values.
  - Run-to-run agreement is measured on DEV, the fixtures and the 375 test texts before any model field is trusted (`../CLAUDE.md` §5).
- **Retries:**
  - `model/client.py` runs one transport ladder with SDK `max_retries=0`. It honours `retry-after-ms` and `retry-after`, and otherwise backs off 1/2/4/8 s, at most 5 attempts.
  - `agent/structured.py` handles 200-level failures: refusal, `max_tokens`, `end_turn` with no text, schema mismatch. It allows at most 2 repairs.
  - **Both ask `RetryPolicy.decide`, the one place that gives up.** Every attempt is logged in `calls.jsonl` with `error_class` and `status`.
- **Budget: `model/budget.py`.** The reservation and settlement guard (§2), with a project ledger at `cache/ledger.jsonl`.

## 9. How the tool effect is measured, on and off
| Arm | What runs | Where it is measured |
|---|---|---|
| `A+` (ship) | Turn 1 + `audit_case` + chosen tools | DEV 22 (gold, dev-filtered loader), fixtures F1–F11 plus 3 new (expected answers derived from the spec), the 518 test inputs (diffs only, no gold) |
| `A` | The same turn 1; the loop continues only when there are open questions | Same |
| `tools_off` | Intent and vision only; open questions are unanswered and fail closed by type | Same |

**What is reported** (generated by `evaluation/agent_report.py` from `runs/<id>/` artifacts, never typed):
1. **N:** cases with ≥1 tool call other than `audit_case`, per tool, plus the tool-sequence histogram. `audit_case` calls are counted separately.
2. **M:** cases whose steps differ when validated answers are applied vs withheld. Each case is compiled twice within the same run, at no extra API cost. Also reported: rejected answers by reason.
3. **Arm deltas:** DEV status, row exact and step F1 per arm; fixture pass counts per arm; test rows that differ between arms, with 3 read by hand (D17).
4. **Intent agreement table:** the model (`DELETION_REQUEST`, `NOT_DELETION`, `UNCERTAIN` or failed) against the intake cross-check (row present / absent), on DEV and on test inputs. Also committed vs final intent (A+), and turn-1 replicate agreement.
5. **Vision agreement:** extracted resource IDs and states against LINK rows and text evidence for the same resource, and replicate agreement per field.
6. **Cost per arm**, from `usage.json`.

**Expected values** (INFERRED, to state in advance):
- DEV deltas of 0, because no DEV case has an open question;
- N and M of about 1–5 on test (the image cases);
- an agreement table of 508/10/0.

**New fixtures beyond `research/16` F1–F11:**
- F12: an image whose visible subject conflicts with its catalog link;
- F13: two cases sharing a request text (the cache-replay probe);
- F14: an unresolved identity.

---

## 10. Where each ruling lands
| T | Ruling (short) | Lands in | Pinned by |
|---|---|---|---|
| T1, T15 | Secret scan | `scripts/secret_scan.sh`, pre-commit | existing hook; packager check |
| T2 | Upstream `AGENTS.md` rename → stop | process | — |
| T3, T19–T24, T30, T36, T44, T46 | Schedule and parallelism | process | — |
| T4 | Account order; not-shipped list | `discovery/accounts.py` | `test_account_order_s1_s2_t26_t27_t28`, `test_timed_window_bounds_inclusive`, `test_result_match_required_no_mismatch_fallback` |
| T5 | Fingerprint as tie-break, ±1 s precision | `discovery/accounts.py`, `config.py` | `test_fingerprint_precision_fixture_one_second`; README statement |
| T6, T28 | Flagged tie pick; account step omitted only when no input names an account | `discovery/accounts.py`, flags | `test_account_order_…`; `metrics.json` count |
| T7 | Intent and screenshots from cached model calls; no hand tables | `agent/intent.py`, `agent/vision.py` | `test_intent_is_model_answer_crosscheck_flags_only`; lint: no `vision_facts` and no phrase table in `deletion_audit` |
| T8, T40 | An unparsed dependency never COMPLETE | `state/reconstruct.py` (`depends_on`), `validate/prewrite.py` | `test_unparsed_dependency_never_complete` |
| T9 | Provisional spec defaults | `policy/rules.py`; G5b fixtures marked provisional | F1–F10 |
| T10 | The agent never changes a settled fact; on/off measured | `agent/answers.py` | `test_answer_never_changes_settled_fact`; §9 report |
| T11 | Port, don't copy | process (G5 log) | — |
| T12–T14, T16, T21, T31 | G2 scope | `notes/gold_forensics.md` | — |
| T13 | Raw-file check | GP `raw_check.py` (done) | `notes/parser_raw_check.md` |
| T17 | The outside version is never imported | process | — |
| T18, T23, T41, T45, T61, T64 | Log format and hygiene | `scripts/check_log.py` | `scripts/test_check_log.py` |
| T25 | G5b fixtures gate | process | F1–F10 |
| T26 | ±10-min result-matched fallback | `discovery/accounts.py` | `test_account_order_…`; case_08 on the UNEXPLAINED list (report line) |
| T27 | Later identity lookup, primary account only | `discovery/accounts.py` | `test_t27_identity_only_never_discovers_never_cites`; README statement; flag |
| T29, T39, T57 | One owner per person; maximum matching ordered by sha256 of `user_id` | `discovery/accounts.py` | `test_one_owner_per_person_shared_account_allowed`, `test_tie_pick_max_matching_sha256_user_id`; README coin-flip count |
| T32 | Both request files' inputs; never gold | `inputs/requests.py` | `test_assignment_reads_both_request_files_never_gold` |
| T33, T37 | `SYSTEM.md` → README; `NUMBERS.md` stays | docs | — |
| T34, T47, T51, T60 | Eval loader, guard, skips, producer record | `code/evaluation/` (done) + `artifacts.py` `producer.json` | existing evaluation tests; `test_freeze_run_has_zero_skips` |
| T35, T38 | Parser layout, EMPTY vs scoped-OK, SQL caps | `evidence/` (done) | GP tests |
| T42 | Precedence list | the validator plus the safety tests (§7) | §7 safety group |
| T43 | Failure protocol | process | — |
| T48 | Lock incident | `evaluation_report.md` holdout section | report line |
| T49, T59 | Field role by line; complete identifier set; own key beats trace lookup | `interpret.py` (done), `identity/resolve.py`, `discovery/links.py` | `test_field_roles.py`, `test_own_key_old_email_hash_links`, `test_lookalike_never_links` |
| T50 | A plain export proves no absence | `collection_export.py` (done), `state/reconstruct.py` | `test_plain_export_never_proves_absence` |
| T52 | H1: no change | — | — |
| T53, T62 | Slot band; analytics follow the job's account, flagged | `discovery/analytics.py` | `test_slot_band_analytics_follow_job_account_flagged`; README statement |
| T54 | Absence by omission | `state/reconstruct.py` | `test_omission_in_declared_scope_absent`, `test_sql_inventory_never_rules_out_replica_copy`, `test_support_records_never_cover_attachments` |
| T55 | Support category: cue, else worker action, flagged | `policy/rules.py` | `test_support_category_cue_else_worker_action_flagged` |
| T56 | T27 not extended to audit records | `discovery/accounts.py` | `test_t27_not_applied_to_audit_records` |
| T58 | DEV 19/22 accepted | `evaluation_report.md` | report line |
| T63 | Pinned requirements | §5 table | §7 |
| T65 | Narrow reading (PDF content only); RESUME, not yet recorded | `evidence/` | existing GP test |
| T66 | Validator by step type | `validate/prewrite.py` | §7 row group |
| T67 | Run-ID pattern; RESUME, not yet recorded | `code/evaluation/runs.py`, `artifacts.py` | its own test (capital-T question pending) |

## 11. Code structure: September carried over, plus `research/18` C1–C6
The September build is at `research/01` §3.3, read with `verify/01`.

| September piece | October counterpart | Carry over or change |
|---|---|---|
| Signatures written before code (`CONTRACT.md`) | `notes/INTERFACES.md` + §5 here | Carry over |
| Every number in code; model gives typed records only | The engine produces every step; the model gives intent, image facts and open-question answers | Carry over |
| One ladder at 1/2/4 s, SDK `max_retries=0`, retryable `SchemaMismatch`, one give-up point | `model/client.py` + `RetryPolicy` | Carry over, adding 408/409, `retry-after`, 503 and 504 as `InternalServerError`, and 200-level stop reasons |
| Forced `emit_result` tool | `output_config.format` + Pydantic re-validation | **Change:** forced tool use returns 400 on Sonnet 5.5 |
| Cache key containing `request_id` | Content hash of the full request | **Change:** `../CLAUDE.md` §5 |
| 3 tools, ≤3 steps, fired on 13/250, never measured | 5 tools, ≤4 calls then `none`; N, M and the on/off arms reported | **Change** (X8, C2) |
| Citation and coherence checks behind one gate; re-decide, then a refusal row | `validate/prewrite.py` (T66 + H01–H16); re-derive, then `FAILED_CLOSED` | Carry over, plus a defined fail-closed row (C4) |
| Hypothesis property tests and a cache-isolation test | `unittest` with seeded generators; fake-client cache tests | Same idea, different library (Hypothesis is not installed) |
| Tail-window exception, with a test that asserted the breach | No exceptions; invariants as named tests | **Change** (X4, C3) |
| Rules tuned and reported on the same 25 rows | DEV 22 / holdout 10 locked; fixtures reported separately | **Change** (C6) |
| `usage.json` from the locked run | `usage.json` + ledger; `usage_report.md` names the runs that bought the replies | Carry over, extended |
| Prompt text inside code | `agent/prompts/*.md`: role, constraints, refusal values (`UNCERTAIN`, `cannot_answer`), fenced and defanged untrusted text, tool descriptions saying when to use, when not, what returns, read-only | **Change** (C1) |
| No injection handling | Code detector + model flag + fixture F9 | **New** (C4) |
| No linters | `ruff` (complexity limit) + `mypy` in the verifier gate if installable (Q9); stdlib docstring lint either way; a `config.py` tunables table with basis and run IDs | **Change** (C5) |

## 12. What not to build (it scores nothing)
- **Model account picks or tie-breaks.** There is no evidence for the model to use (T4, T39, `research/14` §4.1).
- **A lexical intent phrase table**, even as a cross-check. It is what D3 and T7 flagged, and it fails on pt/ko/ja. The intake row is the cross-check.
- **A Batch client**, unless the measured projection exceeds $80 (§2).
- **`query_snapshot`**, unless `UNKNOWN_FORMAT` ever names a SQL file (0 today).
- **An agent framework or multi-agent handoff.** It is rare even at the top (6.2%, `PLAYBOOK` §1) and adds nothing to defend.
- **Free-text explanations in the output.** The schema has none; rationale stays in the artifacts.
- **A model "second opinion" on settled facts** (T10).
- **More timing refinements** beyond T5 and T53 (mod-60 variants, joint analytics), and any further tie-signal search. G2 found none (`gold_forensics.md` Q7).
- **Per-message effort, the beta tool runner, 1-hour cache TTLs and streaming.** None is needed at these sizes.
- **A top-level `evaluation/` duplicate.** That is packaging (A8, G10), not architecture.

## 13. Open questions for the developer
1. **Q1, architecture:** A+ (text-first routing, recommended) or A, under the §3 switch rule.
2. **Q2, intent fail-closed:** when intent stays `UNCERTAIN`, the call fails, or the budget runs out. Recommended: the engine's deletion-path row, flagged, never NA. The alternative is NA.
3. **Q3, a T66 hard failure (case_33):** (a) a LINK-row alias counts as containment; (b) cite the LINK activity row; (c) keep the finding and mark the row `FAILED_CLOSED`. Never drop the finding.
4. **Q4 (main's):** do REDACTED, ANONYMIZED, DATA_FLOW_DISABLED and RESTORE_BLOCKED verifications fall under the hard check? Only case_46 is affected.
5. **Q5, the `FAILED_CLOSED` row:** an enumerated row class (INCOMPLETE, reason logged, H03 reported), with freeze requiring 0 such rows or your acknowledgement. Recommended.
6. **Q6, T27 in a COMPLETE row** (0 expected): cite through T66's ABSENT branches from pre-audit files, otherwise flag.
7. **Q7, Batch:** only if the 3-case measurement projects more than $80.
8. **Q8, hygiene-lint scope:** `code/deletion_audit/**` and the prompts; `code/evaluation/` exempt (`split.py` must hold the holdout IDs).
9. **Q9, installs:** `anthropic==2.3.0` (pydantic comes with it) is required for GM. `ruff` and `mypy` are needed for C5. Approve the installs, or keep the stdlib docstring lint and drop mypy.
10. **Q10, cross-check source:** the intake CLASSIFY_REQUEST rows only (recommended). The join counts are to be confirmed in G5; expected 10 test, 0 DEV.
11. **Q11, `IMAGE_SUBJECT_CONFLICT`** (case_63 `marketing_001`): include the record with a flag (the catalog link wins), or exclude it (the image wins). `research/15` P6 left this UNKNOWN.
