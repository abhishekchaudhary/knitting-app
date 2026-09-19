# Code tour

A guided route through the code for a new engineer. Read the files in
the order below. Each one opens with a short docstring saying what it does, with an example.

## Reading order

**Assignment A: the assistant** (`assignment-a/`)

| # | File | What it does | Read for |
|---|---|---|---|
| 1 | `knitcalc/domain.yaml` | Every knitting number: yarn weights, needle table, stitch multipliers, safety margin. Each has a `source` and a `note` | Where the numbers live |
| 2 | `knitcalc/calculators.py` | `yarn_quantity`, `needle_recommendation`, `tension_diagnosis`. Each returns a `CalcResult` (answer, formula, inputs, assumptions, source) | The maths |
| 3 | `assistant/assistant.py` | `answer(question)`: route → calculate → phrase → guard. The whole flow in ~20 lines | The architecture |
| 4 | `assistant/router.py` | `route()` picks the calculator from keywords; `intent_from_llm()` checks the LLM's reading against the question | How a question becomes an `Intent` |
| 5 | `assistant/question_reader.py` | `read_dimensions`, `read_weight`, `read_stitch`, `read_gauge`, `read_tension_pair` | How inputs are read out of text |
| 6 | `assistant/declines.py` | The questions we refuse, each with a fixed sentence | Declines |
| 7 | `assistant/guard.py` | Every number in a reply must be a calculator value of the right kind, and the headline must be stated | The trust boundary |
| 8 | `assistant/phraser.py` | Fixed-wording replies: the safe template, "please tell me…", "I can't answer…" | The fallback reply |
| 9 | `assistant/providers.py` | `RuleProvider` (offline) and `OpenAIProvider` (LLM), with the same two methods | Where the LLM is called |
| 10 | `cli.py`, `evals/run_eval.py` | The command line, and the 36-question evaluation | How it is run and measured |

**Assignment B: the swatch preview** (`assignment-b/`)

| # | File | What it does |
|---|---|---|
| 1 | `swatch/config.yaml` | Stitch descriptions for the prompt, colour presets, ΔE threshold, prices |
| 2 | `swatch/pipeline.py` | `get_swatch(inputs)`: cache → generate → placeholder. `get_swatch_fast`: grey master once, then tint |
| 3 | `swatch/prompt_builder.py` | Structured inputs → prompt (stitch first, then colour as hex + RGB + words) |
| 4 | `swatch/cache.py` | `cache_key` = sha256 of the inputs + model + prompt; `SwatchCache.get/put` on disk |
| 5 | `swatch/providers.py` | `OpenAIImageProvider`, `FailingProvider` (simulated outage), `OfflineProvider`, `FixtureProvider` |
| 6 | `swatch/colour.py` | hex → LAB, ΔE2000 colour distance, `tint()` |
| 7 | `swatch/fallback.py` | A drawn placeholder per stitch in the target colour |
| 8 | `swatch/ravelry.py` | Pattern search for a reference photo; every failure returns None |
| 9 | `swatch_preview.ipynb` | The demo, in video order |

## Five questions traced through the code

**1. "How much DK yarn do I need for a 50 x 60cm blanket in stockinette?"**

```
assistant.answer
 └─ _route ─ RuleProvider.route ─ router.route
      ├─ declines.matching_declines   → none
      └─ _calculator_intent: no "tension", no "needle", has "yarn" → _yarn_intent
           ├─ read_dimensions  → (50.0, 60.0)
           ├─ read_weight      → ("light", "dk")      alias from domain.yaml
           └─ read_stitch      → "stockinette"
      → Intent(yarn_quantity, {width_cm: 50, height_cm: 60, weight: light, stitch: stockinette})
 └─ _calculate ─ calculators.yarn_quantity   → {metres: 429.0, balls: 4}
 └─ _phrase_and_guard
      ├─ _draft_reply: rules route → phraser.template_reply
      └─ guard.problems(draft, calc) → []  → reply goes out
```
With an API key, `OpenAIProvider.route` reads the question instead. `intent_from_llm` rejects the reading if the LLM returns a number the question doesn't contain, or disagrees with the rules. The LLM then writes the reply, and `guard.problems` swaps it for the template if a number is wrong.

