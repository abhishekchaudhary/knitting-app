"""Colour maths: known LAB values, CIEDE2000 reference pair, round trip, tint moves ΔE under threshold."""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from swatch import colour
from swatch.config import CONFIG


@pytest.mark.parametrize(
    "hex_code,expected",
    [("#FFFFFF", (100.0, 0.0, 0.0)), ("#000000", (0.0, 0.0, 0.0)), ("#FF0000", (53.24, 80.09, 67.20))],
)
def test_hex_to_lab_known_values(hex_code, expected):
    assert colour.hex_to_lab(hex_code) == pytest.approx(expected, abs=0.05)


@pytest.mark.parametrize("hex_code", ["#5B3E96", "#2E6B3F", "#D4A017", "#000000", "#FFFFFF"])
def test_lab_round_trip(hex_code):
    rgb = np.array(colour.hex_to_rgb(hex_code), dtype=float)
    assert colour.lab_to_rgb(colour.rgb_to_lab(rgb)) == pytest.approx(rgb, abs=0.5)


def test_delta_e_sharma_reference_pair():
    assert colour.delta_e2000(np.array([50, 2.6772, -79.7751]), np.array([50, 0, -82.7485])) == pytest.approx(
        2.0425, abs=1e-3
    )


def test_delta_e_identical_is_zero():
    lab = colour.hex_to_lab("#5B3E96")
    assert colour.delta_e2000(lab, lab) == pytest.approx(0.0)


def test_bad_hex_rejected():
    with pytest.raises(ValueError):
        colour.hex_to_rgb("#12345")


def test_tint_moves_grey_texture_onto_target():
    rng = np.random.default_rng(0)
    grey = np.clip(150 + rng.normal(0, 20, (64, 64, 1)), 0, 255).repeat(3, axis=2).astype(np.uint8)
    image = Image.fromarray(grey, "RGB")
    target = "#5B3E96"
    assert colour.measure_delta_e(image, target) > CONFIG.colour.delta_e_threshold
    tinted = colour.tint(image, target)
    assert colour.measure_delta_e(tinted, target) < 3
    assert np.asarray(tinted).std() > 5  # texture survives


@pytest.mark.parametrize(
    "hex_code,word", [("#5B3E96", "purple"), ("#2E6B3F", "green"), ("#3B5B8C", "blue"), ("#9A9A9A", "grey")]
)
def test_describe_names_the_hue(hex_code, word):
    assert word in colour.describe(hex_code)
