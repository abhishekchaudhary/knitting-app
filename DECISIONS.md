# DECISIONS.md

> Brief §5: key technical choices and trade-offs, domain assumptions and sources, why these LLM and image providers, and how numeric accuracy is guaranteed in Assignment A.

## 1. Decisions

| # | Decision | Options considered | Choice | Why | Revisit when | Status |
|---|---|---|---|---|---|---|
| D1 | LLM provider (A) | Anthropic · OpenAI · local model | OpenAI `gpt-5.4-mini` (`reasoning_effort=none`) behind `LLMProvider`, with the rule router + templates as the built-in fallback | One key covers A and B. Structured output (strict JSON schema) makes routing checkable. Eval: 24/24 intent, 16/16 numbers, p95 ≈ 3.4 s ([report](assignment-a/evals/results/eval_report_openai.md), run 2026-09-17 at commit `ab5c59e`, before the later router and guard changes; not re-run since) | Intent accuracy < 93%, or a second vendor is needed | decided |
| D2 | Image provider (B) | OpenAI images · Stability · Flux · Gemini | OpenAI `gpt-image-1-mini`, `quality=low`, 1024×1024, behind `ImageProvider` | Compared with `gpt-image-2` on the brief's cable swatch in two runs (§1c): both drew convincing cables; mini was faster (10.9 / 11.2 s vs 13.4 / 15.1 s) and ~4× cheaper per image token ($8 vs $30 per 1M). `gpt-image-2` held colour a little better (ΔE 7.1 / 9.9 vs 8.7 / 13.9), a gap the tint check closes | Zoomed hero image needs more detail → try `quality=medium` or `gpt-image-2` for the zoom tier only | decided (OpenAI chosen for one key across A and B; the model within it was chosen by the side-by-side run in §1c on 2026-09-17) |
| D3 | Assistant UI | CLI · Streamlit · notebook | CLI with a "how this was calculated" trace, `--json`, `--offline` | Fastest, clean on video, scriptable for the eval | — | decided |
| D4 | Swatch UI | notebook · script | Jupyter notebook, cells in video order | Brief says a notebook is enough; images inline | — | decided |
| D5 | Cache | filesystem · sqlite · S3 | Filesystem, `sha256(canonical JSON)` key | Zero infra; the same key works as an S3 object key behind a CDN | More than one server | decided |
| D6 | Config format | YAML + pydantic · JSON · Python constants | YAML + pydantic (`domain.yaml`, `config.yaml`, `prompts.yaml`) | Human-editable without touching Python; validated at import | — | decided |
| D7 | Ravelry auth | Basic Auth (read-only) · OAuth 2.0 | Read-only Basic Auth; OAuth2 bearer supported via `RAVELRY_AUTH=oauth2` | Server-side, read-only search; no user login flow | Per-user features (stash, favourites) | decided |
| D8 | Python version | 3.11 · 3.12 | 3.12 locally; code targets 3.11+ | System Python is 3.9 | — | decided |
| D9 | Brief in repo | commit · gitignore | gitignored (`docs/brief/`) | Company document; repo may be public | — | decided |
| D10 | Scope | core only · core + bonuses | Core requirements plus three of the four bonuses: structure-once tint, cost estimate, cache warming. The content-safety check is left out (README) | The tint path answers the latency tension in brief §4.2; the cost estimate feeds the go-live section | — | decided |
| D11 | Eval question sets | one set · tuned + held-out | Two sets: `questions.jsonl` (n=24, the set the rule router was built against) and `held_out.jsonl` (n=12, written afterwards), reported in separate columns; only the tuned set gates | A 100% on the set you tuned on measures fit, not accuracy, and a CTO will say so. Gating the held-out set would create pressure to tune on it, which destroys the only honest number in the report. It is a diagnostic: if it drops, that is the signal to look | Held-out drops below the tuned column by more than a couple of points, or the set grows past ~30 and can be split into gate + diagnostic | decided |
| D12 | Dependency pinning | floors only · lock file | Keep `>=` floors in the two `requirements.txt`, add `requirements.lock` (`pip freeze`) as the reproducible install | The code passes recent OpenAI SDK parameters, so a fresh clone resolving a different major would fail in a way that looks like our bug. The floors stay so the direct dependencies are still readable | A packaging tool (uv/poetry) is introduced, or CI pins per-platform | decided |
| D13 | Config validation | lazy (`KeyError` at call time) · strict at import | pydantic models with `extra="forbid"`, cross-checks (`Stitch.fallback` exists in `fallback.PATTERNS`, `default_project` / `default_fabric` exist) run when `domain.yaml` / `config.yaml` load | These files are meant to be edited by hand. A typo should fail on the next import with the field name, not five cells later inside a demo as a `KeyError` the audience has to watch us debug. Cost is a slightly noisier import error for a valid-but-unknown key | Config is edited by non-engineers at runtime; then it needs a UI with the same checks | decided |

