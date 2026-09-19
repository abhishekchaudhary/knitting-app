"""Structured swatch input -> image prompt.

Order matters: stitch structure first (the input that must always be
respected), then colour (hex + RGB + words), then weight, fibre and the fixed
photography suffix. All wording lives in config.yaml.

Example: SwatchInputs(stitch_type="Cable", colour_hex="#5b3e96") -> stitch "cable", hex "#5B3E96";
build_prompt(...) -> "A close-up of <cable structure>. <colour clause> The swatch is ... <suffix>"
"""

from __future__ import annotations

from pydantic import BaseModel, field_validator

from swatch import colour
from swatch.config import CONFIG


class SwatchInputs(BaseModel):
    """Brief §4.2 input. Frozen and normalised on construction, so equal inputs compare and hash
    equal — that is what makes the cache key stable across spellings of the same request."""

    model_config = {"frozen": True}

    stitch_type: str
    colour_hex: str
    colour_name: str = ""
    weight_category: str = "medium"
    fibre_content: str = "100% wool"

    @field_validator("stitch_type")
    @classmethod
    def _normalise_stitch(cls, value: str) -> str:
        """Any alias or spelling -> the configured stitch key, e.g. 'Rib 1x1' -> 'rib_1x1'."""
        return CONFIG.stitch(value).key

    @field_validator("weight_category")
    @classmethod
    def _normalise_weight(cls, value: str) -> str:
        """Any alias -> the configured weight key."""
        return CONFIG.weight(value).key

    @field_validator("colour_hex")
    @classmethod
    def _normalise_hex(cls, value: str) -> str:
        """'5b3e96' -> '#5B3E96'."""
        return colour.rgb_to_hex(colour.hex_to_rgb(value))

    @field_validator("colour_name", "fibre_content")
    @classmethod
    def _normalise_text(cls, value: str) -> str:
        """Lower case, single spaces."""
        return " ".join(value.strip().lower().split())


def build_prompt(inputs: SwatchInputs) -> str:
    """The image prompt for these inputs: structure, colour, weight + fibre, then the photography suffix."""
    stitch = CONFIG.stitch(inputs.stitch_type)
    red, green, blue = colour.hex_to_rgb(inputs.colour_hex)
    colour_clause = CONFIG.prompt.colour_template.format(
        hex=inputs.colour_hex, r=red, g=green, b=blue, words=colour.describe(inputs.colour_hex)
    )
    weight_clause = CONFIG.weight(inputs.weight_category).clause
    fibre_clause = CONFIG.fibre_clause(inputs.fibre_content)
    parts = [
        f"A close-up of {stitch.structure}.",
        colour_clause,
        f"The swatch is {weight_clause}, {fibre_clause}.",
        CONFIG.prompt.suffix,
    ]
    return " ".join(parts)
