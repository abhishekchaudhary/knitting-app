"""Placeholder: one pattern per stitch, dominant colour is the target hex, patterns differ by stitch."""

from __future__ import annotations

import numpy as np
import pytest

from swatch import colour
from swatch.config import CONFIG
from swatch.fallback import PATTERNS, placeholder

STITCHES = [s.key for s in CONFIG.stitches.items]


def test_every_stitch_has_a_fallback_pattern():
    assert {s.fallback for s in CONFIG.stitches.items} <= set(PATTERNS)


@pytest.mark.parametrize("stitch", STITCHES)
@pytest.mark.parametrize("hex_code", ["#5B3E96", "#D4A017", "#D8CBB0"])
def test_placeholder_dominant_colour_is_target(stitch, hex_code):
    image = placeholder(stitch, hex_code, size=128)
    assert colour.measure_delta_e(image, hex_code) < 3


def test_placeholders_differ_by_stitch():
    arrays = {s: np.asarray(placeholder(s, "#5B3E96", size=96), dtype=float) for s in STITCHES}
    assert np.abs(arrays["cable"] - arrays["rib_1x1"]).mean() > 3
    assert np.abs(arrays["stockinette"] - arrays["garter"]).mean() > 3


def test_unknown_stitch_still_yields_a_flat_target_colour(caplog):
    """The placeholder is the always-something-to-show path, so it must never raise."""
    import logging

    from swatch.fallback import flat

    with caplog.at_level(logging.WARNING, logger="swatch"):
        image = placeholder("moss-diamond-brioche", "#5B3E96", size=64)
    assert image.size == (64, 64)
    assert colour.measure_delta_e(image, "#5B3E96") < 1
    assert "placeholder=flat" in caplog.text
    assert flat("not-a-hex", size=8).size == (8, 8)