## 1a. Vendor strategy: fallback by design, not one vendor by accident
The POC uses one AI vendor (OpenAI) for both assignments. The architecture does not depend on it:

- **Interfaces first.** Assignment A calls `LLMProvider`; Assignment B calls `ImageProvider`. No SDK is imported outside the two `providers.py` files. A second vendor is one new class plus one env value.
- **A working degraded mode for each capability.**
  - A: if OpenAI times out, errors, returns an invalid route, or its draft fails the guard, that step falls back to rules/templates. Answers stay correct because the calculators do the maths. Every reply records `route=llm|rules` and `phrase=llm|template`; the eval counts fallbacks.
  - B: cache first, then generate, then a placeholder in the target colour. An outage never leaves the screen blank, and failures are not cached, so the next tap retries.
- **Known risk: one vendor for both.** An OpenAI outage hits A and B at the same moment; each drops to its own degraded mode. The hardened stage adds a second vendor per capability and an ordered provider chain with timeouts and a circuit breaker (README → "What I left out").
- **Models and prices live in config** (`OPENAI_MODEL`, `OPENAI_IMAGE_MODEL`, `IMAGE_QUALITY`, `config.yaml → cost`), so a model or tier change is a one-line edit.

## 1b. Assignment A: the LLM reads and writes, code computes
- **Routing.** The LLM returns a strict JSON schema whose enums (weights, stitches, projects, decline categories) are generated from `domain.yaml` and the router. `router.intent_from_llm()` then accepts the reading only if:
  - every number the LLM extracted appears in the question, and a gauge sits next to "sts"/"stitches"/"gauge";
  - a weight, stitch, project or fabric is actually named in the question. If not, it is dropped, so a missing weight gets asked for rather than guessed;
  - units come from the question text wherever it states one, and conversion (in, m → cm) happens in code;
  - wherever the rule router can also read a value, both readings agree. Two independent readers must match; this catches swapped width/height and misread units.

  Otherwise the rule router answers. Declines use a fixed reason per category, so no LLM-written text is ever shown in a decline.
- **Phrasing.** The phraser prompt sees only the `CalcResult` JSON and is told which values must lead (per intent). Prompts live in `assistant/prompts.yaml`.
- **Why the guard matters, with evidence.** The first version of the phraser prompt listed the headline rules for all three intents at once. The model then mixed intents and, for the tension question, invented a needle size ("4.0 mm, US 6, UK 8"). The guard rejected 5 of 16 drafts and the user saw the template reply every time (post-guard 16/16). The prompt was fixed to send only the current intent's rule; pre-guard went to 16/16.
- **Live evidence, current run (2026-09-18, gpt-5.4-mini, 36 questions).** On the held-out questions the model produced two drafts whose numbers did not trace to the calculator, and the guard replaced both: for a 40 x 40 cm worsted piece it wrote "the ball count assumes a 100 m ball" when the configured put-up is 200 m per 100 g ball, and for a tension question it wrote "a major difference by 11.1" with no unit and dropped the needle change entirely. Pre-guard number-match on that set was 5/7; post-guard it was 7/7, so no reader saw either draft. The tuned set stayed 16/16 on both sides. This is the metric to watch: a rising gap between pre- and post-guard means the prompt is drifting, and the guard is absorbing it.
- **Missing inputs are asked for, not guessed.** Both routers return the intent with a `missing` list; the reply asks for exactly those fields (eval "ask correct" 24/24).

