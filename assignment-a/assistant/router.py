"""Turn a question into an Intent: which calculator to run, and with which inputs.

There are two routers with the same output type:

  route(question)
      Rules only: keywords and patterns, no LLM, no network, never raises. This is the
      offline mode, and the fallback whenever the LLM fails.

  intent_from_llm(question, payload)
      Checks what the LLM read from the question (see providers.router_schema) against
      the question itself. Returns None when the reading can't be trusted, and the
      caller then uses route().

Neither router calculates anything. They only pick a calculator and read the inputs the
knitter wrote. An input that isn't there goes into Intent.missing, so the assistant asks
for it. A question it can't answer becomes an "unsupported" Intent with a fixed reason.

    route("How much DK yarn for a 50 x 60cm blanket in stockinette?")
        -> Intent(name="yarn_quantity",
                  params={"width_cm": 50.0, "height_cm": 60.0, "weight": "light",
                          "stitch": "stockinette"})

ASSUMPTION: route() is a keyword cascade, not language understanding. It is tuned
against evals/questions.jsonl. When a real question is misread, the fix is a new
pattern in question_reader.py, never a special case in the calculators.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from assistant import question_reader as reader
from assistant.declines import (  # noqa: F401  (re-exported: providers and tests use them here)
    DECLINE_CATEGORIES,
    DECLINES,
    FALLBACK_DECLINE_REASON,
    ROW_GAUGE_DECLINE_REASON,
    SPECIFIC_DECLINE_REASONS,
    matching_declines,
    mentions_row_gauge,
    reason_for_category,
)
from assistant.question_reader import (  # noqa: F401  (re-exported)
    AMBIGUOUS_WEIGHT_ALIASES,
    FABRIC_TOKENS,
    UNITLESS_DIMENSION_ASSUMPTION,
)
from knitcalc.domain import DOMAIN

logger = logging.getLogger("assistant")

INTENTS = ("yarn_quantity", "needle_recommendation", "tension_diagnosis", "unsupported")


@dataclass(frozen=True)
class Intent:
    """What the router decided.

    name: a calculator name, or "unsupported".
    params: inputs ready for knitcalc.calculators.<name>(**params) once `missing` is empty.
    missing: inputs the question didn't give; the assistant asks for these.
    decline_reason: set only when name == "unsupported".
    assumptions: how the router read the question (e.g. "read the dimensions as cm");
        shown to the knitter alongside the calculator's own assumptions.
    """

    name: str
    params: dict[str, Any] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    decline_reason: str | None = None
    assumptions: list[str] = field(default_factory=list)


# --- Words that pick the calculator --------------------------------------------

TENSION_WORD = re.compile(r"\btension\b", re.IGNORECASE)
# Without the word "tension", a question is still about tension when it compares the
# knitter's count with the pattern's ("getting 20 ... pattern says 18").
TENSION_CONTEXT_WORD = re.compile(r"\b(pattern|swatch|gauge|getting)\b", re.IGNORECASE)
NEEDLE_WORD = re.compile(r"\bneedles?\b", re.IGNORECASE)
YARN_WORD = re.compile(
    r"\byarn\b|\bballs?\b|\bskeins?\b|\bmetres?\b|\bmeters?\b|\bhow much\b", re.IGNORECASE
)


# =============================================================================
# The rule router
# =============================================================================


def route(question: str) -> Intent:
    """Rules only. Declines first, then: tension -> needles -> yarn -> general decline."""
    text = question.strip()

    decline_reason = _decline_reason(text)
    if decline_reason:
        return Intent(name="unsupported", decline_reason=decline_reason)

    return _calculator_intent(text)


def _decline_reason(text: str) -> str | None:
    """The reason of the first decline category that applies, or None.

    A technique word is ignored when the question is really a calculation that mentions
    it in passing ("a 50 x 60cm blanket after blocking"). A real technique question
    ("Which cast-on for 4ply?") has nothing for the calculators to use, so it declines.
    """
    for category, reason in matching_declines(text):
        if category == "technique" and _is_complete_calculation(text):
            continue
        return reason
    return None


def _is_complete_calculation(text: str) -> bool:
    intent = _calculator_intent(text)
    return intent.name != "unsupported" and not intent.missing


def _calculator_intent(text: str) -> Intent:
    """Pick the calculator from the question's words, then read its inputs."""
    if mentions_row_gauge(text):
        return Intent(name="unsupported", decline_reason=ROW_GAUGE_DECLINE_REASON)
    if _is_tension_question(text):
        return _tension_intent(text)
    if NEEDLE_WORD.search(text):
        return _needle_intent(text)
    if YARN_WORD.search(text):
        return _yarn_intent(text)
    return Intent(name="unsupported", decline_reason=FALLBACK_DECLINE_REASON)


def _is_tension_question(text: str) -> bool:
    if TENSION_WORD.search(text):
        return True
    return bool(TENSION_CONTEXT_WORD.search(text)) and reader.read_tension_pair(text) is not None


