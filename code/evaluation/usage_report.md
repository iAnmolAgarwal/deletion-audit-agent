# Usage report `reports-final-20261025T1632`

## Headline

Generated from the same run artifacts as the sections below (code/evaluation/headline.py); every number names its run, and a number not yet available says so.

| what | value | run |
|---|---|---|
| DEV status accuracy | 22/22 (1.0000) | `cand-dev-A-20261025T1352` |
| DEV row exact | 19/22 (0.8636) | `cand-dev-A-20261025T1352` |
| DEV step F1 | 0.9887 | `cand-dev-A-20261025T1352` |
| Test rows by status | COMPLETE 153, INCOMPLETE 355, NOT_APPLICABLE 10 (of 518) | `freeze-test-Aplus-20261025T1629` |
| Test FAILED_CLOSED rows | 2 (by reason {'IMAGE_STATE_NOT_SHOWN': 1, 'UNPARSED_DEPENDENCY': 1}) | `freeze-test-Aplus-20261025T1629` |
| Tool-use rate: audit_case | 508/518 (0.9807) cases called audit_case; mode A+, replay-only, paid model calls 0 | `freeze-test-Aplus-20261025T1629` |
| Tool-use rate: other read-only tools | 1/518 (0.0019) cases called another read-only tool (get_request_context, inspect_evidence, lookup_identity, list_activity); mode A+, replay-only, paid model calls 0 | `freeze-test-Aplus-20261025T1629` |
| Tools on vs off (DEV) | A - tools_off: status +0, row exact +0, step F1 +0.0000 (runs `cand-dev-A-20261025T1352` vs `cand-dev-toolsoff-20261025T1352`) | DEV arms |
| Total cost: replies the final output used | $14.102924 for 1283 replies (0 unresolved), bought by `pass1-test-Aplus-shard0-20261025`, `pass1-test-Aplus-shard1-20261025`, `pass1-test-Aplus-shard2-20261025`, `pass1-test-Aplus-shard3-20261025`, `pass1-test-routing-20261025T1325`, `pass1-vision-20261025T1323`, `stage1-routing-20261025T1255` | `freeze-test-Aplus-20261025T1629` |
| Cost per case | $0.027226 over 518 rows | `freeze-test-Aplus-20261025T1629` |
| The final run's own sends | $0.000000 in 0 send attempts | `freeze-test-Aplus-20261025T1629` |
| Holdout | status 9/10 (0.9000), row exact 8/10 (0.8000), step F1 0.9739 | `holdout-20261025T1628` |

> **Holdout caveat (verbatim from `notes/split.json 'created'`):** 2026-10-24 prep session. Made AFTER the prep forensics agent had read all 32 sample answers; stratification used gold status, step count and operations. Rules are re-derived on DEV only; holdout scores are an optimistic estimate.

Generated 2026-10-25T16:32:05+05:30 by `python3 -B code/evaluation/reports.py --spec /private/tmp/claude-501/-Users-anmolagarwal-hackerrank-orchestrate-october26-hackerrank-orchestrate-october26/a5e12cbe-b80b-4f4f-8569-6ab18d22f35c/scratchpad/reports_spec_final.json --publish` from `runs/freeze-test-Aplus-20261025T1629/calls.jsonl`, the reply cache entries it names, the buying runs' call logs and `cache/ledger.jsonl` (code/evaluation/usage_report.py). Every figure names its run. Nothing is typed by hand. Total tokens = input + output + cache read + cache write tokens.

## Required fields (notes/ORGANISER_README.md:97, read as data)

| field | value | section |
|---|---|---|
| Final full-dataset run | run `freeze-test-Aplus-20261025T1629`; the final run wrote 518 rows for 518 test requests (the full dataset) | this table; report title |
| Model providers and names | Anthropic (Messages API): claude-sonnet-5-5 | Providers and models |
| Model calls | (a) 1283 model requests bought the 1283 replies the output used; (b) the run made 0 send attempts (0 returned a reply) and 1569 cache reads | (a), (b) |
| Input and output tokens | (a) 6103637 input, 189565 output; (b) 0 input, 0 output | (a), (b) |
| Total and average tokens per request | (a) total 6293202; 4757.3 input, 147.8 output, 4905.1 total tokens and $0.010992 per reply (over 1283). (b) total 0; no successful send, so no average | (a), (b) |
| Estimated total and per-request cost | (a) $14.102924 settled ($14.102924 re-priced), per reply $0.010992; (b) $0.000000, per successful send n/a (no successful send). Estimated from the price table below | (a), (b), Price basis |
| Per-model and overall totals | 1 model(s) in (a), 0 in (b); each part has a per-model table and an overall total row | (a), (b) |

## Providers and models

