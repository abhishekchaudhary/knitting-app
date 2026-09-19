"""yarn_quantity, needle_recommendation, tension_diagnosis: boundary cases,
bad input rejection, and directional sanity (tighter gauge -> more yarn)."""

from __future__ import annotations

import pytest

from knitcalc.calculators import (
    needle_recommendation,
    tension_diagnosis,
    yarn_quantity,
)


# --- yarn_quantity ----------------------------------------------------------

def test_yarn_quantity_basic_dk_blanket():
    r = yarn_quantity(50, 60, "dk", "stockinette")
    assert r.result["metres"] > 0
    assert r.result["balls"] >= 1


def test_yarn_quantity_lace_boundary():
    r = yarn_quantity(100, 100, "lace", "lace")
    assert r.result["metres"] > 0


def test_yarn_quantity_jumbo_boundary():
    r = yarn_quantity(100, 100, "jumbo", "stockinette")
    assert r.result["metres"] > 0


@pytest.mark.parametrize("width,height", [(0, 60), (50, 0), (-10, 60), (50, -5)])
def test_yarn_quantity_rejects_nonpositive_dims(width, height):
    with pytest.raises(ValueError):
        yarn_quantity(width, height, "dk")


def test_yarn_quantity_unknown_weight_rejected():
    with pytest.raises(ValueError):
        yarn_quantity(50, 60, "nonexistent-weight")


def test_yarn_quantity_unknown_stitch_rejected():
    with pytest.raises(ValueError):
        yarn_quantity(50, 60, "dk", "nonexistent-stitch")


def test_yarn_quantity_tighter_gauge_uses_more_yarn():
    loose = yarn_quantity(50, 60, "dk", "stockinette", gauge_sts_10cm=20)
    tight = yarn_quantity(50, 60, "dk", "stockinette", gauge_sts_10cm=26)
    assert tight.result["metres"] > loose.result["metres"]


def test_yarn_quantity_cable_uses_more_than_stockinette():
    stock = yarn_quantity(50, 50, "medium", "stockinette")
    cable = yarn_quantity(50, 50, "medium", "cable")
    assert cable.result["metres"] > stock.result["metres"]


def test_yarn_quantity_lace_stitch_uses_less_than_stockinette():
    stock = yarn_quantity(50, 50, "medium", "stockinette")
    lace = yarn_quantity(50, 50, "medium", "lace")
    assert lace.result["metres"] < stock.result["metres"]


def test_yarn_quantity_imperial_caller_converts_before_calling():
    # units.cm_to_in / in_to_cm handle the conversion; calculator itself is cm-only
    from knitcalc.units import in_to_cm

    width_cm = in_to_cm(8)
    height_cm = in_to_cm(60)
    r = yarn_quantity(width_cm, height_cm, "medium", "garter")
    assert r.result["metres"] > 0


# --- needle_recommendation ---------------------------------------------------

def test_needle_recommendation_worsted_scarf_default():
    r = needle_recommendation("worsted")
    assert r.result["range_min_mm"] == 4.5
    assert r.result["range_max_mm"] == 5.5
    assert r.result["range_min_mm"] <= r.result["metric_mm"] <= r.result["range_max_mm"]


def test_needle_recommendation_socks_nudge_smaller():
    """Strict: a >= would also pass if the socks nudge were ignored entirely."""
    balanced = needle_recommendation("super_fine", project="scarf")
    socks = needle_recommendation("super_fine", project="socks")
    assert socks.result["metric_mm"] < balanced.result["metric_mm"]
    assert (socks.result["metric_mm"], balanced.result["metric_mm"]) == (2.25, 2.75)


def test_needle_recommendation_shawl_nudge_larger():
    """Strict: the shawl nudge must actually move the recommendation up a row."""
    balanced = needle_recommendation("light", project="scarf")
    shawl = needle_recommendation("light", project="shawl")
    assert shawl.result["metric_mm"] > balanced.result["metric_mm"]
    assert (balanced.result["metric_mm"], shawl.result["metric_mm"]) == (4.0, 4.5)


