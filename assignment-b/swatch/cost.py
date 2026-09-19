"""Monthly cost estimate from measured tokens per image and OpenAI's published token prices (config.yaml).

All inputs (previews per day, cache hit rate, token prices) live in config.yaml under `cost:`.

Example: price_per_image("gpt-image-1-mini", input_tokens, output_tokens) -> USD for one image;
         monthly_estimate(...) -> three CostLines: no cache, cache, structure once + tint.
"""

from __future__ import annotations

from dataclasses import dataclass

from swatch.config import CONFIG


class UnknownModelError(LookupError):
    """No published price for this model in config.yaml → the caller must say "unknown", not "$0.00"."""


@dataclass(frozen=True)
class CostLine:
    """One row of the cost table."""

    scenario: str
    generations_per_month: float  # for a one_off line this is the total, not a monthly rate
    usd_per_image: float
    usd_per_month: float
    one_off: bool = False  # True: paid once, not every month (the grey structure masters)


def price_per_image(model: str, input_tokens: int, output_tokens: int) -> float:
    """price = input_tokens * text_input/1M + output_tokens * image_output/1M.

    Raises UnknownModelError (naming the priced models) if `model` has no published price.
    """
    try:
        price = CONFIG.cost.token_prices_per_1m[model]
    except KeyError:
        raise UnknownModelError(
            f"no published price for model {model!r}; priced models: "
            f"{sorted(CONFIG.cost.token_prices_per_1m)} (add it to config.yaml → cost.token_prices_per_1m)"
        ) from None
    return (input_tokens * price.text_input + output_tokens * price.image_output) / 1_000_000


def monthly_estimate(model: str, input_tokens: int, output_tokens: int, masters: int) -> list[CostLine]:
    """Three ways to serve CONFIG.cost.previews_per_day previews.

    no cache:   every preview is a generation
    cache:      only misses generate (1 - cache_hit_rate)
    tint path:  only the grey structure masters are generated, once (one_off); colours are tinted for free
    """
    cost_config = CONFIG.cost
    per_image = price_per_image(model, input_tokens, output_tokens)
    previews = cost_config.previews_per_day * cost_config.days_per_month
    misses = previews * (1 - cost_config.cache_hit_rate)
    return [
        CostLine("no cache", previews, per_image, previews * per_image),
        CostLine(f"cache ({cost_config.cache_hit_rate:.0%} hits)", misses, per_image, misses * per_image),
        CostLine(
            f"structure once + tint ({masters} masters, one-off)",
            masters, per_image, masters * per_image, one_off=True,
        ),
    ]
