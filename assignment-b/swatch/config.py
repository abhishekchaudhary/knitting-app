"""Load and validate swatch/config.yaml (pydantic). Fails fast at import on a bad edit.

One pydantic class per config.yaml section, smallest pieces first, then `Config`
(the whole file) with name lookups, then the module-level `CONFIG` everyone imports.
A typo in the YAML (wrong key, bad hex, unknown fallback pattern) raises at import.

Example: CONFIG.stitch("Rib 1x1").key -> "rib_1x1"; CONFIG.fibre_clause("merino wool") -> the wool clause.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator

CONFIG_PATH = Path(__file__).parent / "config.yaml"


def _validated_hex(value: str, field_name: str) -> str:
    """#RRGGBB, upper-cased. Shared by Preset.hex and ColourConfig.master_hex (both key inputs)."""
    if len(value) != 7 or not value.startswith("#"):
        raise ValueError(f"{field_name} must look like #RRGGBB, got {value!r}")
    int(value[1:], 16)  # raises ValueError if the six characters are not hex digits
    return value.upper()


class Stitch(BaseModel):
    key: str
    aliases: list[str]
    structure: str
    fallback: str
    ravelry_query: str

    @field_validator("fallback")
    @classmethod
    def _fallback_is_drawable(cls, value: str) -> str:
        """A typo here would make the failure path itself raise, so it is rejected at load."""
        from swatch.fallback import PATTERNS  # local: fallback.py reads this module's CONFIG

        if value not in PATTERNS:
            raise ValueError(f"unknown fallback pattern {value!r}; known: {sorted(PATTERNS)}")
        return value


class Stitches(BaseModel):
    source: str
    note: str
    items: list[Stitch]


class WeightItem(BaseModel):
    key: str
    aliases: list[str]
    clause: str


class Weights(BaseModel):
    source: str
    note: str
    items: list[WeightItem]


class FibreItem(BaseModel):
    keyword: str
    clause: str


class Fibres(BaseModel):
    source: str
    note: str
    default: str
    items: list[FibreItem]


class PromptConfig(BaseModel):
    source: str
    note: str
    colour_template: str
    suffix: str


class Preset(BaseModel):
    name: str
    hex: str

    @field_validator("hex")
    @classmethod
    def _normalise_hex(cls, value: str) -> str:
        return _validated_hex(value, "preset hex")


class Presets(BaseModel):
    source: str
    note: str
    items: list[Preset]


class ColourConfig(BaseModel):
    delta_e_threshold: float
    master_hex: str
    measure_crop: float = Field(gt=0, le=1)
    source: str
    approximation: bool
    note: str
    calibrate: str

    @field_validator("master_hex")
    @classmethod
    def _normalise_master_hex(cls, value: str) -> str:
        """Normalised like Preset.hex: the master hex is part of the tint master's cache key."""
        return _validated_hex(value, "colour master_hex")


class ImageConfig(BaseModel):
    default_model: str
    quality: str
    size: str
    store_px: int
    source: str
    note: str


class RavelryConfig(BaseModel):
    base_url: str
    search_path: str
    page_size: int
    search_timeout_s: float
    photo_timeout_s: float
    source: str
    note: str


class TokenEstimate(BaseModel):
    """Measured tokens for one image. Typed so a key typo fails at load, not inside the cost cell."""

    model_config = {"extra": "forbid"}

    input: int = Field(ge=0)
    output: int = Field(ge=0)

    def __getitem__(self, name: str) -> int:  # dict-style access kept for the notebook
        if name not in type(self).model_fields:
            raise KeyError(name)
        return getattr(self, name)


class TokenPrice(BaseModel):
    """USD per 1M tokens for one model."""

    model_config = {"extra": "forbid"}

    text_input: float = Field(ge=0)
    image_output: float = Field(ge=0)

    def __getitem__(self, name: str) -> float:
        if name not in type(self).model_fields:
            raise KeyError(name)
        return getattr(self, name)


class CostConfig(BaseModel):
    previews_per_day: int = Field(gt=0)
    days_per_month: int = Field(gt=0)
    cache_hit_rate: float = Field(ge=0, le=1)
    source: str
    approximation: bool
    note: str
    calibrate: str
    estimate_tokens: TokenEstimate
    prices_checked: str
    price_source: str
    token_prices_per_1m: dict[str, TokenPrice]


class Config(BaseModel):
    version: int
    stitches: Stitches
    weights: Weights
    fibres: Fibres
    prompt: PromptConfig
    presets: Presets
    colour: ColourConfig
    image: ImageConfig
    ravelry: RavelryConfig
    cost: CostConfig

    def stitch(self, name: str) -> Stitch:
        """Stitch entry by key or alias (case, spaces and underscores ignored). ValueError if unknown."""
        return _find_by_name(self.stitches.items, name, "stitch type")

    def weight(self, name: str) -> WeightItem:
        """Weight entry by key or alias. ValueError if unknown."""
        return _find_by_name(self.weights.items, name, "weight category")

    def fibre_clause(self, fibre_content: str) -> str:
        """Prompt clause for the first fibre keyword found in `fibre_content`, else the default clause."""
        text = fibre_content.lower()
        for item in self.fibres.items:
            if item.keyword in text:
                return item.clause
        return self.fibres.default


def load_config(path: Path = CONFIG_PATH) -> Config:
    """Read and validate a config.yaml. Raises pydantic.ValidationError on a bad edit."""
    return Config.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def _find_by_name(items: list, name: str, kind: str):
    """The item whose key (underscores read as spaces) or alias matches `name`, ignoring case and extra spaces."""
    normalised = " ".join(name.strip().lower().replace("_", " ").split())
    for item in items:
        if normalised == item.key.replace("_", " "):
            return item
        if _matches_alias(normalised, item.aliases):
            return item
    raise ValueError(f"unknown {kind}: {name!r}")


def _matches_alias(normalised: str, aliases: list[str]) -> bool:
    for alias in aliases:
        if normalised == alias.lower():
            return True
    return False


CONFIG = load_config()
