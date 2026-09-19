"""guard: numbers must be CalcResult values of the matching kind.

Uses real calculator results so the allow-list is the one users actually get:
yarn 50x60cm DK -> 429.0 m, 4 balls; needle worsted scarf -> 5.0 mm, US 8, UK 6;
tension 24 vs 22 -> too tight, 9.1%.
"""

from __future__ import annotations

import pytest

from assistant import guard
from knitcalc.calculators import needle_recommendation, tension_diagnosis, yarn_quantity

YARN = yarn_quantity(50, 60, "dk")
NEEDLE = needle_recommendation("worsted", project="scarf")
TENSION = tension_diagnosis(24, 22)


@pytest.mark.parametrize(
    "calc,text",
    [
        (YARN, "You'll need about 429.0 m of yarn, which is 4 balls."),
        (YARN, "Plan on roughly 429 metres (4 balls) for your 50cm x 60cm blanket."),
        (YARN, "That's 429m. It includes a 10% safety margin and assumes 22.5 sts per 10cm."),
        (YARN, "Each 50g ball has 120 m, so buy 4 balls: 429 m in total."),
        (YARN, "For 1x1 rib the number changes, but for stockinette it's 429 m / 4 balls."),
        (NEEDLE, "Use a 5.0mm needle (US 8, UK 6); the usual range is 4.5-5.5mm."),
        (TENSION, "Your gauge is too tight (moderate, 9.1% off). Go up about 0.5mm."),
        (TENSION, "Aim for 22 stitches per 10 cm instead of 24 sts."),
        (TENSION, "One needle size (~0.25mm) changes gauge by about one stitch per 10cm."),
    ],
)
def test_honest_replies_pass(calc, text):
    assert guard.find_leaks(text, calc) == []


@pytest.mark.parametrize(
    "calc,text,leak",
    [
        (YARN, "You need 60 balls.", 60.0),             # 60 is the height, not a ball count
        (YARN, "You need 3 balls and 429 m.", 3.0),     # wrong count by one
        (YARN, "You'll need 900g of yarn.", 900.0),     # unit phrases are checked, not skipped
        (YARN, "Buy 12 in total, about 429 m.", 12.0),  # "in" read as inches: fails safe
        (YARN, "Get 7 x 50 balls.", 50.0),
        (YARN, "About twelve balls should do.", 12.0),  # number words next to a unit
        (YARN, "That's 429 m and costs about $45.", 45.0),
        (NEEDLE, "Use a 3.5mm needle.", 3.5),
        (NEEDLE, "Use a US 7 needle.", 7.0),
        (TENSION, "You're 20% off.", 20.0),
    ],
)
def test_leaks_are_caught(calc, text, leak):
    assert leak in guard.find_leaks(text, calc)


def test_metres_use_a_rounding_tolerance_not_a_percentage():
    """429.0 m may be written 429; 446 m is a different number, not a rounding."""
    assert guard.verify("You'll need about 429 m -- 4 balls.", YARN)
    assert not guard.verify("You'll need about 446 m -- 4 balls.", YARN)   # +4%, inside 5%
    assert not guard.verify("You'll need about 430 m -- 4 balls.", YARN)


def test_negative_diff_reported_as_positive_percent():
    loose = tension_diagnosis(15, 18)
    assert loose.result["diff_pct"] < 0
    assert guard.verify(f"You're {abs(loose.result['diff_pct'])}% too loose.", loose)


def test_range_hyphen_is_not_a_minus_sign():
    assert guard.extract_numbers("4.5-5.5mm") == [4.5, 5.5]


def test_inches_restated_from_the_question_pass():
    calc = yarn_quantity(20.32, 152.4, "worsted", "garter")
    text = (
        f"For your 8in x 60in scarf you need about {calc.result['metres']} m "
        f"-- {calc.result['balls']} skeins."
    )
    assert guard.verify(text, calc)


def test_template_replies_always_pass():
    from assistant.phraser import template_reply

    for name, calc in [("yarn_quantity", YARN), ("needle_recommendation", NEEDLE), ("tension_diagnosis", TENSION)]:
        assert guard.verify(template_reply(name, calc), calc), name


def test_no_numbers_no_leaks():
    assert guard.find_leaks("Swatch first, then decide.", YARN) == []


# --- the claim, not just the numbers --------------------------------------------


@pytest.mark.parametrize(
    "calc,text",
    [
        # every number is real; the sentence still misinforms the knitter
        (TENSION, "Your gauge is too loose (moderate, 9.1% off). Go down about 0.5mm."),
        (YARN, "You'll need about 120 m of yarn, so buy 4 balls."),  # 120 m is one ball
        (YARN, "You'll need about 13 m."),                            # m per 100 sq cm
        (YARN, "You'll need five."),                                  # no headline at all
        (NEEDLE, "Your range is 4.5-5.5mm, so pick whichever you like."),
    ],
)
def test_true_numbers_with_a_false_claim_are_rejected(calc, text):
    assert not guard.verify(text, calc)


def test_unlabelled_numbers_match_the_result_only():
    text = "You'll need about 429.0 m -- 4 balls. Rest for 10 minutes first."
    assert guard.find_leaks(text, YARN) == [10.0]


@pytest.mark.parametrize(
    "calc,text",
    [
        (YARN, "You'll need about 429.0 m -- 4 balls. In k2p2 rib, add a little."),
        (YARN, "You'll need about 429.0 m -- 4 balls of DK (8 ply)."),
        (TENSION, "Your gauge is too tight (moderate, 9.1% off); go up 2 needle sizes."),
    ],
)
def test_knitting_notation_is_not_a_leaked_number(calc, text):
    assert guard.find_leaks(text, calc) == []
    assert guard.verify(text, calc)


def test_problems_name_what_failed():
    problems = guard.problems("Your gauge is too loose (moderate, 9.1% off).", TENSION)
    assert any("contradiction" in p for p in problems)
