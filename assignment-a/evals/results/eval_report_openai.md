# Assistant evaluation report
run: 2026-09-18 01:31 IST  git: d0f9a86  mode: provider: openai gpt-5.4-mini  questions: 36

## Summary
| metric | tuned (n=24) | held-out (n=12) |
|---|---|---|
| intent accuracy | 24/24 (100%) | 12/12 (100%) |
| params correct | 24/24 (100%) | 12/12 (100%) |
| numbers match (pre-guard) | 16/16 (100%) | 5/7 (71%) |
| numbers match (post-guard) | 16/16 (100%) | 7/7 (100%) |
| decline correct | 24/24 (100%) | 12/12 (100%) |
| ask correct | 24/24 (100%) | 12/12 (100%) |
| golden values (pinned) | 3/3 (100%) | – |
| guard rejections | 0 | 2 |
| route fell back to rules | 0 | 3 |
| latency p50 / p95 / max (reported, not gated) | 2568 / 3264 / 3760 ms | 1830 / 6852 / 6852 ms |
| provider calls | 40 | 17 |
| thresholds | PASS | not gated (diagnostic) |

Numbers match = every number in the reply traces to the calculator's result for the expected inputs, and the headline answer is stated. Pre-guard scores the provider's draft; post-guard scores what the user sees.
Golden values = the brief's worked examples, hand-pinned; they fail on purpose if a domain constant changes.

> The **tuned** set is the set the rule router was fitted on, so its score measures fit, not generalisation. The **held-out** set was written afterwards from phrasings the router never saw; it is reported honestly and is not a pass/fail gate. Read the held-out column as the realistic offline accuracy.

## Per question — tuned (questions.jsonl)
| id | category | intent | params | numbers (pre/post) | decline/ask | golden | route/phrase | guard | ms |
|---|---|---|---|---|---|---|---|---|---|
| yq-01 | yarn_quantity | ✓ | ✓ | ✓ / ✓ | ✓ | ✓ | llm/llm | pass | 3760 |
| yq-02 | yarn_quantity | ✓ | ✓ | ✓ / ✓ | ✓ | – | llm/llm | pass | 2690 |
| yq-03 | yarn_quantity | ✓ | ✓ | ✓ / ✓ | ✓ | – | llm/llm | pass | 2568 |
| yq-04 | yarn_quantity | ✓ | ✓ | ✓ / ✓ | ✓ | – | llm/llm | pass | 2882 |
| yq-05 | yarn_quantity | ✓ | ✓ | ✓ / ✓ | ✓ | – | llm/llm | pass | 2967 |
| yq-06 | yarn_quantity | ✓ | ✓ | ✓ / ✓ | ✓ | – | llm/llm | pass | 3258 |
| yq-07 | yarn_quantity | ✓ | ✓ | ✓ / ✓ | ✓ | – | llm/llm | pass | 2867 |
| yq-08 | yarn_quantity | ✓ | ✓ | ✓ / ✓ | ✓ | – | llm/llm | pass | 2268 |
| nr-01 | needle_recommendation | ✓ | ✓ | ✓ / ✓ | ✓ | ✓ | llm/llm | pass | 2971 |
| nr-02 | needle_recommendation | ✓ | ✓ | ✓ / ✓ | ✓ | – | llm/llm | pass | 2354 |
| nr-03 | needle_recommendation | ✓ | ✓ | ✓ / ✓ | ✓ | – | llm/llm | pass | 3225 |
| nr-04 | needle_recommendation | ✓ | ✓ | ✓ / ✓ | ✓ | – | llm/llm | pass | 2510 |
| nr-05 | needle_recommendation | ✓ | ✓ | ✓ / ✓ | ✓ | – | llm/llm | pass | 2754 |
| td-01 | tension_diagnosis | ✓ | ✓ | ✓ / ✓ | ✓ | ✓ | llm/llm | pass | 2777 |
| td-02 | tension_diagnosis | ✓ | ✓ | ✓ / ✓ | ✓ | – | llm/llm | pass | 3264 |
| td-03 | tension_diagnosis | ✓ | ✓ | ✓ / ✓ | ✓ | – | llm/llm | pass | 3213 |
| ask-01 | missing_input | ✓ | ✓ | – / – | ✓ | – | llm/none | – | 1227 |
| ask-02 | missing_input | ✓ | ✓ | – / – | ✓ | – | llm/none | – | 1287 |
| ask-03 | missing_input | ✓ | ✓ | – / – | ✓ | – | llm/none | – | 2168 |
| dec-01 | unsupported | ✓ | ✓ | – / – | ✓ | – | llm/none | – | 1329 |
| dec-02 | unsupported | ✓ | ✓ | – / – | ✓ | – | llm/none | – | 1534 |
| dec-03 | unsupported | ✓ | ✓ | – / – | ✓ | – | llm/none | – | 1660 |
| dec-04 | unsupported | ✓ | ✓ | – / – | ✓ | – | llm/none | – | 1192 |
| dec-05 | unsupported | ✓ | ✓ | – / – | ✓ | – | llm/none | – | 1856 |

