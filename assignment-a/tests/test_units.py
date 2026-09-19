"""cm<->in and needle mm<->US<->UK conversions round-trip correctly."""

from __future__ import annotations

import pytest

from knitcalc.units import cm_to_in, convert_needle, in_to_cm, needle_row_for


def test_cm_in_round_trip():
    assert in_to_cm(cm_to_in(50.0)) == pytest.approx(50.0)


def test_cm_to_in_known_value():
    assert cm_to_in(2.54) == pytest.approx(1.0)


def test_needle_mm_to_us_to_mm_round_trip():
    match_us = convert_needle(4.0, "mm", "us")
    assert match_us.row.us == "6"
    match_mm = convert_needle("6", "us", "mm")
    assert match_mm.row.mm == pytest.approx(4.0)


def test_needle_mm_to_uk_to_mm_round_trip():
    match_uk = convert_needle(4.5, "mm", "uk")
    assert match_uk.row.uk == "7"
    match_mm = convert_needle("7", "uk", "mm")
    assert match_mm.row.mm == pytest.approx(4.5)


def test_needle_us_has_no_uk_flagged_approx():
    # US 4 (3.5mm) has no UK row at that exact mm in the table
    match = convert_needle("4", "us", "uk")
    assert match.exact is False
    assert match.row.uk is not None


def test_needle_mm_nearest_when_no_exact_row():
    match = needle_row_for(4.3, "mm")
    assert match.exact is False
    assert match.row.mm in (4.0, 4.5)


def test_needle_unknown_label_raises():
    with pytest.raises(ValueError):
        needle_row_for("999", "us")


def test_needle_boundaries_lace_and_jumbo():
    lace_min = needle_row_for(1.5, "mm")
    assert lace_min.row.mm == 1.5
    jumbo_max = needle_row_for(25.0, "mm")
    assert jumbo_max.row.mm == 25.0
