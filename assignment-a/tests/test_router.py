"""router.route(): intent classification, param extraction, missing-param asks, declines.

Cases mirror evals/questions.jsonl;
the 3 brief §3.1 examples and all 5 decline cases are non-negotiable.
"""

from __future__ import annotations

import pytest

from assistant import router as router_module
from assistant.router import route


# --- brief §3.1 examples, verbatim -------------------------------------------


def test_brief_example_yarn_quantity():
    intent = route("How much DK yarn do I need for a 50 x 60cm blanket in stockinette?")
    assert intent.name == "yarn_quantity"
    assert intent.missing == []
    assert intent.params == {
        "width_cm": 50.0,
        "height_cm": 60.0,
        "weight": "light",
        "stitch": "stockinette",
    }


def test_brief_example_needle_recommendation():
    intent = route("What needle size should I use for worsted yarn for a scarf?")
    assert intent.name == "needle_recommendation"
    assert intent.missing == []
    assert intent.params["weight"] == "medium"
    assert intent.params["project"] == "scarf"


def test_brief_example_tension_diagnosis():
    intent = route("My swatch is 24 stitches per 10cm but the pattern says 22. What's wrong?")
    assert intent.name == "tension_diagnosis"
    assert intent.missing == []
    assert intent.params == {"actual_sts_10cm": 24.0, "target_sts_10cm": 22.0}


# --- yarn_quantity: units, phrasing variety ----------------------------------


@pytest.mark.parametrize(
    "question,width_cm,height_cm,weight,stitch",
    [
        (
            "I want to knit a cabled cushion cover 40cm by 40cm in aran yarn. How many metres and how many balls?",
            40.0, 40.0, "medium", "cable",
        ),
        ("How much chunky yarn for a 30 x 180 cm scarf in 1x1 rib?", 30.0, 180.0, "bulky", "rib_1x1"),
        (
            "Fingering weight lace shawl, 60cm wide and 150cm long. How much yarn should I buy?",
            60.0, 150.0, "super_fine", "lace",
        ),
        ("Scarf 8in by 60in in worsted, garter -- how many skeins?", 20.32, 152.4, "medium", "garter"),
        (
            "Baby blanket, 30 inches square, sport weight, seed stitch. How much yarn?",
            76.2, 76.2, "fine", "seed",
        ),
        (
            "A super chunky throw 100cm by 40 inches in stocking stitch -- how many balls?",
            100.0, 101.6, "super_bulky", "stockinette",
        ),
    ],
)
def test_yarn_quantity_variants(question, width_cm, height_cm, weight, stitch):
    intent = route(question)
    assert intent.name == "yarn_quantity"
    assert intent.missing == []
    assert intent.params["width_cm"] == pytest.approx(width_cm)
    assert intent.params["height_cm"] == pytest.approx(height_cm)
    assert intent.params["weight"] == weight
    assert intent.params["stitch"] == stitch


@pytest.mark.parametrize(
    "question,width_cm,height_cm",
    [
        ("How much DK yarn for a 50cm x 60 blanket?", 50.0, 60.0),
        ("How much chunky yarn for a 1.5m x 2m throw?", 150.0, 200.0),
        ("How much DK yarn for a 50 × 60 cm blanket in 1x1 rib?", 50.0, 60.0),
    ],
)
def test_more_dimension_formats(question, width_cm, height_cm):
    intent = route(question)
    assert (intent.params["width_cm"], intent.params["height_cm"]) == (width_cm, height_cm)


def test_spaced_in_is_not_inches():
    """"60 in stockinette" is not 60 inches; the unit-less pair is read as cm instead."""
    intent = route("How much DK yarn for a 50 x 60 in stockinette?")
    assert (intent.params["width_cm"], intent.params["height_cm"]) == (50.0, 60.0)
    assert intent.missing == []
    assert intent.assumptions == [router_module.UNITLESS_DIMENSION_ASSUMPTION]


def test_yarn_quantity_gauge_override_extracted():
    intent = route(
        "How much DK yarn do I need for a 50 x 60cm blanket in stockinette "
        "if my gauge is 26 stitches per 10cm?"
    )
    assert intent.params["gauge_sts_10cm"] == 26.0


