"""Prompt: stitch structure first, hex + RGB + words present, stitches produce different structure text."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from swatch.config import CONFIG
from swatch.prompt_builder import SwatchInputs, build_prompt

BRIEF = {
    "stitch_type": "cable",
    "colour_name": "royal purple",
    "colour_hex": "#5B3E96",
    "weight_category": "worsted",
    "fibre_content": "100% wool",
}


def test_brief_example_prompt_contents():
    prompt = build_prompt(SwatchInputs(**BRIEF))
    assert prompt.startswith("A close-up of cable knit fabric")
    assert "rope-like braids" in prompt
    assert "#5B3E96" in prompt and "RGB(91, 62, 150)" in prompt
    assert "purple" in prompt
    assert "worsted" in prompt
    assert "ply twist" in prompt


def test_stitch_comes_before_colour():
    prompt = build_prompt(SwatchInputs(**BRIEF))
    assert prompt.index("braids") < prompt.index("#5B3E96")


def test_every_stitch_has_distinct_structure():
    prompts = {s.key: build_prompt(SwatchInputs(**{**BRIEF, "stitch_type": s.key})) for s in CONFIG.stitches.items}
    assert len(set(prompts.values())) == len(prompts)
    assert "vertical" in prompts["rib_1x1"] and "V-shaped" in prompts["stockinette"]


@pytest.mark.parametrize("alias,key", [("Rib", "rib_1x1"), ("moss stitch", "seed"), ("Stocking Stitch", "stockinette")])
def test_stitch_aliases_normalise(alias, key):
    assert SwatchInputs(**{**BRIEF, "stitch_type": alias}).stitch_type == key


def test_hex_normalised_to_upper():
    assert SwatchInputs(**{**BRIEF, "colour_hex": " #5b3e96 "}).colour_hex == "#5B3E96"


@pytest.mark.parametrize("field,value", [("stitch_type", "fair isle"), ("colour_hex", "purple"), ("weight_category", "mega")])
def test_bad_inputs_rejected(field, value):
    with pytest.raises(ValidationError):
        SwatchInputs(**{**BRIEF, field: value})


def test_unknown_fibre_uses_default_clause():
    prompt = build_prompt(SwatchInputs(**{**BRIEF, "fibre_content": "yak down"}))
    assert CONFIG.fibres.default in prompt


def test_equal_inputs_compare_and_hash_equal():
    """The docstring promises it; the cache key scheme relies on the same normalisation."""
    messy = {"stitch_type": "Cable", "colour_name": "Royal Purple", "colour_hex": "#5b3e96",
             "weight_category": "Worsted", "fibre_content": " 100%  WOOL "}
    assert SwatchInputs(**BRIEF) == SwatchInputs(**messy)
    assert hash(SwatchInputs(**BRIEF)) == hash(SwatchInputs(**messy))


def test_inputs_are_frozen():
    with pytest.raises(ValidationError):
        SwatchInputs(**BRIEF).stitch_type = "garter"