## 1c. Assignment B: structure once, colour fast, always something to show
| Choice | Why |
|---|---|
| Prompt order: stitch structure → colour (hex + RGB + words) → weight → fibre → fixed photo suffix (`config.yaml`) | Stitch and colour are the must-respect inputs; image models follow colour words better than hex, and negative phrases ("no ridges") stop drift to plain stockinette |
| Colour check: CIEDE2000 between the target hex and the median LAB of the centre 60% crop; tint if ΔE > 12 | Measures the dyed yarn, not shadows or vignettes. In the demo run forest green came back at ΔE 14.8 and was tinted to 0.3 |
| Structure-once-then-tint (`get_swatch_fast`) | One grey master per stitch/weight/fibre (≈ 10 s, cached), then each colour is a LAB shift: ~55 ms (≈ 60 ms including the master lookup) per colour on the 512 px cached master vs ~10 s per generation. The first colour pays once for the master. Trade-off: tinted swatches look slightly flatter and lighter than generated ones, so tint is for instant switching, with the generated image swapped in when ready |
| Cache key: stitch, hex, weight, fibre, model, quality, size and a hash of the prompt (not the colour name) | Hex is the source of truth; model, quality and size change the image; hashing the prompt means editing `config.yaml` wording never serves a stale image. Corrupt entries are treated as a MISS; writes are atomic |
| Placeholder: procedural pattern per stitch in the target hex, never cached; any generation error (API, decode, unexpected) lands here | Shows *something* in the right colour and rough structure immediately; a retry can still succeed |
| No key ⇒ `offline` provider | Serves the committed example images from `cache/` (same model/quality key space) and the placeholder for anything else, so a run without keys still shows real images |
| Ravelry: stitch keyword → first pattern with a photo; timeout, HTTP error, no key and no match all return `None` with a `RAVELRY status=…` log | Brief allows a loose match; the reference is a nice-to-have and must never block the preview |
| Model comparison (brief cable, royal purple, `quality=low`, two runs) | `gpt-image-1-mini`: 10.9 s / ΔE 8.7, then 11.2 s / ΔE 13.9 (tinted to 0.2) · `gpt-image-2`: 13.4 s / ΔE 7.1, then 15.1 s / ΔE 9.9. Both draw convincing cables; `gpt-image-2` draws more intricate plaits and holds colour better. Of the comparison runs only the `gpt-image-2` second run is committed (`assignment-b/cache/0bc1dd95…`, 15.1 s, ΔE 9.94); the committed `gpt-image-1-mini` cable/royal-purple image (`c18d4c77…`, 10.4 s, ΔE 9.85) is a later demo run, not a comparison run |
| Cost (notebook cell 9) | 156–163 prompt + 272 image tokens (measured across the seven committed images; the prompt length varies with stitch and colour words) → **$0.0025/image** at 162 prompt tokens (`gpt-image-1-mini`: $2/1M text in, $8/1M image out, OpenAI pricing page, checked 2026-09-17). 2,000 previews/day: $150/month uncached, $60 with a 60% cache hit rate, $0.98 one-off for 392 tint masters |

## 2. Numeric accuracy guarantee (Assignment A)
The phraser (LLM or template) only ever sees a `CalcResult`; it never computes. Every number the calculator used is a named field (`CalcResult.named_values()`): the result, the inputs, and the constants it applied (ball size, typical gauge, multiplier, safety margin %, target mm). `CalcResult.result` is the narrower set: the computed answers only. Before a reply reaches the user, `assistant/guard.py` runs `problems(draft, calc)`, which must come back empty:

