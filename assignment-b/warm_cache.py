"""Bonus: pre-generate a fixed stitch x preset-colour grid so first taps are cache hits.

    python warm_cache.py --dry-run                         # list the grid and estimated cost, no API calls
    python warm_cache.py --stitches cable rib_1x1 --presets 3 --workers 3
"""

from __future__ import annotations

import argparse
import logging
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dotenv import load_dotenv
from pydantic import ValidationError

from swatch.cache import SwatchCache
from swatch.config import CONFIG
from swatch.cost import UnknownModelError, price_per_image
from swatch.pipeline import get_swatch, key_for
from swatch.prompt_builder import SwatchInputs
from swatch.providers import get_image_provider

logger = logging.getLogger("swatch")


def main() -> int:
    """Warm the cache for the stitch x preset grid. Returns the process exit code (0 ok, 1 nothing/failed)."""
    parser = _build_parser()
    args = parser.parse_args()

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    provider = get_image_provider()
    cache = SwatchCache()
    grid = _build_grid(args, parser)
    todo = [swatch for swatch in grid if cache.get(key_for(swatch, provider)) is None]

    logger.info("WARM grid=%d already_cached=%d to_generate=%d provider=%s model=%s est. cost=%s",
                len(grid), len(grid) - len(todo), len(todo), provider.name, provider.model,
                _estimated_cost(len(todo), provider.model))
    if args.dry_run or not todo:
        return 0
    if provider.name != "openai":
        logger.warning("WARM status=no_provider provider=%r: set OPENAI_API_KEY to generate, "
                       "or re-run with --dry-run to see the grid and the estimate", provider.name)
        return 1
    return _generate_all(todo, provider, cache, args.workers)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stitches", nargs="+", default=[stitch.key for stitch in CONFIG.stitches.items])
    parser.add_argument("--presets", type=_positive("--presets"), default=len(CONFIG.presets.items),
                        help="first N preset colours")
    parser.add_argument("--weight", default="worsted")
    parser.add_argument("--fibre", default="100% wool")
    parser.add_argument("--workers", type=_positive("--workers"), default=3)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def _positive(name: str):
    """argparse type: a positive integer, with an error message naming the flag."""

    def parse(value: str) -> int:
        number = int(value)
        if number <= 0:
            raise argparse.ArgumentTypeError(f"{name} must be a positive integer, got {number}")
        return number

    return parse


def _build_grid(args: argparse.Namespace, parser: argparse.ArgumentParser) -> list[SwatchInputs]:
    """Every requested stitch x the first N presets, stitch by stitch.

    --stitches / --weight / --fibre are user input, so a bad value is an
    argparse error (exit 2 with a message), not a raw traceback.
    """
    grid = []
    try:
        for stitch in args.stitches:
            for preset in CONFIG.presets.items[: args.presets]:
                grid.append(SwatchInputs(stitch_type=stitch, colour_name=preset.name, colour_hex=preset.hex,
                                         weight_category=args.weight, fibre_content=args.fibre))
    except ValidationError as exc:
        parser.error(str(exc))
    return grid


def _estimated_cost(image_count: int, model: str) -> str:
    """'$1.23' for `image_count` images, or 'unknown (...)' when the model has no price (never '$0.00')."""
    tokens = CONFIG.cost.estimate_tokens
    try:
        return f"${image_count * price_per_image(model, tokens.input, tokens.output):.2f}"
    except UnknownModelError:
        return f"unknown (no price for model {model})"


def _generate_all(todo: list[SwatchInputs], provider, cache: SwatchCache, workers: int) -> int:
    """Generate the missing swatches in parallel. Exit code 1 if any fell back to a placeholder."""
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(lambda swatch: get_swatch(swatch, provider=provider, cache=cache), todo))
    failed = [result for result in results if result.source == "fallback"]
    logger.info("WARM generated=%d failed=%d (failures are not cached; re-run to retry)",
                len(results) - len(failed), len(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
