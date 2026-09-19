"""assistant.answer(): offline end-to-end (router -> calculators -> phraser -> guard).

Must hold: 100% intent accuracy on the 3 brief §3.1 examples, and every
decline case declines.
"""

from __future__ import annotations

import pytest

from assistant.assistant import answer
from assistant.providers import RuleProvider


class LeakyProvider(RuleProvider):
    """Test double: routes correctly, but its draft invents a number CalcResult never produced."""

    name = "leaky"
    kind = "llm"

    def phrase(self, question, intent_name, calc, timeout_s=None):
        return "That'll cost about $45 and take 823.456m of yarn."


def test_brief_yarn_quantity_end_to_end():
    r = answer("How much DK yarn do I need for a 50 x 60cm blanket in stockinette?")
    assert r.intent == "yarn_quantity"
    assert r.calc is not None
    assert not r.guard_rejected
    assert str(r.calc.result["metres"]) in r.reply
    assert str(r.calc.result["balls"]) in r.reply


def test_brief_needle_recommendation_end_to_end():
    r = answer("What needle size should I use for worsted yarn for a scarf?")
    assert r.intent == "needle_recommendation"
    assert r.calc is not None
    assert not r.guard_rejected


def test_brief_tension_diagnosis_end_to_end():
    r = answer("My swatch is 24 stitches per 10cm but the pattern says 22. What's wrong?")
    assert r.intent == "tension_diagnosis"
    assert r.calc is not None
    assert not r.guard_rejected
    assert "tight" in r.reply.lower()


def test_decline_states_a_reason():
    r = answer("Is merino warmer than acrylic?")
    assert r.intent == "unsupported"
    assert r.calc is None
    assert "can't answer" in r.reply.lower()
    assert r.decline_reason


@pytest.mark.demo
def test_all_five_decline_cases_decline():
    questions = [
        "Is merino warmer than acrylic?",
        "How much yarn for a size M raglan sweater?",
        "What crochet hook size should I use for granny squares in DK?",
        "Will two skeins from different dye lots look different in my blanket?",
        "How long will it take me to knit a 50 x 60cm blanket?",
    ]
    for q in questions:
        r = answer(q)
        assert r.intent == "unsupported", q


def test_missing_params_asks_instead_of_calculating():
    r = answer("Why is my tension off?")
    assert r.calc is None
    assert r.missing
    assert "tell me" in r.reply.lower()


def test_offline_rule_provider_explicit():
    r = answer("What needle size should I use for worsted yarn for a scarf?", provider=RuleProvider())
    assert not r.guard_rejected


@pytest.mark.demo
def test_guard_rejects_leaky_provider_and_falls_back_to_template():
    r = answer(
        "How much DK yarn do I need for a 50 x 60cm blanket in stockinette?",
        provider=LeakyProvider(),
    )
    assert r.guard_rejected
    assert r.phrase == "template"
    assert "45" not in r.reply
    assert str(r.calc.result["metres"]) in r.reply


def test_out_of_range_input_is_declined_with_reason():
    r = answer("How much DK yarn for a 99999 x 60cm blanket?")
    assert r.intent == "yarn_quantity"
    assert r.calc is None
    assert "can't be calculated" in r.reply


# --- regression cases --------------------------------------------------------


def test_tension_reply_gives_the_computed_direction_and_change():
    r = answer("My swatch is 24 stitches per 10cm but the pattern says 22. What's wrong?")
    assert not r.guard_rejected
    assert "up" in r.reply.lower()
    assert str(r.calc.result["suggested_needle_change_mm"]) in r.reply


def test_loose_tension_reply_says_go_down():
    r = answer("My swatch is 18 stitches per 10cm but the pattern says 22. What's wrong?")
    assert "down" in r.reply.lower()
    assert not r.guard_rejected


def test_yarn_reply_names_the_assumed_ball_put_up():
    r = answer("How much DK yarn do I need for a 50 x 60cm blanket in stockinette?")
    assert not r.guard_rejected
    assert f"{r.calc.inputs['ball_metres']:g}m" in r.reply
    assert f"{r.calc.inputs['ball_grams']:g}g" in r.reply
    assert any("ball" in a.lower() for a in r.calc.assumptions)


def test_negative_dimension_is_declined_not_answered():
    r = answer("How much DK yarn for a -50 x 60cm blanket?")
    assert r.calc is None
    assert "can't be calculated" in r.reply


def test_unitless_dimensions_are_answered_with_an_assumption():
    r = answer("How much DK yarn for a 50x60 blanket?")
    assert r.calc is not None
    assert any("centimetres" in a for a in r.calc.assumptions)


def test_guard_rejection_logs_the_draft_for_debugging(caplog):
    import logging

    with caplog.at_level(logging.DEBUG, logger="assistant"):
        r = answer(
            "How much DK yarn do I need for a 50 x 60cm blanket in stockinette?",
            provider=LeakyProvider(),
        )
    assert r.guard_rejected
    assert "823.456" in caplog.text          # the rejected draft itself, at DEBUG
    assert "question_sha256=" in caplog.text  # and a handle to find the question


class SlowProvider(RuleProvider):
    """Records the per-call deadline it is given."""

    name = "slow"
    kind = "llm"

    def __init__(self):
        self.timeouts = []

    def route(self, question, timeout_s=None):
        self.timeouts.append(timeout_s)
        return super().route(question)

    def phrase(self, question, intent_name, calc, timeout_s=None):
        self.timeouts.append(timeout_s)
        return super().phrase(question, intent_name, calc)


def test_each_provider_call_gets_the_remaining_budget():
    provider = SlowProvider()
    answer(
        "How much DK yarn do I need for a 50 x 60cm blanket in stockinette?",
        provider=provider,
        budget_s=8.0,
    )
    assert len(provider.timeouts) == 2
    assert all(t is not None and 0 < t <= 8.0 for t in provider.timeouts)
    assert provider.timeouts[1] <= provider.timeouts[0]
