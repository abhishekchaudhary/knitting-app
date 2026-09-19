"""Ask the knitting assistant a question.

    python cli.py "question" [--offline] [--json] [--quiet]

Without --offline the OpenAI provider is used when OPENAI_API_KEY is set;
otherwise (or on any provider failure) the rule router + templates answer.

Exit status, so a script can tell the three outcomes apart:
    0  answered   (a calculation was made and phrased)
    2  asked      (an input was missing; the reply asks for it)
    3  declined   (out of scope, or the inputs cannot be calculated)
    1  usage/runtime error (argparse or an unhandled exception)

Example:
    python cli.py --offline "How much DK yarn for a 50 x 60cm blanket?"  -> reply, exit 0
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import sys

from dotenv import find_dotenv, load_dotenv

from assistant.assistant import answer
from assistant.providers import get_provider

# Exit codes (1 is left to argparse and unhandled errors).
EXIT_ANSWERED = 0
EXIT_ASKED = 2
EXIT_DECLINED = 3

USAGE_EPILOG = """exit status: 0 answered, 2 asked for a missing input, 3 declined, 1 usage error.

a question that starts with a dash goes after --, e.g.:
  python cli.py --offline -- "-50 x 60cm blanket in DK: how much yarn?"
"""


def main() -> int:
    """Parse the flags, answer the question, print it, and return the exit code."""
    args = _build_parser().parse_args()

    load_dotenv(find_dotenv(usecwd=True))
    _configure_logging(quiet=args.quiet)

    provider = get_provider(offline=args.offline)
    result = answer(args.question, provider=provider)

    if args.json:
        print(_as_json(result))
    else:
        print(result.reply)
        if not args.quiet:
            print(_how_calculated(result))
    return _exit_code(result)


# --- Helpers, in the order main() calls them ----------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Ask the knitting assistant a question.",
        epilog=USAGE_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("question", help="the question, in quotes")
    parser.add_argument("--offline", action="store_true", help="rule router + templates only (no key, no network)")
    parser.add_argument("--json", action="store_true", help="print the full AnswerResult as JSON")
    parser.add_argument("--quiet", action="store_true", help="reply only, no trace block or log lines")
    return parser


def _configure_logging(quiet: bool) -> None:
    """Log lines (route, fallback, guard) show by default; --quiet hides them."""
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    logging.getLogger("assistant").setLevel(logging.WARNING if quiet else logging.INFO)


def _as_json(result) -> str:
    """The full AnswerResult as indented JSON, plus the exit code."""
    payload = dataclasses.asdict(result)
    # `draft` is the provider's text *before* the guard; name it so nothing downstream
    # mistakes it for the reply that was actually verified.
    payload["draft_unverified"] = payload.pop("draft")
    payload["exit_code"] = _exit_code(result)
    return json.dumps(payload, indent=2, default=str)


def _how_calculated(result) -> str:
    """The "how this was calculated" block printed under the reply."""
    lines = ["", "-- how this was calculated --"]
    if result.calc:
        lines.append(f"formula:     {result.calc.formula}")
        lines.append(f"inputs:      {json.dumps(result.calc.inputs)}")
        for assumption in result.calc.assumptions:
            lines.append(f"assumption:  {assumption}")
        lines.append(f"source:      {result.calc.source}")
    lines.append(_trace_line(result))
    return "\n".join(lines)


def _trace_line(result) -> str:
    """One line saying which path produced the answer: rules or LLM, and the guard verdict."""
    if result.guard_rejected:
        guard = "REJECTED -> template"
    elif result.calc:
        guard = "pass"
    else:
        guard = "n/a"
    gauge = "stated" if "gauge_sts_10cm" in result.params else "default"
    return (
        f"trace:       intent={result.intent} route={result.route} phrase={result.phrase} "
        f"gauge={gauge} guard={guard} {result.elapsed_ms:.0f}ms"
    )


def _exit_code(result) -> int:
    """0 answered, 2 asked for a missing input, 3 declined."""
    if result.intent == "unsupported" or (result.calc is None and result.decline_reason):
        return EXIT_DECLINED
    if result.missing:
        return EXIT_ASKED
    return EXIT_ANSWERED


if __name__ == "__main__":
    sys.exit(main())