def _tension_intent(text: str) -> Intent:
    counts = reader.read_tension_pair(text)
    if counts is None:
        return Intent(
            name="tension_diagnosis", missing=["actual_sts_10cm", "target_sts_10cm"]
        )
    actual, target = counts
    return Intent(
        name="tension_diagnosis",
        params={"actual_sts_10cm": actual, "target_sts_10cm": target},
    )


def _needle_intent(text: str) -> Intent:
    params: dict[str, Any] = {}
    missing: list[str] = []

    weight_key, _alias = reader.read_weight(text)
    if weight_key:
        params["weight"] = weight_key
    else:
        missing.append("weight")

    project_key = reader.read_project(text)
    if project_key:
        params["project"] = project_key

    fabric = reader.read_fabric(text)
    if fabric:
        params["fabric"] = fabric

    return Intent(name="needle_recommendation", params=params, missing=missing)


def _yarn_intent(text: str) -> Intent:
    params: dict[str, Any] = {}
    missing: list[str] = []
    assumptions: list[str] = []

    size_cm, assumed_cm = reader.read_dimensions(text)
    if size_cm:
        params["width_cm"], params["height_cm"] = size_cm
        if assumed_cm:
            assumptions.append(UNITLESS_DIMENSION_ASSUMPTION)
    else:
        missing += ["width_cm", "height_cm"]

    weight_key, weight_alias = reader.read_weight(text)
    if weight_key:
        params["weight"] = weight_key
    else:
        missing.append("weight")

    stitch_key, unknown_stitch_named = reader.read_stitch(text, weight_alias=weight_alias)
    if stitch_key:
        params["stitch"] = stitch_key
    elif unknown_stitch_named:
        missing.append("stitch")

    gauge = reader.read_gauge(text)
    if gauge is not None:
        params["gauge_sts_10cm"] = gauge

    return Intent(name="yarn_quantity", params=params, missing=missing, assumptions=assumptions)


# =============================================================================
# Checking the LLM's reading
# =============================================================================


def intent_from_llm(question: str, payload: dict[str, Any]) -> Intent | None:
    """Turn the LLM's reading of the question into an Intent, or None if it can't be trusted.

    The LLM may read inputs but never invent them:
    - every number it returns must be written in the question;
    - a weight, stitch, project or fabric must be named in the question; otherwise it is
      dropped, and a missing weight is asked for instead of guessed;
    - units come from the question text when it states one; conversion happens here;
    - where the rule router also read a value, both readings must agree.
    A malformed payload (wrong types, unknown names) also returns None.
    """
    try:
        return _check_llm_reading(question, payload)
    except (TypeError, ValueError, AttributeError, KeyError):
        return None


def _check_llm_reading(question: str, payload: dict[str, Any]) -> Intent | None:
    intent_name = payload.get("intent")
    if intent_name not in INTENTS:
        return None

    rules_intent = route(question)

    if intent_name == "unsupported":
        return _check_llm_decline(payload, rules_intent)

    if not _llm_numbers_are_in_question(question, payload):
        return None

    names = _llm_names_found_in_question(question, payload)
    if names is None:
        return None

    params, missing = _llm_params(intent_name, question, payload, names)
    if params is None:
        return None

    if rules_intent.name == intent_name and _disagrees_with_rules(params, rules_intent):
        return None

    return _keep_what_rules_found(intent_name, params, missing, rules_intent)


def _check_llm_decline(payload: dict[str, Any], rules_intent: Intent) -> Intent:
    """The LLM says "can't answer". Decide which decline (or answer) to give."""
    if _is_specific_decline(rules_intent):
        # Both decline, but the rules know the exact cause (row gauge, crochet, ...).
        return rules_intent

    if rules_intent.name != "unsupported" and not rules_intent.missing:
        # The rules can answer this completely, so the LLM's decline is a mistake.
        # Declining a question we can answer is the costly error, so the rules win.
        logger.info(
            "ASSISTANT ROUTE_DISAGREE llm=unsupported rules=%s -> using rules", rules_intent.name
        )
        return rules_intent

    reason = reason_for_category(payload.get("decline_category"))
    return Intent(name="unsupported", decline_reason=reason)


def _llm_numbers_are_in_question(question: str, payload: dict[str, Any]) -> bool:
    """Every number the LLM read must be written in the question."""
    written_numbers = reader.numbers_in(question)
    for field_name in ("width", "height", "gauge_sts_10cm", "actual_sts_10cm", "target_sts_10cm"):
        value = payload.get(field_name)
        if value is not None and float(value) not in written_numbers:
            return False
    return True


