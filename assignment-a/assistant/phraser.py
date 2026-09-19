"""The fixed-wording replies: the answer template, "please tell me ..." and "I can't answer".

Every number in a template reply is read straight out of the CalcResult, so these
replies always pass the guard. That makes the template the safe fallback whenever the
guard rejects an LLM reply, and the only reply the offline mode produces. The LLM's
own wording lives in providers.OpenAIProvider.phrase().

    template_reply("yarn_quantity", calc)
        -> "For a 50cm x 60cm piece in stockinette (light weight), you'll need about 429.0m ..."
    ask_reply(["weight"])
        -> "I need a bit more information: please tell me the yarn weight (e.g. DK, worsted, chunky)."
"""

from __future__ import annotations

from knitcalc.calculators import CalcResult
from knitcalc.domain import DOMAIN

# How each missing input is described when the assistant asks for it.
MISSING_INPUT_DESCRIPTIONS = {
    "stitch": "the stitch pattern (e.g. stockinette, garter, 1x1 rib)",
    "width_cm": "the width (in cm or inches)",
    "height_cm": "the height (in cm or inches)",
    "weight": "the yarn weight (e.g. DK, worsted, chunky)",
    "actual_sts_10cm": "your actual gauge (stitches per 10cm)",
    "target_sts_10cm": "the target/pattern gauge (stitches per 10cm)",
}


def template_reply(intent_name: str, calc: CalcResult) -> str:
    """The always-safe reply for a calculation: every number comes from `calc`."""
    reply_for = {
        "yarn_quantity": _yarn_quantity_reply,
        "needle_recommendation": _needle_recommendation_reply,
        "tension_diagnosis": _tension_diagnosis_reply,
    }
    return reply_for[intent_name](calc)


def ask_reply(missing: list[str]) -> str:
    """Ask the knitter for the inputs the question didn't give."""
    descriptions = [MISSING_INPUT_DESCRIPTIONS.get(name, name) for name in missing]
    return "I need a bit more information: please tell me " + "; ".join(descriptions) + "."


def decline_reply(reason: str) -> str:
    """Say the assistant can't answer, and why (reason starts lower-case mid-sentence)."""
    reason_mid_sentence = reason[:1].lower() + reason[1:]
    return f"I can't answer that -- {reason_mid_sentence}"


# --- One template per calculator ------------------------------------------------


def _yarn_quantity_reply(calc: CalcResult) -> str:
    inputs, result = calc.inputs, calc.result
    stitch_name = DOMAIN.stitch_by_alias(inputs["stitch"]).aliases[0]
    ball_word = "ball" if result["balls"] == 1 else "balls"
    return (
        f"For a {inputs['width_cm']:g}cm x {inputs['height_cm']:g}cm piece in {stitch_name} "
        f"({_weight_name(inputs['weight'])} weight), you'll need about {result['metres']}m of yarn "
        f"-- roughly {result['balls']} {ball_word} of {inputs['ball_grams']:g}g / {inputs['ball_metres']:g}m. "
        f"If your balls are a different length, tell me and I'll redo the count."
    )


def _needle_recommendation_reply(calc: CalcResult) -> str:
    inputs, result = calc.inputs, calc.result
    return (
        f"For {_weight_name(inputs['weight'])} weight yarn on a {inputs['project']} (fabric: {inputs['fabric']}), "
        f"try a {result['metric_mm']}mm needle -- {_us_and_uk_sizes(result)}. "
        f"This weight's typical range is {result['range_min_mm']}-{result['range_max_mm']}mm."
    )


def _tension_diagnosis_reply(calc: CalcResult) -> str:
    """Leads with the diagnosis, then the needle change the calculator worked out."""
    result = calc.result
    other_fixes = [
        fix.replace("_", " ") for fix in result["fixes"] if fix != "change_needle_size"
    ]
    if result["direction"] == "none":
        needle_advice = "No needle change needed"
    else:
        needle_advice = (
            f"Go {result['direction']} about {result['suggested_needle_change_mm']}mm in needle size"
        )
    return (
        f"Your gauge is {result['diagnosis']} ({result['severity']}, {abs(result['diff_pct'])}% off target). "
        f"{needle_advice}, then reswatch. Other things to try: {', '.join(other_fixes)}."
    )


def _us_and_uk_sizes(result: dict) -> str:
    """ "US 8, UK 6". Some metric sizes have no US or UK equivalent."""
    us_size = f"US {result['us']}" if result["us"] else "no US size"
    uk_size = f"UK {result['uk']}" if result["uk"] else "no UK size"
    return f"{us_size}, {uk_size}"


def _weight_name(weight_key: str) -> str:
    return DOMAIN.weight_by_alias(weight_key).name.lower()
