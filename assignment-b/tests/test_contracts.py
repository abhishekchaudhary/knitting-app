"""config.yaml contract, SwatchResult shape, cost arithmetic."""

from __future__ import annotations

import dataclasses

import pytest

from swatch.cache import SwatchCache
from swatch.config import CONFIG, load_config
from swatch.cost import CostLine, UnknownModelError, monthly_estimate, price_per_image
from swatch.fallback import PATTERNS
from swatch.pipeline import SwatchResult, get_swatch
from swatch.providers import FixtureProvider


def test_config_loads_and_every_stitch_is_complete():
    cfg = load_config()
    assert {"stockinette", "garter", "rib_1x1", "seed", "cable", "lace"} <= {s.key for s in cfg.stitches.items}
    for s in cfg.stitches.items:
        assert s.structure and s.ravelry_query and s.fallback in PATTERNS


def test_presets_cover_five_to_six_colours():
    assert 5 <= len(CONFIG.presets.items) <= 6


def test_default_model_has_a_price():
    assert CONFIG.image.default_model in CONFIG.cost.token_prices_per_1m


def test_swatch_result_contract(tmp_path):
    result = get_swatch(
        {"stitch_type": "rib", "colour_hex": "#2E6B3F"}, provider=FixtureProvider(), cache=SwatchCache(tmp_path)
    )
    fields = {f.name for f in dataclasses.fields(SwatchResult)}
    assert {"image", "source", "key", "elapsed_ms", "delta_e"} <= fields
    assert result.source in {"cache", "generated", "fallback", "tint"}
    assert len(result.key) == 64


def test_price_per_image_arithmetic():
    # gpt-image-1-mini: $2/1M text in, $8/1M image out
    assert price_per_image("gpt-image-1-mini", 1_000, 10_000) == pytest.approx(0.002 + 0.08)


def test_monthly_estimate_orders_scenarios():
    lines = monthly_estimate("gpt-image-1-mini", 100, 272, masters=56)
    no_cache, cached, tint = (line.usd_per_month for line in lines)
    assert no_cache > cached > tint
    assert lines[0].generations_per_month == CONFIG.cost.previews_per_day * CONFIG.cost.days_per_month


def test_unpriced_model_raises_a_named_error_listing_the_priced_models():
    """A model swap used to traceback the notebook cost cell with a bare KeyError."""
    with pytest.raises(UnknownModelError) as exc:
        price_per_image("gpt-image-9", 100, 200)
    assert "gpt-image-9" in str(exc.value)
    for model in CONFIG.cost.token_prices_per_1m:
        assert model in str(exc.value)


def test_tint_line_is_labelled_one_off():
    """The masters are paid once; the notebook table must be able to say so."""
    lines = monthly_estimate("gpt-image-1-mini", 100, 272, masters=56)
    assert [line.one_off for line in lines] == [False, False, True]
    assert "one-off" in lines[-1].scenario


def test_cost_line_fields_the_notebook_reads():
    fields = {f.name for f in dataclasses.fields(CostLine)}
    assert {"scenario", "generations_per_month", "usd_per_image", "usd_per_month", "one_off"} == fields
