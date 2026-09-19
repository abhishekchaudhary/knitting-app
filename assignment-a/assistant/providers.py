"""Providers: who reads the question and who words the reply.

A provider does two jobs and never calculates:
    route(question)             -> Intent   (which calculator, which inputs)
    phrase(question, intent, calc) -> str   (a friendly reply built from the CalcResult)

RuleProvider   keyword router + fixed templates. No key, no network, never fails.
               Used offline and as the fallback whenever the LLM fails.
OpenAIProvider an OpenAI chat model. Its reading is checked by router.intent_from_llm()
               and its wording by guard.problems().

Adding a second vendor means one more class with the same two methods; assistant.py
doesn't change.
"""

from __future__ import annotations

import json
import logging
import os
import string
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

import yaml

from assistant import phraser, router
from assistant.router import Intent
from knitcalc.calculators import CalcResult
from knitcalc.domain import DOMAIN

PROMPTS_PATH = Path(__file__).parent / "prompts.yaml"


class ProviderError(RuntimeError):
    """A provider could not produce a usable answer; the caller falls back to rules."""


class LLMProvider(Protocol):
    name: str
    kind: str  # "llm" or "rules"

    def route(self, question: str, timeout_s: float | None = None) -> Intent: ...

    def phrase(
        self, question: str, intent_name: str, calc: CalcResult, timeout_s: float | None = None
    ) -> str: ...


def get_provider(offline: bool = False) -> LLMProvider:
    """--offline, LLM_PROVIDER=rules, or a missing key all mean RuleProvider (never a crash)."""
    if offline or (os.environ.get("LLM_PROVIDER") or "openai") == "rules":
        return RuleProvider()
    try:
        return OpenAIProvider()
    except ProviderError as exc:
        logging.getLogger("assistant").info("ASSISTANT provider=rules reason=%r", str(exc))
        return RuleProvider()


class RuleProvider:
    """Offline / fallback provider: keyword router + templates. No key, no network, never fails."""

    name = "rules"
    kind = "rules"

    def route(self, question: str, timeout_s: float | None = None) -> Intent:
        return router.route(question)

    def phrase(
        self, question: str, intent_name: str, calc: CalcResult, timeout_s: float | None = None
    ) -> str:
        return phraser.template_reply(intent_name, calc)


def _nullable(schema: dict[str, Any]) -> dict[str, Any]:
    """The same schema, but null is also allowed (the LLM returns null for "not stated")."""
    if "enum" in schema:
        return {"type": ["string", "null"], "enum": [*schema["enum"], None]}
    return {"type": [schema["type"], "null"]}


def router_schema() -> dict[str, Any]:
    """The JSON the LLM must return when it reads a question. Allowed names come from domain.yaml."""
    number = {"type": "number"}
    unit = {"enum": ["cm", "in"]}
    fields: dict[str, Any] = {
        "intent": {"type": "string", "enum": list(router.INTENTS)},
        "decline_category": _nullable({"enum": list(router.DECLINE_CATEGORIES)}),
        "width": _nullable(number),
        "width_unit": _nullable(unit),
        "height": _nullable(number),
        "height_unit": _nullable(unit),
        "weight": _nullable({"enum": [weight.key for weight in DOMAIN.weights]}),
        "stitch": _nullable({"enum": [stitch.key for stitch in DOMAIN.stitches.items]}),
        "gauge_sts_10cm": _nullable(number),
        "project": _nullable({"enum": [project.key for project in DOMAIN.needle_recommender.projects]}),
        "fabric": _nullable({"enum": list(router.FABRIC_TOKENS)}),
        "actual_sts_10cm": _nullable(number),
        "target_sts_10cm": _nullable(number),
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": list(fields),
        "properties": fields,
    }


def render(template: str, **values: str) -> str:
    """Fill $placeholders in an operator-edited prompt.

    safe_substitute, not str.format: a literal brace or an unknown $word in
    prompts.yaml must not raise, because the provider boundary would swallow the
    error and silently turn the LLM off. An unfilled placeholder is logged loudly
    instead, and the prompt still goes out.
    """
    filled = string.Template(template).safe_substitute(values)
    for name in values:
        if f"${name}" in filled or f"${{{name}}}" in filled:
            logging.getLogger("assistant").error(
                "ASSISTANT prompt=UNSUBSTITUTED placeholder=%s (check prompts.yaml)", name
            )
    return filled