1. **Reads each number with its label.** A label is a unit after the number (`429 m`, `4 balls`, `9.1%`, `5.0mm`, `22.5 sts`, `50g`, `60in`) or a prefix (`US 8`). Spelled-out numbers next to a unit ("twelve balls") count too. Knitting notation is removed first, so `1x1`, `k2p2`, `4 ply` and "3 needle sizes" are neither checked nor reported.
2. **Checks labelled numbers against fields of their own kind.** Metres only match metres fields, ball counts only `balls`, mm only needle fields, % only `diff_pct` / `safety_margin_pct`, sts only gauge fields, US/UK only their own. Tolerance is per kind and mostly absolute, not a percentage: counts, grams and US/UK sizes must be exact; mm within ±0.05; **metres within ±0.5 m absolute** (a 5% relative window would have let "446 m" pass for 429 m); sts within ±0.05; % within ±0.15. So "60 balls" fails even though 60 is the input height, and "3.5mm" fails for a 4.0 mm answer.
3. **Requires an unlabelled number to be an answer.** It must match a value in `CalcResult.result` within ±0.05 — not an input, not a constant, not the gauge-width values. A bare "60" is a leak even though the question said 60 cm.
4. **Requires the headline, per intent.** Yarn: both the metres and the ball count must appear, each with its unit. Needles: the recommended `metric_mm` must appear as mm — quoting only the range minimum is a rejection. Tension: the diagnosis word (`tight` / `loose` / `gauge`) must appear, `diff_pct` must appear as a percentage, **and the opposite diagnosis must not appear** — a draft that says "loose" about a too-tight gauge is rejected even though every number in it is correct.
5. **Falls back on any problem.** `assistant.answer()` discards the draft and returns `phraser.template_reply()`, built only from `CalcResult`. The rejection is logged with the reason list (`number:446`, `headline:balls`, `contradiction:loose`).

**Result: no reply can show a number, or a number in a unit, that the calculator did not produce, and no reply can omit or contradict the headline it was asked for.**

Evidence:
- `assignment-a/tests/test_guard.py`: honest phrasings pass; the attack strings are caught ("60 balls", "900g", "3 balls", "twelve balls", "US 7", "20% off", "$45", "446 m" for 429 m, a bare input number, a reply that states the range minimum as the recommendation, and a "too loose" draft for a too-tight gauge).
- `test_assistant.py` and `test_providers.py`: a leaky draft, an invented input, a swapped reading and a provider outage all end in a correct reply.
- The eval applies the same headline rule and scores before and after the guard: offline tuned 16/16 and held-out 7/7, both pre- and post-guard ([offline report](assignment-a/evals/results/eval_report_offline.md)).
- In the log: `ASSISTANT intent=… route=… phrase=… guard=pass|REJECTED leaked=[…]`.

**What the guard still cannot catch.** It checks the reply against the calculation, never the calculation against the question — if the router misreads "baby blanket" as baby-weight yarn, the guard passes a perfectly consistent answer to the wrong question. Within the reply, it enforces the headline and the diagnosis direction but not every subordinate claim: a correct value in the correct unit can still be attached to the wrong sentence (e.g. the ball *weight* described as the ball *length*, or a fix listed in the wrong order of preference). And it says nothing about non-numeric advice. The next step is to have the LLM fill labelled slots that code renders, so prose structure is code, not text (README → "What I left out").

