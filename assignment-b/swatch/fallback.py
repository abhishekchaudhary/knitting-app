"""Procedural placeholder swatch: the stitch's rough structure drawn in the target hex.

Shown instantly when image generation fails (and usable as the "show something
now" frame while the real image loads). Each stitch names a pattern in
config.yaml (`fallback:`); the pattern only varies lightness around the target
colour, so the image's median colour is the target hex.

Example: placeholder("cable", "#5B3E96") -> a 512x512 purple image with rope-like braids.
"""

from __future__ import annotations

import logging

import numpy as np
from PIL import Image

from swatch import colour, config  # module import: config validates stitch fallbacks against PATTERNS

logger = logging.getLogger("swatch")

# --- Drawing constants ---
# Size in pixels of one repeat of a stitch pattern.
_CELL_PX = 32
# How far (in LAB lightness units) the texture moves above and below the target colour.
_LIGHTNESS_AMPLITUDE = 14.0
# Colour used by flat() when even the hex code is unusable.
_FLAT_GREY_RGB = (154, 154, 154)


def flat(hex_code: str, size: int | None = None) -> Image.Image:
    """Last-resort image: a flat square in `hex_code` (grey if even the hex is unusable).

    The placeholder is the "always something to show" path, so it must not be able to raise.
    """
    size = size or config.CONFIG.image.store_px
    try:
        rgb = colour.hex_to_rgb(hex_code)
    except Exception:
        rgb = _FLAT_GREY_RGB
    return Image.new("RGB", (size, size), rgb)


def placeholder(stitch_type: str, hex_code: str, size: int | None = None) -> Image.Image:
    """Draw the stitch's placeholder pattern in `hex_code`; a flat square if anything goes wrong."""
    try:
        return _draw(stitch_type, hex_code, size)
    except Exception as exc:  # unknown stitch / pattern, bad hex: still show the colour
        logger.warning("SWATCH placeholder=flat reason=%r stitch=%r", f"{type(exc).__name__}: {exc}"[:80], stitch_type)
        return flat(hex_code, size)


def _draw(stitch_type: str, hex_code: str, size: int | None = None) -> Image.Image:
    """Texture from the stitch's pattern, centred on zero, applied as lightness around the target colour."""
    size = size or config.CONFIG.image.store_px
    pattern = PATTERNS[config.CONFIG.stitch(stitch_type).fallback]

    y_px, x_px = np.mgrid[0:size, 0:size].astype(float)
    texture = np.clip(pattern(x_px, y_px), -1.5, 1.5)
    # Centre on the median so the median pixel is exactly the target colour.
    texture -= np.median(texture)

    lab = np.broadcast_to(colour.hex_to_lab(hex_code), (size, size, 3)).copy()
    lab[..., 0] = np.clip(lab[..., 0] + _LIGHTNESS_AMPLITUDE * texture, 0, 100)
    return Image.fromarray(colour.lab_to_rgb(lab).round().astype(np.uint8), "RGB")


# --- Stitch patterns ---
# Each takes pixel coordinate grids (x_px, y_px) and returns a texture value per pixel:
# positive = lighter than the target colour, negative = darker.


def _vees(x_px: np.ndarray, y_px: np.ndarray) -> np.ndarray:
    """Stockinette: rows of small V shapes."""
    across_cell = (x_px % _CELL_PX) / _CELL_PX
    down_cell = (y_px % _CELL_PX) / _CELL_PX
    return np.cos(2 * np.pi * (down_cell - 1.2 * np.abs(across_cell - 0.5)))


def _ridges(x_px: np.ndarray, y_px: np.ndarray) -> np.ndarray:
    """Garter: horizontal ridges with a slight bump along each ridge."""
    return np.sin(2 * np.pi * y_px / (_CELL_PX / 2)) * (0.8 + 0.2 * np.cos(2 * np.pi * x_px / (_CELL_PX / 2)))


def _ribs(width: float):
    """Raised columns `width` px apart, separated by dark grooves; mostly mid-tone so the median stays on the target."""

    def pattern(x_px: np.ndarray, y_px: np.ndarray) -> np.ndarray:
        distance_to_groove = np.abs(((x_px + width / 2) % width) - width / 2)
        ridge_shading = 0.3 * np.cos(2 * np.pi * y_px / (_CELL_PX / 2))
        return -2.0 * np.exp(-(distance_to_groove**2) / (width / 5)) + ridge_shading

    return pattern


def _checker(x_px: np.ndarray, y_px: np.ndarray) -> np.ndarray:
    """Seed: a soft checkerboard of alternating bumps."""
    half_cell = _CELL_PX / 2
    return np.sin(np.pi * x_px / half_cell) * np.sin(np.pi * y_px / half_cell) * 1.6


def _braids(x_px: np.ndarray, y_px: np.ndarray) -> np.ndarray:
    """Cable: two ropes crossing in a wave down each column, on a faint seed background."""
    column_width = 3 * _CELL_PX
    x_from_column_centre = (x_px % column_width) - column_width / 2
    wave = (column_width / 4) * np.sin(2 * np.pi * y_px / (2 * _CELL_PX))
    left_rope = np.exp(-((x_from_column_centre - wave) ** 2) / 90)
    right_rope = np.exp(-((x_from_column_centre + wave) ** 2) / 90)
    rope = np.maximum(left_rope, right_rope)
    background = 0.25 * np.sin(np.pi * x_px / 6) * np.sin(np.pi * y_px / 6)
    return 2.2 * rope - 1 + background


def _eyelets(x_px: np.ndarray, y_px: np.ndarray) -> np.ndarray:
    """Lace: faint stockinette with dark round holes, every other column shifted half a cell down."""
    base = 0.35 * _vees(x_px, y_px)
    half_cell_shift = (x_px // _CELL_PX % 2) * _CELL_PX / 2
    x_from_hole = (x_px % _CELL_PX) - _CELL_PX / 2
    y_from_hole = ((y_px + half_cell_shift) % _CELL_PX) - _CELL_PX / 2
    holes = np.exp(-(x_from_hole**2 + y_from_hole**2) / 20)
    return base - 2.5 * holes


# Pattern name (as used by `fallback:` in config.yaml) -> drawing function.
PATTERNS = {
    "vees": _vees,
    "ridges": _ridges,
    "ribs_narrow": _ribs(_CELL_PX / 2),
    "ribs_wide": _ribs(_CELL_PX),
    "checker": _checker,
    "braids": _braids,
    "eyelets": _eyelets,
}