# --- needle_recommendation ----------------------------------------------------


@pytest.mark.parametrize(
    "question,weight,project,fabric",
    [
        ("Which needles for a drapey shawl in fingering?", "super_fine", "shawl", "drapey"),
        (
            "I'm knitting socks with sock yarn and want a firm fabric. What size needles in US and UK?",
            "super_fine", "socks", "firm",
        ),
        ("What needles for a chunky blanket with a balanced fabric?", "bulky", "blanket", "balanced"),
        ("Needle size for a jumbo yarn hat?", "jumbo", "hat", None),
    ],
)
def test_needle_recommendation_variants(question, weight, project, fabric):
    intent = route(question)
    assert intent.name == "needle_recommendation"
    assert intent.missing == []
    assert intent.params["weight"] == weight
    assert intent.params["project"] == project
    if fabric is not None:
        assert intent.params["fabric"] == fabric
    else:
        assert "fabric" not in intent.params


# --- tension_diagnosis ---------------------------------------------------------


def test_tension_pattern_gauge_getting():
    intent = route("Pattern gauge is 18 sts over 10cm, I'm getting 15. Is that a problem?")
    assert intent.params == {"actual_sts_10cm": 15.0, "target_sts_10cm": 18.0}


def test_tension_i_got_pattern_wants():
    intent = route("I got 21.5 stitches per 10cm and the pattern wants 22 -- should I change needles?")
    assert intent.params == {"actual_sts_10cm": 21.5, "target_sts_10cm": 22.0}


# --- missing-param asks ---------------------------------------------------------


def test_ask_tension_no_numbers():
    intent = route("Why is my tension off?")
    assert intent.name == "tension_diagnosis"
    assert set(intent.missing) == {"actual_sts_10cm", "target_sts_10cm"}


def test_ask_yarn_quantity_no_dims_no_weight():
    intent = route("How much yarn for a hat?")
    assert intent.name == "yarn_quantity"
    assert set(intent.missing) == {"width_cm", "height_cm", "weight"}
    assert "stitch" not in intent.params  # calculator default (stockinette) applies


def test_ask_yarn_quantity_no_dims_has_weight_and_stitch():
    intent = route("How much worsted do I need for a blanket in garter stitch?")
    assert intent.name == "yarn_quantity"
    assert set(intent.missing) == {"width_cm", "height_cm"}
    assert intent.params["weight"] == "medium"
    assert intent.params["stitch"] == "garter"


# --- declines --------------------------------------------------------------------


@pytest.mark.parametrize(
    "question",
    [
        "Is merino warmer than acrylic?",
        "How much yarn for a size M raglan sweater?",
        "What crochet hook size should I use for granny squares in DK?",
        "Will two skeins from different dye lots look different in my blanket?",
        "How long will it take me to knit a 50 x 60cm blanket?",
    ],
)
def test_declines(question):
    intent = route(question)
    assert intent.name == "unsupported"
    assert intent.decline_reason


# --- regression cases --------------------------------------------------------


@pytest.mark.parametrize(
    "question,gauge",
    [
        ("How much DK yarn do I need for a 50 x 60cm blanket, I knit 24 sts to 10cm", 24.0),
        ("How much DK yarn for a 50 x 60cm blanket at 24 stitches per 10cm?", 24.0),
        ("How much DK yarn for a 50 x 60cm blanket, 24 sts/10cm", 24.0),
        ("How much DK yarn for a 50 x 60cm blanket at 22 stitches over 4 inches?", 22.0),
        ("How much DK yarn for a 50 x 60cm blanket at 22 sts over 4in?", 22.0),
        ("How much DK yarn for a 50 x 60cm blanket if my gauge is 26?", 26.0),
    ],
)
def test_gauge_phrasings_extracted(question, gauge):
    intent = route(question)
    assert intent.params["gauge_sts_10cm"] == pytest.approx(gauge, abs=0.05)


@pytest.mark.parametrize(
    "question",
    [
        "How much yarn do I need for a 50 x 60cm baby blanket?",
        "How much yarn for a 50 x 60cm rug?",
        "How much yarn for a 50 x 60cm afghan?",
        "What needles for a baby cardigan?",
        "What needles for a light, airy scarf?",
    ],
)
def test_project_words_are_not_weights(question):
    intent = route(question)
    assert "weight" not in intent.params
    assert "weight" in intent.missing


