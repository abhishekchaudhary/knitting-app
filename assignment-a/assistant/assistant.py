"""answer(question): the whole assistant in one function call.

    question -> route (LLM or rules) -> calculator -> phrase (LLM or template) -> guard -> reply

The provider (LLM or rules) only reads the question and words the reply. The numbers
always come from knitcalc.calculators. If the LLM fails at either step, that step
falls back to the rules or the template, and guard.problems() checks every worded
reply before it reaches the knitter. The whole question has one time budget, so a hung
provider costs seconds, not minutes. Diagram: README.md, Architecture.

    answer("What needle size for worsted yarn for a scarf?").reply
        -> "For medium weight yarn on a scarf (fabric: balanced), try a 5.0mm needle -- US 8, UK 6. ..."
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

from assistant import guard, phraser
from assistant.providers import LLMProvider, RuleProvider
from assistant.router import Intent
from knitcalc.calculators import (
    CalcResult,
    needle_recommendation,
    tension_diagnosis,
    yarn_quantity,
)

logger = logging.getLogger("assistant")

CALCULATORS = {
    "yarn_quantity": yarn_quantity,
    "needle_recommendation": needle_recommendation,
    "tension_diagnosis": tension_diagnosis,
}
RULES = RuleProvider()

# A hung provider must not keep the knitter waiting. The rules are the fallback, so the
# whole question gets one budget and each provider call gets whatever is left of it.
DEFAULT_BUDGET_S = float(os.environ.get("ASSISTANT_BUDGET_S") or 8.0)
MIN_CALL_S = 0.5


@dataclass(frozen=True)
class AnswerResult:
    """Everything about one answer: the reply, plus how it was produced (for logs and the eval)."""

    reply: str
    intent: str
    calc: CalcResult | None
    params: dict[str, Any] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    decline_reason: str | None = None
    route: str = "rules"  # who read the question: "llm" | "rules"
    phrase: str = "none"  # who wrote the reply: "llm" | "template" | "none" (ask/decline)
    draft: str | None = None  # the provider's reply before the guard, for the eval
    guard_rejected: bool = False
    elapsed_ms: float = 0.0


def answer(
    question: str,
    provider: LLMProvider | None = None,
    budget_s: float = DEFAULT_BUDGET_S,
) -> AnswerResult:
    """Answer the question. Provider calls share `budget_s` seconds; local work is not timed out."""
    budget = _TimeBudget(budget_s)
    provider = provider or RULES

    intent, route_by = _route(question, provider, budget)

    if intent.name == "unsupported":
        return _decline(intent, route_by, budget)
    if intent.missing:
        return _ask_for_missing_inputs(intent, route_by, budget)

    try:
        calc = _calculate(intent)
    except ValueError as exc:
        return _decline_bad_inputs(intent, route_by, exc, budget)

    return _phrase_and_guard(question, provider, intent, calc, route_by, budget)


# --- Steps of answer(), in order ---------------------------------------------


def _route(question: str, provider: LLMProvider, budget: _TimeBudget) -> tuple[Intent, str]:
    """Ask the provider which calculator to use. If it fails, the rules decide."""
    try:
        return provider.route(question, timeout_s=budget.remaining_s()), provider.kind
    except Exception as exc:  # any provider failure means the rules take over
        logger.info("ASSISTANT route=rules fallback reason=%r", str(exc)[:120])
        return RULES.route(question), "rules"


def _decline(intent: Intent, route_by: str, budget: _TimeBudget) -> AnswerResult:
    logger.info("ASSISTANT intent=unsupported route=%s", route_by)
    return AnswerResult(
        reply=phraser.decline_reply(intent.decline_reason or ""),
        intent="unsupported",
        calc=None,
        decline_reason=intent.decline_reason,
        route=route_by,
        elapsed_ms=budget.elapsed_ms(),
    )


def _ask_for_missing_inputs(intent: Intent, route_by: str, budget: _TimeBudget) -> AnswerResult:
    logger.info("ASSISTANT intent=%s route=%s missing=%s", intent.name, route_by, intent.missing)
    return AnswerResult(
        reply=phraser.ask_reply(intent.missing),
        intent=intent.name,
        calc=None,
        params=intent.params,
        missing=intent.missing,
        route=route_by,
        elapsed_ms=budget.elapsed_ms(),
    )


def _calculate(intent: Intent) -> CalcResult:
    """Run the calculator. Raises ValueError for inputs it can't use (e.g. a negative width)."""
    calc = CALCULATORS[intent.name](**intent.params)
    calc.assumptions.extend(intent.assumptions)  # e.g. "read the dimensions as cm"
    return calc