## 3. Domain assumptions and sources
One row per constant block in `assignment-a/knitcalc/domain.yaml`. Published tables were checked on 2026-09-17.
Sources: [CYC Standard Yarn Weight System](https://www.craftyarncouncil.com/standards/yarn-weight-system) · [CYC needle and hook sizes](https://www.craftyarncouncil.com/standards/hooks-and-needles) · [Vogue Knitting needle chart](https://www.vogueknitting.com/pattern-help/how-to/techniques-abbreviations/knitting-needles/).

| Constant | Value | Source | Approximation? | How to calibrate |
|---|---|---|---|---|
| `units.cm_per_inch` | 2.54 | 1959 international yard agreement (exact) | No | — |
| `units.gauge_width_cm` / `gauge_width_in` | 10 cm and 4 in, treated as two labels for the same swatch width, not as a conversion | CYC prints the gauge label as "sts per 4 inches (10 cm)" ([CYC weight table](https://www.craftyarncouncil.com/standards/yarn-weight-system)) | Yes, 1.6% arithmetic gap (4 in = 10.16 cm) | Deliberately not converted: "20 sts to 4in" is read as 20 sts per 10 cm (`question_reader.GAUGE_PER_4IN`, eval row ho-02). Rescaling would move every published gauge by 1.6%, well below the ±1 st a knitter can measure |
| `weights[].gauge_sts_10cm` | Lace 33–40 · Super Fine 27–32 · Fine 23–26 · Light 21–24 · Medium 16–20 · Bulky 12–15 · Super Bulky 7–11 · Jumbo ≤6 | CYC weight table | No (Jumbo lower bound 3 is ours, see below) | — |
| `weights[].needle_mm` / `us_needle` | Lace 1.5–2.25 (000–1) · SF 2.25–3.25 (1–3) · Fine 3.25–3.75 (3–5) · Light 3.75–4.5 (5–7) · Medium 4.5–5.5 (7–9) · Bulky 5.5–8 (9–11) · SB 8–12.75 (11–17) · Jumbo ≥12.75 (≥17) | CYC weight table | No (Jumbo upper bound 25 mm is ours) | — |
| `weights[jumbo]` closed bounds | gauge 3–6, needles 12.75–25 mm | ASSUMPTION: CYC bounds are open-ended | Yes | Read the ball label |
| `weights[].typical_gauge` | Midpoint of the CYC range (22.5 for DK) | Derived from CYC | Yes | The user's own gauge overrides it |
| `weights[].aliases` | dk→Light, worsted/aran→Medium, fingering/sock/4ply→Super Fine, chunky→Bulky, baby→Super Fine, roving→Super Bulky | CYC yarn-type column; UK/AU ply names are common usage | `baby` and `roving` are ambiguous in CYC | Ask the user if the answer matters |
| `weights[].m_per_100cm2` | 22 / 20 / 16 / 13 / 11 / 9 / 7 / 5 | Our estimate from typical pattern yardages | **Yes** | Calibration table below |
| `weights[].ball` | 50g/400m · 100g/400m · 50g/150m · 50g/120m · 100g/200m · 100g/100m · 100g/70m · 200g/60m | Typical retail put-ups | **Yes** | The user's own ball size should override it (future inventory) |
| `needles.rows` | 24 rows, 1.5–25 mm | mm↔US: CYC; UK: Vogue Knitting | No. Where the two disagree (US 17 = 12 vs 12.75 mm, US 19 = 16 vs 15 mm) we follow CYC | — |
| `stitches.items[].multiplier` | stockinette 1.00 · garter 1.10 · seed 1.10 · rib 1x1 1.20 · rib 2x2 1.15 · cable 1.35 · lace 0.85 | Common knitting advice; no single published table | **Yes** (ranges in YAML) | 3 published patterns per stitch |
| plain "rib" alias | means 1x1 | ASSUMPTION | Yes | Ask if it matters |
| `yarn_quantity.safety_margin` | 0.10 | Common advice: 10–15% extra | **Yes** | Raise to 0.15 if we under-estimate |
| `needle_recommender.fabric` | firm 0.15 · balanced 0.50 · drapey 0.85 (position inside the CYC range) | Our heuristic | **Yes** | Needle sizes on published patterns |
| `needle_recommender.projects[].nudge_mm` | socks/mittens −0.25 · shawl +0.25 · others 0 | Our heuristic | **Yes** | Needle sizes on published patterns |
| `needle_recommender` defaults | fabric = balanced, project = scarf | ASSUMPTION | Yes | — |
| `tension.mm_per_stitch` | 0.25 mm per stitch of difference per 10 cm | Rule of thumb (1 size ≈ 1 st / 10 cm) | **Yes** | Swatch on 3 neighbouring sizes |
| `tension.sts_per_needle_size` | 1 stitch per 10 cm per needle size | Same rule of thumb, stitch side. Moved out of `calculators.py` into `domain.yaml` so the number the reply quotes ("about one stitch per 10cm") is editable with the mm side it pairs with | **Yes** | Same 3-swatch procedure; the two must be changed together |
| `tension.severity` | minor < 5% ≤ moderate < 10% ≤ major | Our heuristic | **Yes** | — |
| `tension.substitution_above` | 15% | Our heuristic | **Yes** | — |

### Calibration against published patterns
Three published patterns, run through the calculator with the pattern's own inputs (procedure: run each pattern's stated size, weight, stitch and gauge through `yarn_quantity`, compare with the published yardage, and adjust `m_per_100cm2` for a weight if the mean error is above 20%).

| Pattern | Inputs | Published yardage | Predicted | Error |
|---|---|---|---|---|
| [Piece of Home Blanket, Baby](https://www.fiftyfourtenstudio.com/knitting-patterns/piece-of-home-blanket) | worsted, stockinette, 29.25×32in, gauge 17sts/4in (16.7 sts/10cm) | 700–720yd (649.2m) | 679.2m | **+4.6%** |
| [Leelee Knits Hope Baby Blanket](https://leeleeknits.com/hope-baby-blanket-free-knitting-pattern/) | DK, alternating knit/purl block texture (mapped to our `seed` multiplier, no closer table entry), 28×34in, gauge 5sts/in stockinette swatch (19.7 sts/10cm) | 738yd (674.8m) | 845.3m | +25.3% |
| [Belleview Blanket, Baby](https://www.fiftyfourtenstudio.com/knitting-patterns/belleview-blanket) | super bulky, stitch and gauge not stated by the pattern (assumed stockinette + typical gauge, our tool's own no-gauge-given default) | 320–335yd (299.5m) | 368.9m | +23.2% |

**Mean absolute error: 17.7%** (all three over-predict; mean signed error +17.7%). Below the 20% adjust-trigger, so `m_per_100cm2` is left as-is. ASSUMPTION: the two larger errors trace to approximated *inputs* we had to guess (pattern 2's stitch has no exact match in our multiplier table; pattern 3 states neither stitch nor gauge), not to the medium/worsted constant itself, which calibrated to +4.6% on a clean, fully-specified pattern. Over-predicting is also the safer direction — running out of a dye lot costs a knitter more than one spare ball does — so no downward adjustment either. Revisit if a future calibration batch pushes the mean over 20%.

## 4. Assumptions log
Every reading, default and guess the product makes, in one place. It is a superset of the `ASSUMPTION:` tags in the source: rows marked † carry a matching tag at that location (`grep -rn ASSUMPTION assignment-a assignment-b`); the rest are recorded here only, because they live in a table row or a `note:` field where a tag would not help a reader.

| Where | Assumption |
|---|---|
| `.gitignore` | The company brief is not committed |
| `domain.yaml` jumbo † | CYC open bounds closed at 3 sts and 25 mm |
| `domain.yaml` aliases † | "baby" → Super Fine, "roving" → Super Bulky, plain "rib" → 1x1 |
| `domain.yaml` needles | Where CYC and Vogue disagree on a US size, CYC wins |
| `evals/questions.jsonl` ask-02 † | Stitch defaults to stockinette, so it is never asked for |
| `evals/questions.jsonl` | "Lace" is both a weight and a stitch; context decides ("lace shawl in fingering" = lace stitch) |
| `assistant/router.py` † | The offline router is a keyword/regex cascade, not NLU: declines (crochet → fibre comparison → dye lot → duration → garment sizing) are checked before intents, so "size M raglan sweater" declines instead of routing to yarn quantity |
| `assistant/question_reader.py` `read_weight` | Weight matching is tiered ("`<alias> weight`" > "`in <alias>`" > "`<alias> yarn`" > bare word), so "sport weight" beats the incidental "baby" in "Baby blanket" |
| `assistant/router.py` `YARN_WORD` | "how much" alone routes to yarn quantity ("How much worsted do I need…"); safe because declines and needle/tension are checked first |
| `assistant/router.py` `intent_from_llm` | An LLM reading is only trusted where it agrees with the question text and with the rule router; a dimension with no stated unit is cm |
| `knitcalc/calculators.py` `CalcResult.named_values()` | Numeric strings (needle sizes) count as numbers; constants the calculator applied are exposed as named inputs so replies may quote them |
| `cli.py` / `providers.get_provider` | No key, `LLM_PROVIDER=rules` or `--offline` ⇒ rules; never a crash |
| `evals/run_eval.py` | Results are written per mode (`eval_report_offline.md`, `eval_report_openai.md`) so both stay committed side by side |
| `swatch/cache.py` † | Colour name is not part of the cache key; model, quality, size and the prompt hash are |
| `swatch/cache.py` | The cache stores a 512 px copy to keep the repo small; production keeps full resolution for zoom |
| `swatch/config.yaml` colour | ΔE threshold 12 and the grey master `#9A9A9A` are tuned by eye (approximation) |
| `swatch/config.yaml` cost | 60% cache hit rate is a placeholder until real traffic exists |
| `swatch/config.yaml` cost | `estimate_tokens` (160 prompt + 272 image) is a round figure inside the measured range (prompt 156–163, image 272 for `gpt-image-1-mini` low 1024×1024, from the seven committed `cache/*.json`); used by `warm_cache.py --dry-run` and when no usage is recorded. `gpt-image-2` returned 196 image tokens, so the estimate is per-model and only calibrated for the default |
| `knitcalc/domain.yaml` limits † | Dimensions over 500 cm and gauges outside 1–60 sts/10 cm are declined as likely typos |
| `assistant/question_reader.py` units | A spaced "in" ("60 in stockinette") is never inches; only "60in", `60"` or "60 inches" are |
| `swatch/providers.py` | No key ⇒ `offline` provider (cache only, placeholder otherwise), and the choice is logged |
| `assistant/question_reader.py` `MIN_UNITLESS_DIMENSION_CM` † | A dimension pair with no stated unit ("50x60") is centimetres, and only when both numbers are ≥ 10 — below that they are more likely a gauge or a needle size than a blanket, so the router asks instead. The reply prints the assumption line |
| `assistant/question_reader.py` `AMBIGUOUS_WEIGHT_ALIASES` † | Words that are both a yarn weight and an ordinary word in a knitting question — `baby`, `rug`, `afghan`, `craft`, `light`, `sport`, plus every project and stitch alias — do not name a weight on their own. They count only as "`<word>` weight", "in `<word>`" or "`<word>` yarn", so "50 x 60cm baby blanket" asks for the weight instead of silently answering for super fine |
| `assistant/assistant.py` `DEFAULT_BUDGET_S` | One question gets 8 s of provider time in total (`ASSISTANT_BUDGET_S`), split across the routing and phrasing calls, with `max_retries=0`. Past the budget the rules and templates answer. The knitter waiting is the constraint, not the completeness of the LLM's attempt |

## 5. Dependencies (one line each)
| Package | Why |
|---|---|
| pydantic | Validates `domain.yaml`/`config.yaml` and the `CalcResult`/`SwatchResult` contracts |
| PyYAML | Human-editable config files |
| python-dotenv | Loads `.env` so no key is ever hard-coded |
| openai | Official SDK for the LLM and images, used only inside `providers.py` (Anthropic SDK removed until a second vendor is added, §1a) |
| requests | Ravelry HTTP calls with explicit timeout |
| Pillow, numpy | Placeholder rendering, colour measurement and tinting (colour maths hand-written, no skimage) |
| jupyter | The Assignment B demo notebook |
| pytest | Tests and markers (`demo`, `live`) |
