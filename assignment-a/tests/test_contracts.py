"""CalcResult contract: every calculator returns the same shape, and values()
exposes every number the guard is allowed to let through."""

from __future__ import annotations

from knitcalc.calculators import (
    CalcResult,
    needle_recommendation,
    tension_diagnosis,
    yarn_quantity,
)


def _assert_contract(r: CalcResult):
    assert isinstance(r, CalcResult)
    assert isinstance(r.result, dict) and r.result
    assert isinstance(r.formula, str) and r.formula
    assert isinstance(r.inputs, dict) and r.inputs
    assert isinstance(r.assumptions, list)
    assert isinstance(r.source, str) and r.source
    values = r.values()
    assert isinstance(values, list)
    assert all(isinstance(v, float) for v in values)
    assert len(values) > 0


def test_yarn_quantity_contract():
    _assert_contract(yarn_quantity(50, 60, "dk", "stockinette"))


def test_needle_recommendation_contract():
    _assert_contract(needle_recommendation("worsted"))


def test_tension_diagnosis_contract():
    _assert_contract(tension_diagnosis(24, 22))


def test_values_includes_result_numbers():
    r = yarn_quantity(50, 60, "dk", "stockinette")
    assert r.result["metres"] in r.values()
    assert float(r.result["balls"]) in r.values()


def test_safety_margin_text_and_input_agree():
    """One rounding only: the assumption line and inputs must not disagree (the guard sees both)."""
    r = yarn_quantity(50, 60, "dk")
    pct = r.inputs["safety_margin_pct"]
    assert any(f"{pct}% safety margin" in a for a in r.assumptions)


def test_yarn_result_names_the_assumed_ball():
    r = yarn_quantity(50, 60, "dk")
    assert any("ball" in a.lower() for a in r.assumptions)
    assert r.inputs["ball_metres"] > 0 and r.inputs["ball_grams"] > 0


def test_tension_result_carries_the_direction():
    assert tension_diagnosis(24, 22).result["direction"] == "up"
    assert tension_diagnosis(18, 22).result["direction"] == "down"
    assert tension_diagnosis(22, 22).result["direction"] == "none"


def test_prompt_placeholders_survive_a_literal_brace():
    """prompts.yaml is operator-edited: a stray brace must not disable the LLM silently."""
    from assistant.providers import render

    out = render("use {this} literally and $weights here", weights="DK")
    assert out == "use {this} literally and DK here"


def test_prompt_unknown_placeholder_is_left_alone_not_raised():
    from assistant.providers import render

    assert render("$unknown stays", weights="DK") == "$unknown stays"