- Provider: Anthropic (Messages API).
- Models of the replies used (run `freeze-test-Aplus-20261025T1629`): claude-sonnet-5-5.
- Models of the run's own successful sends: none.

## (a) Tokens and cost originally spent on the replies this run used

Run `freeze-test-Aplus-20261025T1629` used 897 distinct replies in 1569 uses (cache hits and successful sends); 0 could not be followed to a cache entry. Each reply is summed once, under the run that bought it; tokens are the cache entry's original usage.

| bought by run | replies | uses | input_tokens | output_tokens | cache_read_input_tokens | cache_creation_input_tokens | output_tokens_details.thinking_tokens | total_tokens | cost settled | cost re-priced |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `pass1-test-Aplus-shard0-20261025` | 127 | 127 | 641745 | 12466 | 0 | 0 | 0 | 654211 | $1.408150 | $1.408150 |
| `pass1-test-Aplus-shard1-20261025` | 127 | 127 | 642434 | 12458 | 0 | 0 | 0 | 654892 | $1.409448 | $1.409448 |
| `pass1-test-Aplus-shard2-20261025` | 130 | 130 | 655283 | 12791 | 0 | 0 | 99 | 668074 | $1.438476 | $1.438476 |
| `pass1-test-Aplus-shard3-20261025` | 127 | 127 | 642415 | 12456 | 0 | 0 | 0 | 654871 | $1.409390 | $1.409390 |
| `pass1-test-routing-20261025T1325` | 736 | 992 | 3355122 | 126325 | 0 | 0 | 0 | 3481447 | $7.973494 | $7.973494 |
| `pass1-vision-20261025T1323` | 22 | 22 | 102748 | 10620 | 0 | 0 | 0 | 113368 | $0.311696 | $0.311696 |
| `stage1-routing-20261025T1255` | 14 | 44 | 63890 | 2449 | 0 | 0 | 0 | 66339 | $0.152270 | $0.152270 |
| **total** | 1283 | 1569 | 6103637 | 189565 | 0 | 0 | 99 | 6293202 | $14.102924 | $14.102924 |

- Model requests behind these replies: 1283 (one per reply).
- Per request (per reply): 4757.3 input, 147.8 output, 4905.1 total tokens and $0.010992 per reply (over 1283).

Per model:

| model | replies | uses | input_tokens | output_tokens | cache_read_input_tokens | cache_creation_input_tokens | output_tokens_details.thinking_tokens | total_tokens | cost settled |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| claude-sonnet-5-5 | 1283 | 1569 | 6103637 | 189565 | 0 | 0 | 99 | 6293202 | $14.102924 |
| **overall** | 1283 | 1569 | 6103637 | 189565 | 0 | 0 | 99 | 6293202 | $14.102924 |

## (b) Calls made by run `freeze-test-Aplus-20261025T1629` itself

- Model calls (send attempts): 0 (0 returned a reply); cache hits: 1569. Cost of the sends: $0.000000.
- Events (event:outcome): {'cache_hit:ok': 1569}.
- Per request (per successful send): no successful send, so no average.

| send tokens | input_tokens | output_tokens | cache_read_input_tokens | cache_creation_input_tokens | output_tokens_details.thinking_tokens | total_tokens |
|---|---:|---:|---:|---:|---:|---:|
| all send attempts | 0 | 0 | 0 | 0 | 0 | 0 |

Failures (event:outcome:error class:HTTP status):

- none

Per model (successful sends):

| model | sends ok | cost | input_tokens | output_tokens | cache_read_input_tokens | cache_creation_input_tokens | output_tokens_details.thinking_tokens | total_tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **overall (all send attempts)** | 0 | $0.000000 | 0 | 0 | 0 | 0 | 0 | 0 |

## Price basis

USD per million tokens, from `code/deletion_audit/model/prices.py` (the budget guard's table). Its stated source: Source for every price: ``research/13_sonnet55_api_facts.md`` §2, confirmed by ``research/verify/13_verify.md`` C20-C24 (platform.claude.com/docs/en/about-claude/pricing and claude.com/pricing, checked 2026-10-24). Synchronous Messages API rates, USD per million tokens.

| model | input | output | cache write 5m | cache write 1h | cache read |
|---|---:|---:|---:|---:|---:|
| claude-sonnet-5-5 | 2.0 | 10.0 | 2.5 | 4.0 | 0.1 |

## Cross-checks

- Per reply, settled cost vs re-priced usage vs ledger: all agree.
- Run `freeze-test-Aplus-20261025T1629` send cost $0.000000 vs the ledger lines for its 0 sent key(s) $0.000000: agree.
- Whole ledger (1412 lines) $15.461994 vs every send in 103 call log(s) under runs/ $15.461994: agree.
- `usage.json` of `freeze-test-Aplus-20261025T1629`: agrees with the call log.