def _decline_bad_inputs(
    intent: Intent, route_by: str, error: ValueError, budget: _TimeBudget
) -> AnswerResult:
    reason = f"those inputs can't be calculated ({error})."
    logger.info("ASSISTANT intent=%s route=%s calc_error=%r", intent.name, route_by, str(error))
    return AnswerResult(
        reply=phraser.decline_reply(reason),
        intent=intent.name,
        calc=None,
        params=intent.params,
        decline_reason=reason,
        route=route_by,
        elapsed_ms=budget.elapsed_ms(),
    )


def _phrase_and_guard(
    question: str,
    provider: LLMProvider,
    intent: Intent,
    calc: CalcResult,
    route_by: str,
    budget: _TimeBudget,
) -> AnswerResult:
    """Word the reply, then check it. A reply that fails the guard is replaced by the template."""
    draft, phrase_by = _draft_reply(question, provider, intent, calc, route_by, budget)

    rejected_because = guard.problems(draft, calc)
    if rejected_because:
        reply, phrase_by = phraser.template_reply(intent.name, calc), "template"
    else:
        reply = draft

    _log_answer(question, intent, route_by, phrase_by, rejected_because, draft)
    return AnswerResult(
        reply=reply,
        intent=intent.name,
        calc=calc,
        params=intent.params,
        route=route_by,
        phrase=phrase_by,
        draft=draft,
        guard_rejected=bool(rejected_because),
        elapsed_ms=budget.elapsed_ms(),
    )


def _draft_reply(
    question: str,
    provider: LLMProvider,
    intent: Intent,
    calc: CalcResult,
    route_by: str,
    budget: _TimeBudget,
) -> tuple[str, str]:
    """(draft reply, who wrote it). The LLM words it only if the LLM also read the question."""
    if route_by != "llm":  # rules provider, or the LLM already failed on this question
        return phraser.template_reply(intent.name, calc), "template"
    try:
        return provider.phrase(question, intent.name, calc, timeout_s=budget.remaining_s()), "llm"
    except Exception as exc:  # any provider failure means the template is used
        logger.info("ASSISTANT phrase=template fallback reason=%r", str(exc)[:120])
        return phraser.template_reply(intent.name, calc), "template"


def _log_answer(
    question: str,
    intent: Intent,
    route_by: str,
    phrase_by: str,
    rejected_because: list[str],
    draft: str,
) -> None:
    # gauge=stated: the knitter's own gauge was read from the question.
    # gauge=default: the weight's typical gauge was used (an assumption line says so).
    gauge = "stated" if "gauge_sts_10cm" in intent.params else "default"
    guard_outcome = f"REJECTED leaked={rejected_because}" if rejected_because else "pass"
    logger.info(
        "ASSISTANT intent=%s route=%s phrase=%s gauge=%s guard=%s question_sha256=%s",
        intent.name,
        route_by,
        phrase_by,
        gauge,
        guard_outcome,
        _question_id(question),
    )
    if rejected_because:
        # The rejected draft never reaches the knitter, so this debug line is the only
        # place to find it. Match it to the info line above by question_sha256.
        logger.debug(
            "ASSISTANT guard=REJECTED question_sha256=%s draft=%r", _question_id(question), draft
        )


# --- Small helpers -------------------------------------------------------------


class _TimeBudget:
    """Wall-clock budget for one question."""

    def __init__(self, budget_s: float) -> None:
        self._budget_s = budget_s
        self._start = time.perf_counter()

    def elapsed_ms(self) -> float:
        return round((time.perf_counter() - self._start) * 1000, 1)

    def remaining_s(self) -> float:
        """Seconds left for the next provider call, never less than MIN_CALL_S."""
        used_s = time.perf_counter() - self._start
        return max(self._budget_s - used_s, MIN_CALL_S)


def _question_id(question: str) -> str:
    """Short hash of the question: links a log line to an eval row without logging the text."""
    return hashlib.sha256(question.encode("utf-8")).hexdigest()[:16]
