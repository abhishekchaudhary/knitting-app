# DELIVERY_PLAN.md: 6-week MVP to the App Store and Google Play

**Team:** 1 React Native engineer (FE), 1 Python engineer (BE), me as EM (trust layer, reviews, release QA), the client founder (domain, content, store accounts).
**Stack:** RN + Expo (EAS Build/Submit); FastAPI on a managed host; Postgres + auth from Supabase; S3 + CDN for swatches; OpenAI behind the POC provider interfaces.
**Design:** no designer. Founder-supplied Figma if it exists, otherwise React Native Paper, with design effort spent on the planner screen only. Decided in week 1, not week 5.
**Principle:** the POCs become production modules in week 1, so the riskiest parts (trustworthy numbers, swatch speed) are solved first.

## The two gates that set the critical path

Outside our control, so both start on day 1.

- **Google Play.** A new personal developer account must run a **closed test with at least 12 testers opted in for 14 continuous days** before it can apply for production access. The closed test opens at the end of week 2 on the week-2 build and runs days 15–28, finishing before the submission week; production access is applied for in week 5.
- **Apple.** An organisation account needs a **D-U-N-S number**: D&B quotes up to 5 business days to issue one and Apple up to 2 more to receive it, before enrolment review even starts, so it is requested on day 1. Fallback: a personal account, decided by end of week 2, because the listing name is hard to change later.

_Sources, checked 2026-09-18: Play's testing requirement for personal accounts created after 13 Nov 2023 ([Play Console Help](https://support.google.com/googleplay/android-developer/answer/14151465)); Apple's D-U-N-S timings ([Apple Developer Help](https://developer.apple.com/help/account/membership/D-U-N-S/))._

The 12 Play testers are also the beta cohort, so one founder recruitment serves both.

## Weekly milestones

Each week ends in an artefact someone can open and check.

| Week | Frontend (RN) | Backend (Python) | What you can open |
|---|---|---|---|
| 1 | Expo shell, navigation, tokens, auth screens; EAS builds on both internal tracks | FastAPI skeleton; port `knitcalc`, `assistant`, `swatch`; auth + Postgres schema; CI runs both POC suites and the offline eval | Signed-in empty app from TestFlight and Play internal testing; green CI; both accounts opened, D-U-N-S requested |
| 2 | Guides (founder markdown); assistant chat with the "how this was calculated" drawer | `/assistant/answer`, `/calc/*`; guard metrics and structured logs; nightly live eval in CI | The three brief questions answered on a phone, plus a decline and an ask-for-input; **Play closed test opens, 12 testers** |
| 3 | Planner: dimensions, stitch, weight, presets; placeholder → swap-in; prefetch of neighbours | `/swatch`; S3 + CDN cache (same content-hash key); preset pre-generation job; tint masters; moderation before `ready` | A preset tap on a real device updating in < 300 ms, measured and recorded |
| 4 | Inventory CRUD; planner uses inventory ball size for yardage | Inventory API; per-user generation rate limits; timeouts, circuit breaker, cost dashboard | Feature-complete build with all 12 testers; TestFlight external review passed; **Play 14-day test complete** |
| 5 | Read-only feed; account deletion; offline and error states; accessibility pass (FE owns, EM audits with VoiceOver/TalkBack against a checklist) | Feed API + admin posting; deletion endpoint; load test on `/swatch` and `/assistant`; privacy data map | Beta bugs triaged with every P0 closed; listings and screenshots drafted; Play production access applied for |
| 6 | **Fix-only, no new scope.** Store assets, release builds, crash reporting | **Fix-only.** Production deploy; alerts on guard rejections, provider errors, spend; runbook | **Submitted to both stores on day 2**, leaving one rejection cycle |

**Release QA is mine:** a written checklist (brief questions, decline, offline mode, presets × stitches, provider-outage fallback, account deletion, fresh install) run on both platforms in weeks 4, 5 and 6. The 12 testers are the second pass; neither engineer signs off their own surface.

## Dependencies
- **Week 1 → everything:** auth and schema block planner and inventory; BE starts day 1.
- **Planner (week 3) needs** `/swatch`, the preset grid and final preset colours by end of week 2; **guides need** founder content by week 2, else three samples.
- **Submission needs** the two gates plus privacy policy, support URL, screenshots, age rating and account deletion (an Apple requirement).
- **External beta (week 4)** needs TestFlight external review: usually 1–2 days.

## Buffer and cut ladder

Week 6 is the buffer: fix-only, so slippage is absorbed by cutting scope, never by cutting the fix week. If we are not feature-complete by the **end of week 4**, we cut in this order and stop as soon as the date is safe:

1. Community feed entirely — link to the founder's existing channel.
2. Inventory write path — read-only yarn list, no needle CRUD.
3. Custom colours — presets only, tint code dormant behind a flag.
4. Guides down to three founder-written samples, no CMS-lite.
5. Android production launch deferred to v1.1 — iOS only, Play stays in closed testing.

Cut 5 is last because it forfeits the Play gate the rest of the plan protects.

## Top risks

| Risk | Likelihood / impact | Mitigation |
|---|---|---|
| **Store review rejection in week 6** (AI images, UGC, account rules) | Medium / high: moves the date | TestFlight external review in week 4; feed read-only; account deletion in week 5; moderation on generated images |
| **Play closed test or D-U-N-S started late** | Medium / high: unrecoverable, 14 days cannot be compressed | Day-1 founder actions with a named owner; weekly check; Apple personal-account fallback decided by end of week 2 |
| A wrong yardage number erodes trust with sceptical knitters | Medium / high | Guard + eval as a CI gate (built); founder signs off `domain.yaml`; testers check 10 real projects |
| Generation latency or cost spikes | Medium / medium | Preset grid on a CDN, tint path, per-user rate limit, spend alert, fast tier by default |
| OpenAI outage | Low / medium | Rules + templates for the assistant, placeholder + cache for swatches (both built); second vendor post-MVP |
| Two engineers, no slack for illness | Medium / high | The cut ladder, checked every Friday; the EM codes in the trust layer |

**The single biggest risk is store review** — the only step outside our control, and it lands last. The plan pulls it forward: real builds from week 1, the Play 14-day clock started in week 2, TestFlight external review in week 4, UGC cut to read-only.

## What the client founder provides
- **Day 1:** Play account opened; Apple enrolment started and D-U-N-S requested; company details, privacy policy owner.
- **Week 1:** 12 beta knitters recruited, tester emails collected (they opt in during week 2).
- **Week 2:** guide content, final preset colours, sign-off on `domain.yaml` multipliers and needle rules.
- **Week 5:** listing copy, screenshot approval, brand assets.
- **Throughout:** a decision owner who answers product questions within one working day.

## What I would cut (and ship in v1.1)
- **Community posting, comments, likes** — the feed is read-only and founder-curated.
- **Custom colours** beyond the presets: the tint path is ready, the UI and QA cost a week.
- **Photo upload of a real swatch** and gauge detection from photos.
- **Social login beyond Apple/Google**, and push notifications.
- **A second AI vendor:** interfaces are ready; it adds a key and a failover test.
- **Bundled offline calculators** — the server answers in ms; bundling means a second implementation to keep in sync.