**2. "What needle size should I use for worsted yarn for a scarf?"**: `_needle_intent` → `read_weight` ("medium"), `read_project` ("scarf"), no fabric (the balanced default) → `needle_recommendation` → 5.0 mm, US 8, UK 6.

**3. "My swatch is 24 stitches per 10cm but the pattern says 22."**: no "tension" word, but `TENSION_CONTEXT_WORD` ("swatch") plus `read_tension_pair` → (24, 22), so `_tension_intent` → `tension_diagnosis` → too tight, +9.1 %, go up a needle size.

**4. A decline: "Is wool warmer than acrylic?"**: `declines.matching_declines` finds `material_comparison` → `Intent("unsupported", reason)` → `phraser.decline_reply`. The reason text is fixed in `declines.py` and never written by the LLM.

**5. Swatch cache HIT and MISS** (`pipeline.get_swatch`)

```
build_prompt(inputs) → key_for(inputs, provider) → cache.get(key)
   HIT  → _cached_result            log: SWATCH cache=HIT
   MISS → provider.generate(prompt)
            ok    → _generated_result: ΔE check, tint if ΔE > 12, cache.put   log: SWATCH cache=MISS
            fails → _placeholder_result: fallback.placeholder in the hex       log: SWATCH fallback=placeholder
```

## Common changes, and where they go

| Change | Edit | Check with |
|---|---|---|
| Change a stitch multiplier (cable 1.35 → 1.4) | `domain.yaml → stitches.items`, the `cable` row | `python assignment-a/cli.py --offline "How much DK yarn for a 50 x 60cm blanket in cable?"` |
| Add a stitch type (e.g. `brioche`) | A: one row in `domain.yaml → stitches.items` (key, aliases, multiplier, range, note). B: one entry in `config.yaml → stitches.items` (`aliases`, `structure` sentence for the prompt, `fallback`: one of the drawn patterns in `fallback.PATTERNS` such as `ridges`, `ravelry_query`) | Same CLI command with "brioche" (for example 686.4 m, 6 balls at a 1.60 multiplier). Gates stay green; the held-out eval row ho-10, which uses brioche as its example of an unknown stitch, now answers instead of asking (11/12, reported, not gated) |
| Add a decline topic (e.g. dyeing) | `declines.py → DECLINES`: add `"dyeing": (pattern, reason)`. The LLM schema picks up the category automatically | `cli.py --offline "How do I dye yarn with tea?"` |
| Add a colour preset | `config.yaml → presets.items` | Notebook cell 3 or 8 |
| Change the colour tolerance | `config.yaml → colour.delta_e_threshold` | `pytest assignment-b/tests -q` |
| Change the safety margin | `domain.yaml → yarn_quantity.safety_margin` | The CLI answer changes; the golden eval values (`questions.jsonl`, `expected_values`) fail on purpose until you update them |

After any change: `scripts/check_all.sh` must print `ALL GATES GREEN`. Pydantic validates both YAML files when the code loads them, so a typo fails at start-up with the field name, not later with a wrong answer.

## Words used in the code

| Word | Meaning |
|---|---|
| `Intent` | The router's decision: which calculator, which inputs, what's missing |
| `CalcResult` | A calculator's answer plus formula, inputs, assumptions and source |
| draft / reply | The LLM's text before the guard / what the knitter actually sees |
| route / phrase | Reading the question / wording the answer |
| alias | Another name for the same thing in domain.yaml ("DK" is an alias of `light`) |
| ΔE (delta E) | How different two colours look; under ~10 reads as the same colour |
| master | The grey swatch generated once per stitch, then tinted to each colour |