def test_needle_recommendation_fabric_firm_vs_drapey():
    """Strict: firm/drapey must land on different rows, at the ends of the CYC range."""
    firm = needle_recommendation("medium", fabric="firm")
    drapey = needle_recommendation("medium", fabric="drapey")
    assert firm.result["metric_mm"] < drapey.result["metric_mm"]
    assert (firm.result["metric_mm"], drapey.result["metric_mm"]) == (4.5, 5.5)


def test_needle_recommendation_boundaries_lace_and_jumbo():
    lace = needle_recommendation("lace")
    assert 1.5 <= lace.result["metric_mm"] <= 2.25
    jumbo = needle_recommendation("jumbo")
    assert 12.75 <= jumbo.result["metric_mm"] <= 25.0


def test_needle_recommendation_unknown_weight_rejected():
    with pytest.raises(ValueError):
        needle_recommendation("nonexistent-weight")


def test_needle_recommendation_unknown_fabric_rejected():
    with pytest.raises(ValueError):
        needle_recommendation("worsted", fabric="squishy")


# --- tension_diagnosis --------------------------------------------------------

def test_tension_too_tight_suggests_up():
    r = tension_diagnosis(actual_sts_10cm=24, target_sts_10cm=22)
    assert r.result["diagnosis"] == "too tight"
    assert r.result["suggested_needle_change_mm"] > 0


def test_tension_too_loose_suggests_down():
    r = tension_diagnosis(actual_sts_10cm=20, target_sts_10cm=22)
    assert r.result["diagnosis"] == "too loose"


def test_tension_on_gauge():
    r = tension_diagnosis(actual_sts_10cm=22, target_sts_10cm=22)
    assert r.result["diagnosis"] == "on gauge"
    assert r.result["diff_pct"] == 0.0


def test_tension_severity_bands():
    minor = tension_diagnosis(actual_sts_10cm=22.5, target_sts_10cm=22)  # ~2.3%
    moderate = tension_diagnosis(actual_sts_10cm=24, target_sts_10cm=22)  # ~9%
    major = tension_diagnosis(actual_sts_10cm=26, target_sts_10cm=22)  # ~18%
    assert minor.result["severity"] == "minor"
    assert moderate.result["severity"] == "moderate"
    assert major.result["severity"] == "major"


def test_tension_substitution_suggested_only_above_threshold():
    minor = tension_diagnosis(actual_sts_10cm=22.5, target_sts_10cm=22)
    major = tension_diagnosis(actual_sts_10cm=26, target_sts_10cm=22)
    assert "consider_yarn_substitution" not in minor.result["fixes"]
    assert "consider_yarn_substitution" in major.result["fixes"]


@pytest.mark.parametrize("actual,target", [(0, 22), (24, 0), (-5, 22), (24, -5)])
def test_tension_rejects_nonpositive_input(actual, target):
    with pytest.raises(ValueError):
        tension_diagnosis(actual, target)


# --- brief examples: pinned golden values ------------------------------------

def test_brief_examples_exact_values():
    """The brief's own three worked examples (§3.1), pinned to exact numbers.

    Every other test here asserts `> 0` or an ordering, so a change to
    `domain.yaml` (e.g. m_per_100cm2 13 -> 31) would slide silently through the
    whole suite. This test is the tripwire: a DELIBERATE change to domain.yaml
    is EXPECTED to break it, and the fix is to re-derive these numbers from the
    new constants and update them here in the same commit.
    """
    yarn = yarn_quantity(50, 60, "dk")
    assert yarn.result["metres"] == 429.0
    assert yarn.result["balls"] == 4

    needle = needle_recommendation("worsted", project="scarf")
    assert needle.result["metric_mm"] == 5.0
    assert needle.result["us"] == "8"
    assert needle.result["uk"] == "6"

    tension = tension_diagnosis(24, 22)
    assert tension.result["diff_pct"] == 9.1
    assert tension.result["diagnosis"] == "too tight"
    assert tension.result["severity"] == "moderate"
    assert tension.result["suggested_needle_change_mm"] == 0.5
