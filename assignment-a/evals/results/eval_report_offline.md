# Assistant evaluation report
run: 2026-09-19 15:49 IST  git: cd6144d  mode: offline (rules + templates)  questions: 36

## Summary
| metric | tuned (n=24) | held-out (n=12) |
|---|---|---|
| intent accuracy | 24/24 (100%) | 12/12 (100%) |
| params correct | 24/24 (100%) | 12/12 (100%) |
| numbers match (pre-guard) | 16/16 (100%) | 7/7 (100%) |
| numbers match (post-guard) | 16/16 (100%) | 7/7 (100%) |
| decline correct | 24/24 (100%) | 12/12 (100%) |
| ask correct | 24/24 (100%) | 12/12 (100%) |
| golden values (pinned) | 3/3 (100%) | – |
| guard rejections | 0 | 0 |
| route fell back to rules | 0 | 0 |
| latency p50 / p95 / max (reported, not gated) | 0 / 0 / 3 ms | 0 / 0 / 0 ms |
| provider calls | 0 | 0 |
| thresholds | PASS | not gated (diagnostic) |

Numbers match = every number in the reply traces to the calculator's result for the expected inputs, and the headline answer is stated. Pre-guard scores the provider's draft; post-guard scores what the user sees.
Golden values = the brief's worked examples, hand-pinned; they fail on purpose if a domain constant changes.

> The **tuned** set is the set the rule router was fitted on, so its score measures fit, not generalisation. The **held-out** set was written afterwards from phrasings the router never saw; it is reported honestly and is not a pass/fail gate. Read the held-out column as the realistic offline accuracy.

## Per question — tuned (questions.jsonl)
| id | category | intent | params | numbers (pre/post) | decline/ask | golden | route/phrase | guard | ms |
|---|---|---|---|---|---|---|---|---|---|
| yq-01 | yarn_quantity | ✓ | ✓ | ✓ / ✓ | ✓ | ✓ | rules/template | pass | 3 |
| yq-02 | yarn_quantity | ✓ | ✓ | ✓ / ✓ | ✓ | – | rules/template | pass | 0 |
| yq-03 | yarn_quantity | ✓ | ✓ | ✓ / ✓ | ✓ | – | rules/template | pass | 0 |
| yq-04 | yarn_quantity | ✓ | ✓ | ✓ / ✓ | ✓ | – | rules/template | pass | 0 |
| yq-05 | yarn_quantity | ✓ | ✓ | ✓ / ✓ | ✓ | – | rules/template | pass | 0 |
| yq-06 | yarn_quantity | ✓ | ✓ | ✓ / ✓ | ✓ | – | rules/template | pass | 0 |
| yq-07 | yarn_quantity | ✓ | ✓ | ✓ / ✓ | ✓ | – | rules/template | pass | 0 |
| yq-08 | yarn_quantity | ✓ | ✓ | ✓ / ✓ | ✓ | – | rules/template | pass | 0 |
| nr-01 | needle_recommendation | ✓ | ✓ | ✓ / ✓ | ✓ | ✓ | rules/template | pass | 0 |
| nr-02 | needle_recommendation | ✓ | ✓ | ✓ / ✓ | ✓ | – | rules/template | pass | 0 |
| nr-03 | needle_recommendation | ✓ | ✓ | ✓ / ✓ | ✓ | – | rules/template | pass | 0 |
| nr-04 | needle_recommendation | ✓ | ✓ | ✓ / ✓ | ✓ | – | rules/template | pass | 0 |
| nr-05 | needle_recommendation | ✓ | ✓ | ✓ / ✓ | ✓ | – | rules/template | pass | 0 |
| td-01 | tension_diagnosis | ✓ | ✓ | ✓ / ✓ | ✓ | ✓ | rules/template | pass | 0 |
| td-02 | tension_diagnosis | ✓ | ✓ | ✓ / ✓ | ✓ | – | rules/template | pass | 0 |
| td-03 | tension_diagnosis | ✓ | ✓ | ✓ / ✓ | ✓ | – | rules/template | pass | 0 |
| ask-01 | missing_input | ✓ | ✓ | – / – | ✓ | – | rules/none | – | 0 |
| ask-02 | missing_input | ✓ | ✓ | – / – | ✓ | – | rules/none | – | 0 |
| ask-03 | missing_input | ✓ | ✓ | – / – | ✓ | – | rules/none | – | 0 |
| dec-01 | unsupported | ✓ | ✓ | – / – | ✓ | – | rules/none | – | 0 |
| dec-02 | unsupported | ✓ | ✓ | – / – | ✓ | – | rules/none | – | 0 |
| dec-03 | unsupported | ✓ | ✓ | – / – | ✓ | – | rules/none | – | 0 |
| dec-04 | unsupported | ✓ | ✓ | – / – | ✓ | – | rules/none | – | 0 |
| dec-05 | unsupported | ✓ | ✓ | – / – | ✓ | – | rules/none | – | 0 |

### Failures (raw) — tuned
None.

## Per question — held-out (held_out.jsonl)
| id | category | intent | params | numbers (pre/post) | decline/ask | golden | route/phrase | guard | ms |
|---|---|---|---|---|---|---|---|---|---|
| ho-01 | yarn_quantity | ✓ | ✓ | ✓ / ✓ | ✓ | – | rules/template | pass | 0 |
| ho-02 | yarn_quantity | ✓ | ✓ | ✓ / ✓ | ✓ | – | rules/template | pass | 0 |
| ho-03 | missing_input | ✓ | ✓ | – / – | ✓ | – | rules/none | – | 0 |
| ho-04 | yarn_quantity | ✓ | ✓ | ✓ / ✓ | ✓ | – | rules/template | pass | 0 |
| ho-05 | yarn_quantity | ✓ | ✓ | ✓ / ✓ | ✓ | – | rules/template | pass | 0 |
| ho-06 | unsupported | ✓ | ✓ | – / – | ✓ | – | rules/none | – | 0 |
| ho-07 | yarn_quantity | ✓ | ✓ | ✓ / ✓ | ✓ | – | rules/template | pass | 0 |
| ho-08 | tension_diagnosis | ✓ | ✓ | ✓ / ✓ | ✓ | – | rules/template | pass | 0 |
| ho-09 | unsupported | ✓ | ✓ | – / – | ✓ | – | rules/none | – | 0 |
| ho-10 | missing_input | ✓ | ✓ | – / – | ✓ | – | rules/none | – | 0 |
| ho-11 | yarn_quantity | ✓ | ✓ | ✓ / ✓ | ✓ | – | rules/template | pass | 0 |
| ho-12 | unsupported | ✓ | ✓ | – / – | ✓ | – | rules/none | – | 0 |

### Failures (raw) — held-out
None.