def _llm_names_found_in_question(
    question: str, payload: dict[str, Any]
) -> dict[str, str | None] | None:
    """The weight, stitch, project and fabric the LLM read, each kept only when the
    question names it. None when the fabric isn't one of the known fabric words."""
    weight_key = _named_in_question(question, payload.get("weight"), DOMAIN.weight_by_alias)
    if weight_key and not reader.weight_is_really_stated(question, weight_key):
        # "baby blanket" contains "baby", but that isn't a yarn weight: ask instead.
        logger.info(
            "ASSISTANT ROUTE_DISAGREE llm=weight=%s support=ambiguous_alias_only -> asking",
            weight_key,
        )
        weight_key = None

    stitch_key = _named_in_question(question, payload.get("stitch"), DOMAIN.stitch_by_alias)
    project_key = _named_in_question(question, payload.get("project"), DOMAIN.project_by_alias)

    fabric = payload.get("fabric")
    if fabric is not None:
        if fabric not in FABRIC_TOKENS:
            return None
        if not reader.mentions_any(question, [fabric]):
            fabric = None

    return {"weight": weight_key, "stitch": stitch_key, "project": project_key, "fabric": fabric}


def _named_in_question(question: str, llm_value: str | None, lookup) -> str | None:
    """The domain key for `llm_value`, if the question names it by any of its aliases.

    `lookup` raises ValueError for a name domain.yaml doesn't know; intent_from_llm
    turns that into "don't trust this reading".
    """
    if not llm_value:
        return None
    item = lookup(llm_value)
    words_for_item = [*item.aliases, item.key.replace("_", " ")]
    if reader.mentions_any(question, words_for_item):
        return item.key
    return None


def _llm_params(
    intent_name: str, question: str, payload: dict[str, Any], names: dict[str, str | None]
) -> tuple[dict[str, Any] | None, list[str]]:
    """Calculator inputs from the LLM's reading, plus the ones still missing.

    Returns (None, []) when a gauge the LLM read isn't written as a stitch count.
    """
    if intent_name == "tension_diagnosis":
        return _llm_tension_params(payload)

    params: dict[str, Any] = {}
    missing: list[str] = []
    if intent_name == "yarn_quantity":
        _add_llm_dimensions(question, payload, params, missing)

    if names["weight"]:
        params["weight"] = names["weight"]
    else:
        missing.append("weight")

    if intent_name == "needle_recommendation":
        if names["project"]:
            params["project"] = names["project"]
        if names["fabric"]:
            params["fabric"] = names["fabric"]
        return params, missing

    # yarn_quantity
    if names["stitch"]:
        params["stitch"] = names["stitch"]
    if payload.get("gauge_sts_10cm") is not None:
        gauge = float(payload["gauge_sts_10cm"])
        if not reader.is_stitch_count(question, gauge):
            return None, []
        params["gauge_sts_10cm"] = gauge
    return params, missing


def _llm_tension_params(payload: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    params: dict[str, Any] = {}
    missing: list[str] = []
    for field_name in ("actual_sts_10cm", "target_sts_10cm"):
        if payload.get(field_name) is None:
            missing.append(field_name)
        else:
            params[field_name] = float(payload[field_name])
    return params, missing


def _add_llm_dimensions(
    question: str, payload: dict[str, Any], params: dict[str, Any], missing: list[str]
) -> None:
    """Width and height in cm. The unit written in the question beats the unit the LLM reported."""
    for llm_field, param_name in (("width", "width_cm"), ("height", "height_cm")):
        if payload.get(llm_field) is None:
            missing.append(param_name)
            continue
        value = float(payload[llm_field])
        unit = reader.read_unit_after(question, value) or payload.get(f"{llm_field}_unit")
        params[param_name] = round(reader.to_cm(value, unit), 2)


def _disagrees_with_rules(llm_params: dict[str, Any], rules_intent: Intent) -> bool:
    """True when the rules read a value and the LLM read a different one for it."""
    for param_name, rules_value in rules_intent.params.items():
        if llm_params.get(param_name) != rules_value:
            return True
    return False


def _is_specific_decline(intent: Intent) -> bool:
    """A decline that names a cause, as opposed to the general "not one of my three"."""
    return intent.name == "unsupported" and intent.decline_reason in SPECIFIC_DECLINE_REASONS


def _keep_what_rules_found(
    intent_name: str, params: dict[str, Any], missing: list[str], rules_intent: Intent
) -> Intent:
    """The LLM's values win, but something the rules noticed and the LLM dropped is kept.

    The LLM can read phrasings the rules can't, so its values are used. But if the rules
    found a named decline, or an input they know is missing (an unknown stitch, an
    unstated weight), dropping that would answer the wrong question without asking.
    """
    if _is_specific_decline(rules_intent):
        logger.info(
            "ASSISTANT ROUTE_DISAGREE llm=%s rules=unsupported reason=%r -> using rules",
            intent_name,
            rules_intent.decline_reason,
        )
        return rules_intent

    if rules_intent.name == intent_name:
        also_missing = [
            field_name
            for field_name in rules_intent.missing
            if field_name not in params and field_name not in missing
        ]
        if also_missing:
            logger.info(
                "ASSISTANT ROUTE_DISAGREE llm=%s missing+=%s (rules found them) -> asking",
                intent_name,
                also_missing,
            )
            missing = [*missing, *also_missing]

    return Intent(name=intent_name, params=params, missing=missing)