@lru_cache(maxsize=1)
def _prompts() -> dict[str, str]:
    """prompts.yaml, with the domain vocabulary filled into the router prompt. Read once."""
    prompts = yaml.safe_load(PROMPTS_PATH.read_text(encoding="utf-8"))
    prompts["router_system"] = render(
        prompts["router_system"],
        weights=_vocabulary(DOMAIN.weights),
        stitches=_vocabulary(DOMAIN.stitches.items),
        projects=_vocabulary(DOMAIN.needle_recommender.projects),
    )
    return prompts


def _vocabulary(items: list[Any]) -> str:
    """One line per item: "    light [dk, double knit, ...]"."""
    lines = [f"    {item.key} [{', '.join(item.aliases)}]" for item in items]
    return "\n".join(lines)


class OpenAIProvider:
    """OpenAI chat model for routing (structured output) and phrasing.

    Config via env: OPENAI_API_KEY, OPENAI_MODEL, OPENAI_REASONING_EFFORT, OPENAI_TIMEOUT_S.
    Pass `client` to inject a fake in tests.
    """

    name = "openai"
    kind = "llm"

    def __init__(self, client: Any | None = None, model: str | None = None) -> None:
        self.model = model or os.environ.get("OPENAI_MODEL") or "gpt-5.4-mini"
        self.reasoning_effort = os.environ.get("OPENAI_REASONING_EFFORT") or "none"
        if client is None:
            if not os.environ.get("OPENAI_API_KEY"):
                raise ProviderError("OPENAI_API_KEY is not set")
            from openai import OpenAI

            # max_retries=0: falling back to the rules is the retry, and it is instant.
            client = OpenAI(timeout=float(os.environ.get("OPENAI_TIMEOUT_S") or 20), max_retries=0)
        self._client = client
        self.calls = 0

    def route(self, question: str, timeout_s: float | None = None) -> Intent:
        """Ask the LLM to read the question into router_schema() JSON, then check that reading."""
        json_only = {
            "type": "json_schema",
            "json_schema": {"name": "intent", "strict": True, "schema": router_schema()},
        }
        reply_text = self._chat(
            _prompts()["router_system"], question, json_only, timeout_s=timeout_s
        )
        try:
            payload = json.loads(reply_text)
        except json.JSONDecodeError as exc:
            raise ProviderError("router returned invalid JSON") from exc
        intent = router.intent_from_llm(question, payload)
        if intent is None:
            raise ProviderError(f"router output failed validation: {payload}")
        return intent

    def phrase(
        self, question: str, intent_name: str, calc: CalcResult, timeout_s: float | None = None
    ) -> str:
        """Ask the LLM to word a reply from the CalcResult. The guard checks it afterwards."""
        calculation = asdict(calc)
        del calculation["source"]  # the source citation is shown by the CLI, not in the reply
        data = {"intent": intent_name, **calculation}
        prompts = _prompts()
        system = render(prompts["phraser_system"], headline=prompts["phraser_headline"][intent_name])
        user = f"Question: {question}\nCalculation JSON: {json.dumps(data)}"
        return self._chat(system, user, timeout_s=timeout_s).strip()

    def _chat(
        self,
        system: str,
        user: str,
        response_format: dict[str, Any] | None = None,
        timeout_s: float | None = None,
    ) -> str:
        """One chat completion. Any SDK failure (timeout, auth, rate limit) becomes ProviderError."""
        self.calls += 1
        kwargs: dict[str, Any] = {}
        if response_format:
            kwargs["response_format"] = response_format
        if timeout_s is not None:
            kwargs["timeout"] = timeout_s  # per-request deadline, not the client default
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                reasoning_effort=self.reasoning_effort,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                **kwargs,
            )
        except Exception as exc:  # SDK boundary: timeout, auth, rate limit, network
            raise ProviderError(f"{type(exc).__name__}: {exc}") from exc
        content = response.choices[0].message.content
        if not content:
            raise ProviderError("empty completion")
        return content
