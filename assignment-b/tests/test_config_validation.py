"""config.yaml must reject a bad edit at load, not at call time.

Every case here is a plausible one-line config edit; each used to load
clean and raise somewhere downstream (the placeholder, the cost cell, the tint master's key).
"""

from __future__ import annotations

import copy

import pytest
import yaml
from pydantic import ValidationError

from swatch.config import CONFIG_PATH, Config


@pytest.fixture(scope="module")
def raw() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))


def _edit(raw: dict, mutate) -> dict:
    data = copy.deepcopy(raw)
    mutate(data)
    return data


def test_bad_fallback_name_rejected_at_load(raw):
    def mutate(d):
        d["stitches"]["items"][0]["fallback"] = "typo"

    with pytest.raises(ValidationError, match="unknown fallback pattern"):
        Config.model_validate(_edit(raw, mutate))


def test_master_hex_is_validated_and_normalised(raw):
    def lower(d):
        d["colour"]["master_hex"] = "#9a9a9a"

    assert Config.model_validate(_edit(raw, lower)).colour.master_hex == "#9A9A9A"

    def broken(d):
        d["colour"]["master_hex"] = "9A9A9A"

    with pytest.raises(ValidationError, match="master_hex"):
        Config.model_validate(_edit(raw, broken))


@pytest.mark.parametrize(
    "section,key,value",
    [
        ("colour", "measure_crop", 0),
        ("cost", "cache_hit_rate", 1.5),
        ("cost", "cache_hit_rate", -0.1),
        ("cost", "previews_per_day", 0),
        ("cost", "days_per_month", -1),
    ],
)
def test_out_of_range_numbers_rejected(raw, section, key, value):
    with pytest.raises(ValidationError):
        Config.model_validate(_edit(raw, lambda d: d[section].__setitem__(key, value)))


def test_estimate_tokens_typo_rejected(raw):
    def mutate(d):
        d["cost"]["estimate_tokens"] = {"inputs": 160, "output": 272}

    with pytest.raises(ValidationError):
        Config.model_validate(_edit(raw, mutate))


def test_token_price_typo_rejected(raw):
    def mutate(d):
        d["cost"]["token_prices_per_1m"]["gpt-image-1-mini"] = {"text_in": 2.0, "image_output": 8.0}

    with pytest.raises(ValidationError):
        Config.model_validate(_edit(raw, mutate))


def test_typed_cost_sections_still_support_notebook_style_access(raw):
    cfg = Config.model_validate(raw)
    assert cfg.cost.estimate_tokens["input"] == cfg.cost.estimate_tokens.input
    price = cfg.cost.token_prices_per_1m[cfg.image.default_model]
    assert price["text_input"] == price.text_input
    with pytest.raises(KeyError):
        cfg.cost.estimate_tokens["nope"]
