# LATENCY_NOTE.md: making colour switching fast

**Goal:** a preset-colour tap updates the hero swatch in well under 300 ms; a fresh generation takes ~10 s.

## Measured (`assignment-b/swatch_preview.ipynb`, `gpt-image-1-mini`, quality low, 1024×1024)

| Path | Time | Colour error (ΔE2000) | Where |
|---|---|---|---|
| Fresh generation | 9.2–16.6 s (typically ~10 s) | 0.3–9.8 after tint check | sections 1, 3, 4 |
| Cache hit (same inputs) | 6–8 ms, local disk | as generated | sections 2, 4 |
| Colour switch: tint a cached grey master | ~60 ms (6 ms lookup + ~55 ms tint, 512 px, numpy) | 0.3–0.5 | section 8 |
| Placeholder (procedural, target hex) | ~47 ms | < 3, asserted in `tests/test_fallback.py` | section 5 |

A 10-second wait behind every tap breaks the calm the product depends on, and no model tier closes that gap (DECISIONS §1c). So: **the tap must never wait for a generation.**

## What I'd build, in order of impact

1. **Pre-generate the preset grid.** Presets are a fixed set (7 stitches × 6 colours × a few weights and fibres). Generate at deploy (`warm_cache.py`), serve from S3 + CDN on the POC's content-hash key. A tap is then a CDN fetch (~50–150 ms on mobile), near 0 ms with prefetch. At $0.0025 per image the grid costs a few dollars.
2. **Generate structure once, apply colour on device.** For custom colours, one neutral-grey master per stitch/weight/fibre, recoloured by a LAB shift: ~55 ms server-side; on device a GPU shader over the downloaded master should cost a few ms, no network (**estimate**, not measured). 392 masters, one-off ≈$1.
   **What tint proves, and what it does not:** the tint moves the master's median LAB onto the target, so the tinted ΔE of 0.3–0.5 is near zero *by construction* — it shows the colour landed, not that the swatch is good. Tint keeps the stitch geometry and its light/shade pattern; it cannot reproduce colour-dependent sheen and shadow, so tinted swatches read flat. `get_swatch_fast` logs `SWATCH tint=OFF_TARGET` if the tinted ΔE still exceeds the threshold (12). Tint for browsing; spend the 10 s on a fresh generation when the user commits — zoom, export, add-to-project.
3. **Show something immediately, swap in the real image.** Serve the best image available *now* — cached → tinted master → placeholder in the exact hex (~47 ms, no network) — while a background job generates the real one and cross-fades it in. This is also the outage path, so it runs daily.
4. **Fast tier for previews, slow tier for zoom.** `quality=low` is enough for a planner card; generate `quality=medium` only on zoom, cached separately (model and quality are already in the key).
5. **Guard the queue.** Dedupe in-flight requests by cache key, rate-limit per user, cancel stale jobs when the user taps on.

## "Fast enough" at launch
- Preset tap to correct-colour image: < 300 ms p95 (mid-range Android, 4G); preset cache hit ratio > 90%.
- Custom colour: tint < 300 ms; dedicated image within ~15 s, in the background.