@pytest.mark.parametrize(
    "question,weight",
    [
        ("How much worsted do I need for a 50 x 60cm blanket?", "medium"),
        ("How much DK yarn for a 50 x 60cm blanket?", "light"),
        ("How much baby weight yarn for a 50 x 60cm blanket?", "super_fine"),
        ("How much yarn for a 50 x 60cm blanket in baby?", "super_fine"),
        ("How much chunky for a 50 x 60cm blanket?", "bulky"),
    ],
)
def test_unambiguous_weight_words_still_read(question, weight):
    assert route(question).params["weight"] == weight


def test_decimal_comma():
    intent = route("How much DK yarn for a 50,5 x 60cm blanket?")
    assert intent.params["width_cm"] == pytest.approx(50.5)
    assert intent.params["height_cm"] == pytest.approx(60.0)


def test_negative_dimension_kept_for_the_calculator():
    intent = route("How much DK yarn for a -50 x 60cm blanket?")
    assert intent.params["width_cm"] == pytest.approx(-50.0)


def test_thousands_separator_not_split_in_llm_cross_check():
    from assistant.providers import router_schema
    from assistant.router import intent_from_llm

    payload = {key: None for key in router_schema()["properties"]}
    payload.update(intent="yarn_quantity", width=1000, width_unit="cm", height=60,
                   height_unit="cm", weight="light")
    intent = intent_from_llm("How much DK yarn for a 1,000 x 60cm blanket?", payload)
    assert intent is not None
    assert intent.params["width_cm"] == pytest.approx(1000.0)


@pytest.mark.parametrize(
    "question,actual,target",
    [
        ("I'm getting 20 stitches per 10cm but the pattern says 18. What's wrong?", 20.0, 18.0),
        ("my gauge is 18 stitches per 10 cm and the pattern wants 20", 18.0, 20.0),
        ("My swatch is 24 stitches per 10cm but the pattern calls for 22.", 24.0, 22.0),
    ],
)
def test_tension_phrasings_route(question, actual, target):
    intent = route(question)
    assert intent.name == "tension_diagnosis"
    assert intent.params == {"actual_sts_10cm": actual, "target_sts_10cm": target}


@pytest.mark.parametrize(
    "question",
    [
        "My swatch is 24 rows per 10cm but the pattern says 30 rows.",
        "I'm getting 28 rows per 10cm and the pattern wants 32 rows.",
    ],
)
def test_row_gauge_declines_with_its_own_reason(question):
    intent = route(question)
    assert intent.name == "unsupported"
    assert "row gauge" in (intent.decline_reason or "")


def test_lace_weight_is_not_also_the_lace_stitch():
    intent = route("How much lace yarn for a 50 x 60cm blanket?")
    assert intent.params["weight"] == "lace"
    assert "stitch" not in intent.params


def test_lace_stitch_still_read_when_named_as_a_stitch():
    intent = route("How much DK yarn for a 50 x 60cm blanket in lace stitch?")
    assert intent.params["weight"] == "light"
    assert intent.params["stitch"] == "lace"


def test_unknown_stitch_asks_instead_of_defaulting():
    intent = route("How much DK yarn for a 50 x 60cm blanket in wibble stitch?")
    assert intent.name == "yarn_quantity"
    assert "stitch" in intent.missing


def test_unitless_dimension_pair_read_as_cm():
    intent = route("How much DK yarn for a 50x60 blanket?")
    assert (intent.params["width_cm"], intent.params["height_cm"]) == (50.0, 60.0)
    assert intent.missing == []


def test_small_unitless_pair_is_still_a_stitch_ratio():
    intent = route("How much DK yarn for a blanket in 1x1 rib?")
    assert set(intent.missing) == {"width_cm", "height_cm"}