### Failures (raw) — tuned
None.

## Per question — held-out (held_out.jsonl)
| id | category | intent | params | numbers (pre/post) | decline/ask | golden | route/phrase | guard | ms |
|---|---|---|---|---|---|---|---|---|---|
| ho-01 | yarn_quantity | ✓ | ✓ | ✓ / ✓ | ✓ | – | llm/llm | pass | 3175 |
| ho-02 | yarn_quantity | ✓ | ✓ | ✗ / ✓ | ✓ | – | llm/template | REJECTED | 6852 |
| ho-03 | missing_input | ✓ | ✓ | – / – | ✓ | – | llm/none | – | 2362 |
| ho-04 | yarn_quantity | ✓ | ✓ | ✓ / ✓ | ✓ | – | llm/llm | pass | 2657 |
| ho-05 | yarn_quantity | ✓ | ✓ | ✓ / ✓ | ✓ | – | rules/template | pass | 1437 |
| ho-06 | unsupported | ✓ | ✓ | – / – | ✓ | – | rules/none | – | 1537 |
| ho-07 | yarn_quantity | ✓ | ✓ | ✓ / ✓ | ✓ | – | rules/template | pass | 1213 |
| ho-08 | tension_diagnosis | ✓ | ✓ | ✗ / ✓ | ✓ | – | llm/template | REJECTED | 2452 |
| ho-09 | unsupported | ✓ | ✓ | – / – | ✓ | – | llm/none | – | 1647 |
| ho-10 | missing_input | ✓ | ✓ | – / – | ✓ | – | llm/none | – | 1241 |
| ho-11 | yarn_quantity | ✓ | ✓ | ✓ / ✓ | ✓ | – | llm/llm | pass | 2250 |
| ho-12 | unsupported | ✓ | ✓ | – / – | ✓ | – | llm/none | – | 1830 |

### Failures (raw) — held-out
#### ho-02
- params: `{"width_cm": 40.0, "height_cm": 40.0, "weight": "medium", "stitch": "stockinette", "gauge_sts_10cm": 20.0}` missing: `[]`
- expected result: `{"metres": 215.1, "balls": 2}`
- draft: 'You’ll need about 215.1 m, which is 2 balls. A 10% safety margin is included for swatching and dye lots, and the ball count assumes a 100 m ball, so if yours is different the exact count may change.'
- reply: "For a 40cm x 40cm piece in stockinette (medium weight), you'll need about 215.1m of yarn -- roughly 2 balls of 100g / 200m. If your balls are a different length, tell me and I'll redo the count."
#### ho-08
- params: `{"actual_sts_10cm": 20.0, "target_sts_10cm": 18.0}` missing: `[]`
- expected result: `{"diagnosis": "too tight", "direction": "up", "severity": "major", "diff_pct": 11.1, "suggested_needle_change_mm": 0.5, "fixes": ["change_needle_size", "check_needle_material", "reswatch_after_blocking", "relax_tension_habits"]}`
- draft: 'Your gauge is too tight, and it’s a major difference by 11.1. You’ll likely need to change needle size, and one needle size is assumed to change gauge by about 1 stitch per 10cm.'
- reply: 'Your gauge is too tight (major, 11.1% off target). Go up about 0.5mm in needle size, then reswatch. Other things to try: check needle material, reswatch after blocking, relax tension habits.'