def test_fabric_vocabulary_comes_from_the_domain():
    from assistant import router as router_module
    from assistant.providers import router_schema
    from knitcalc.domain import DOMAIN

    expected = tuple(DOMAIN.needle_recommender.fabric.model_dump())
    assert router_module.FABRIC_TOKENS == expected
    assert [v for v in router_schema()["properties"]["fabric"]["enum"] if v] == list(expected)


def test_llm_unsupported_loses_to_a_complete_rules_intent(caplog):
    import logging

    from assistant.providers import router_schema
    from assistant.router import intent_from_llm

    payload = {key: None for key in router_schema()["properties"]}
    payload.update(intent="unsupported", decline_category="other")
    with caplog.at_level(logging.INFO, logger="assistant"):
        intent = intent_from_llm(
            "How much DK yarn do I need for a 50 x 60cm blanket in stockinette?", payload
        )
    assert intent is not None and intent.name == "yarn_quantity"
    assert "ROUTE_DISAGREE" in caplog.text


def test_four_inch_gauge_is_the_same_statement_as_10cm():
    """CYC prints "sts per 4 inches (10 cm)": 4 in names the 10 cm swatch, it is not
    a length to convert. "20 sts to 4in" and "20 sts per 10cm" must be identical."""
    four_in = route("How much DK yarn for a 50 x 60cm blanket, my gauge is 20 sts to 4in")
    ten_cm = route("How much DK yarn for a 50 x 60cm blanket, my gauge is 20 sts per 10cm")
    assert four_in.params["gauge_sts_10cm"] == 20.0
    assert four_in.params == ten_cm.params


# --- the cross-check carries the rule router's findings, never drops them ------


def _llm_payload(**overrides):
    from assistant.providers import router_schema

    payload = {key: None for key in router_schema()["properties"]}
    payload.update(overrides)
    return payload


def test_llm_cannot_lose_a_specific_rules_decline(caplog):
    """ho-09: row gauge. The LLM reads it as tension with no numbers, which would ask the
    knitter for stitch counts they never mentioned; the rules' decline must win."""
    import logging

    from assistant.router import intent_from_llm

    question = "My swatch is 32 rows per 10cm but the pattern wants 28 rows. What's wrong?"
    with caplog.at_level(logging.INFO, logger="assistant"):
        intent = intent_from_llm(question, _llm_payload(intent="tension_diagnosis"))
    assert intent is not None
    assert intent.name == "unsupported"
    assert "row gauge" in (intent.decline_reason or "")
    assert "ROUTE_DISAGREE" in caplog.text


def test_llm_cannot_lose_a_rules_missing_field(caplog):
    """Like ho-10: an unknown stitch has no multiplier. The LLM omits `stitch`, which would answer
    silently as stockinette; the rules' missing field must survive."""
    import logging

    from assistant.router import intent_from_llm

    question = "How much DK yarn for a 50 x 60cm blanket in wibble stitch?"
    payload = _llm_payload(
        intent="yarn_quantity", width=50, width_unit="cm", height=60, height_unit="cm",
        weight="light",
    )
    with caplog.at_level(logging.INFO, logger="assistant"):
        intent = intent_from_llm(question, payload)
    assert intent is not None
    assert intent.name == "yarn_quantity"
    assert "stitch" in intent.missing
    assert intent.params["width_cm"] == 50.0  # the LLM's reading is kept
    assert "ROUTE_DISAGREE" in caplog.text


def test_llm_values_still_beat_a_rules_blind_spot():
    """The carry-over must not undo the point of the LLM route: a field the LLM read and
    the rules could not is kept, not turned into a question."""
    from assistant.router import intent_from_llm, route

    question = "I need yarn for a blanket that is fifty by sixty centimetres, in DK."
    assert set(route(question).missing) == {"width_cm", "height_cm"}
    payload = _llm_payload(
        intent="yarn_quantity", width=50, width_unit="cm", height=60, height_unit="cm",
        weight="light",
    )
    intent = intent_from_llm(question.replace("fifty by sixty", "50 by 60"), payload)
    assert intent is not None and intent.missing == []


def test_generic_rules_decline_does_not_override_a_good_llm_reading():
    """Only a *specific* decline carries over: the rules' catch-all "only answers ..."
    is exactly the case the LLM route exists to rescue."""
    from assistant.router import intent_from_llm, route

    question = "I'd like to make something 50 x 60cm out of DK. What do I buy?"
    assert route(question).name == "unsupported"
    payload = _llm_payload(
        intent="yarn_quantity", width=50, width_unit="cm", height=60, height_unit="cm",
        weight="light",
    )
    intent = intent_from_llm(question, payload)
    assert intent is not None and intent.name == "yarn_quantity"


def test_technique_questions_decline_with_their_own_reason():
    """ho-12: cast-on choice is technique advice; no calculator stands behind it, and the
    "4ply" in the question must not turn it into a needle recommendation."""
    intent = route("Which cast-on should I use for a stretchy sock cuff in 4ply?")
    assert intent.name == "unsupported"
    assert intent.decline_reason in router_module.SPECIFIC_DECLINE_REASONS
    assert "technique" in (intent.decline_reason or "")


@pytest.mark.parametrize(
    "question",
    [
        "What's the best bind-off for a shawl edge?",
        "How do I pick up stitches around a neckline in DK?",
        "Should I use mattress stitch or backstitch to seam a worsted jumper?",
        "What's the best way of blocking a 50 x 60cm lace blanket?",
    ],
)
def test_more_technique_questions_decline(question):
    assert route(question).name == "unsupported"


def test_llm_technique_reading_loses_to_the_specific_decline(caplog):
    import logging

    from assistant.router import intent_from_llm

    question = "Which cast-on should I use for a stretchy sock cuff in 4ply?"
    payload = _llm_payload(intent="needle_recommendation", weight="super_fine", project="socks")
    with caplog.at_level(logging.INFO, logger="assistant"):
        intent = intent_from_llm(question, payload)
    assert intent is not None and intent.name == "unsupported"
    assert "technique" in (intent.decline_reason or "")
    assert "ROUTE_DISAGREE" in caplog.text


def test_llm_may_not_source_a_weight_from_an_ambiguous_alias_alone(caplog):
    """ho-03: "baby blanket" is a project, not super fine yarn. 660 m of super fine for a
    blanket is the expensive wrong answer, so the ask must survive the LLM's confidence."""
    import logging

    from assistant.router import intent_from_llm

    question = "How much yarn for a 50 x 60cm baby blanket?"
    payload = _llm_payload(
        intent="yarn_quantity", width=50, width_unit="cm", height=60, height_unit="cm",
        weight="super_fine",
    )
    with caplog.at_level(logging.INFO, logger="assistant"):
        intent = intent_from_llm(question, payload)
    assert intent is not None
    assert intent.name == "yarn_quantity"
    assert "weight" not in intent.params
    assert "weight" in intent.missing
    assert "ROUTE_DISAGREE" in caplog.text


@pytest.mark.parametrize(
    "question,weight",
    [
        ("How much baby weight yarn for a 50 x 60cm blanket?", "super_fine"),
        ("How much yarn for a 50 x 60cm blanket in baby?", "super_fine"),
        ("How much DK yarn for a 50 x 60cm baby blanket?", "light"),
    ],
)
def test_llm_weight_survives_when_the_question_really_states_it(question, weight):
    from assistant.router import intent_from_llm

    payload = _llm_payload(
        intent="yarn_quantity", width=50, width_unit="cm", height=60, height_unit="cm",
        weight=weight,
    )
    intent = intent_from_llm(question, payload)
    assert intent is not None
    assert intent.params["weight"] == weight
    assert intent.missing == []


@pytest.mark.parametrize(
    "question,intent_name",
    [
        ("How much DK yarn for a 50 x 60cm blanket after blocking?", "yarn_quantity"),
        (
            "My swatch is 24 stitches per 10cm but the pattern says 22, "
            "measured after blocking. What's wrong?",
            "tension_diagnosis",
        ),
        ("How much DK yarn for a 50 x 60cm blanket with seams?", "yarn_quantity"),
    ],
)
def test_technique_word_in_passing_does_not_block_a_calculation(question, intent_name):
    """Knitters say "after blocking" and "with seams" as modifiers on a calculation.
    The technique decline is for questions *about* the technique (ho-12), not these."""
    intent = route(question)
    assert intent.name == intent_name
    assert intent.missing == []
