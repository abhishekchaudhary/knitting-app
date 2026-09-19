"""Evaluate the assistant against question sets and write a report.

    python assignment-a/evals/run_eval.py --offline                        # tuned + held-out, side by side
    python assignment-a/evals/run_eval.py --offline --questions questions  # tuned set only (diagnostic)
    python assignment-a/evals/run_eval.py --provider openai                # real LLM

For every question it checks: the right calculator was picked, the inputs were read
correctly, every number in the reply matches the calculator (before and after the
guard), declines and "please tell me ..." replies happen when expected, and how long
it took.

Question sets live beside this file as <name>.jsonl:
- `questions` (tuned): the set the rule router was built against. Its score measures
  fit, not generalisation. This is the only set with pass/fail thresholds.
- `held_out`: written afterwards, never tuned on. Reported, never gated.

Expected numbers are never typed by hand: each one is recomputed by calling the
calculator with the question's expected_params. The exception is `expected_values`
(the brief's worked examples), which are pinned on purpose.

Writes evals/results/eval_results_<mode>.json and eval_report_<mode>.md. Running only
some of the sets adds their names as a suffix, so a diagnostic run never overwrites
the committed results.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from dotenv import find_dotenv, load_dotenv  # noqa: E402

from assistant import guard  # noqa: E402
from assistant.assistant import AnswerResult, answer  # noqa: E402
from assistant.providers import OpenAIProvider, ProviderError, RuleProvider  # noqa: E402
from knitcalc.calculators import (  # noqa: E402
    CalcResult,
    needle_recommendation,
    tension_diagnosis,
    yarn_quantity,
)

CALCULATORS = {
    "yarn_quantity": yarn_quantity,
    "needle_recommendation": needle_recommendation,
    "tension_diagnosis": tension_diagnosis,
}

# Minimum pass rate per metric. Latency is reported but
# never gated: wall-clock time on a busy machine changes with no code change.
THRESHOLDS = {
    "offline": {"intent": 1.0, "numbers_post": 1.0, "decline": 1.0, "golden": 1.0},
    "openai": {"intent": 0.93, "numbers_pre": 0.95, "numbers_post": 1.0, "decline": 1.0, "golden": 1.0},
}
TUNED_SET = "questions"  # the set the rule router was built against; the only one that gates
HELD_OUT_SET = "held_out"  # written after the router was built; reported, never gated
SET_LABELS = {"questions": "tuned", "held_out": "held-out"}
IST = timezone(timedelta(hours=5, minutes=30))

# The checks that decide whether a question passed. None ("not applicable") counts as a pass.
PASS_CHECKS = (
    "intent_correct", "params_correct", "decline_correct", "ask_correct",
    "numbers_post", "golden_correct",
)


# =============================================================================
# Main
# =============================================================================


def main() -> int:
    args = _parse_args()

    if args.offline:
        provider, mode, mode_label = RuleProvider(), "offline", "offline (rules + templates)"
    else:
        load_dotenv(find_dotenv(usecwd=True))
        try:
            provider = OpenAIProvider()
        except ProviderError as exc:
            print(f"cannot run provider eval: {exc}", file=sys.stderr)
            return 2
        mode, mode_label = "openai", f"provider: openai {provider.model}"

    sets = []
    for set_name in args.questions:
        path = HERE / f"{set_name}.jsonl"
        if not path.exists():
            print(f"no such question set: {path}", file=sys.stderr)
            return 2
        sets.append(_run_set(set_name, _load_questions(path), provider, mode, print_progress=not args.offline))

    meta = {
        "timestamp": datetime.now(IST).strftime("%Y-%m-%d %H:%M IST"),
        "git": _git_sha(),
        "mode": mode_label,
        "question_sets": args.questions,
    }
    report = _write_results(args.out, args.questions, mode, meta, sets)
    print(report.split("## Per question")[0].rstrip())

    gate_failures = [failure for one_set in sets if one_set["gated"] for failure in one_set["fails"]]
    return 1 if gate_failures else 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--offline", action="store_true", help="rule router + templates")
    mode.add_argument("--provider", choices=["openai"], help="real LLM provider")
    parser.add_argument("--out", type=Path, default=HERE / "results")
    parser.add_argument(
        "--questions",
        nargs="+",
        default=[TUNED_SET, HELD_OUT_SET],
        metavar="SET",
        help=f"question set name(s); <name>.jsonl beside this file (default: {TUNED_SET})",
    )
    return parser.parse_args()


def _load_questions(path: Path) -> list[dict]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line]


def _run_set(set_name: str, questions: list[dict], provider, mode: str, print_progress: bool) -> dict:
    """Ask every question in the set, score each answer, and summarise."""
    calls_before = getattr(provider, "calls", 0)
    rows = []
    for question in questions:
        row = score(question, answer(question["question"], provider=provider))
        rows.append(row)
        if print_progress:
            outcome = "ok" if row["passed"] else "FAIL"
            print(f"{question['id']}: {outcome} {row['latency_ms']:.0f} ms", file=sys.stderr)

    provider_calls = getattr(provider, "calls", 0) - calls_before
    summary = summarise(rows, provider_calls, used_llm=mode != "offline")
    return {
        "name": set_name,
        "rows": rows,
        "summary": summary,
        "fails": check_thresholds(mode, summary),
        "gated": set_name == TUNED_SET,  # held-out sets are diagnostics, never a gate
    }


def _write_results(out_dir: Path, set_names: list[str], mode: str, meta: dict, sets: list[dict]) -> str:
    """Write the JSON results and the markdown report; return the report."""
    # The committed files carry every set. A run of only some sets gets a suffix.
    is_full_run = set_names == [TUNED_SET, HELD_OUT_SET]
    suffix = "" if is_full_run else "_" + "_".join(set_names)

    results = {
        "meta": meta,
        "sets": {
            one_set["name"]: {
                "summary": one_set["summary"],
                "threshold_failures": one_set["fails"],
                "gated": one_set["gated"],
                "rows": one_set["rows"],
            }
            for one_set in sets
        },
        # Older readers expect the first set's numbers at the top level.
        "summary": sets[0]["summary"],
        "threshold_failures": sets[0]["fails"],
        "rows": sets[0]["rows"],
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"eval_results_{mode}{suffix}.json").write_text(
        json.dumps(results, indent=2, default=str), encoding="utf-8"
    )
    report = render(meta, sets)
    (out_dir / f"eval_report_{mode}{suffix}.md").write_text(report, encoding="utf-8")
    return report


# =============================================================================
# Scoring one answer
# =============================================================================


def score(question: dict, result: AnswerResult) -> dict:
    """One report row: which checks the answer passed, plus the reply for debugging."""
    tolerance = question.get("tolerance", 0.05)
    expected_calc = _expected_calculation(question)

    row = {
        "id": question["id"],
        "category": question["category"],
        "intent_correct": result.intent == question["expected_intent"],
        "params_correct": _params_match(result.params, question["expected_params"], tolerance),
        "numbers_pre": None,
        "numbers_post": None,
        "decline_correct": _decline_correct(question, result),
        "golden_correct": None,
        "ask_correct": _ask_correct(question, result),
        "guard_rejected": result.guard_rejected,
        "route": result.route,
        "phrase": result.phrase,
        "latency_ms": result.elapsed_ms,
        "reply": result.reply,
        "draft": result.draft,
        "params": result.params,
        "missing": result.missing,
    }

    if expected_calc is not None:
        intent_name = question["expected_intent"]
        row["numbers_pre"] = _numbers_ok(result.draft, intent_name, expected_calc, tolerance)
        row["numbers_post"] = _numbers_ok(result.reply, intent_name, expected_calc, tolerance)
        row["expected_result"] = expected_calc.result
        if question.get("expected_values"):
            row["golden_correct"] = _golden_values_match(expected_calc, question["expected_values"])

    row["passed"] = all(row[check] is not False for check in PASS_CHECKS)
    return row


def _expected_calculation(question: dict) -> CalcResult | None:
    """The calculator's answer for the expected inputs, when the question expects one."""
    expects_answer = (
        question["expected_intent"] in CALCULATORS
        and not question["expect_ask"]
        and not question["expect_decline"]
    )
    if not expects_answer:
        return None
    return CALCULATORS[question["expected_intent"]](**question["expected_params"])


def _params_match(actual: dict, expected: dict, tolerance: float) -> bool:
    if set(actual) != set(expected):
        return False
    return all(_close(actual[name], value, tolerance) for name, value in expected.items())


def _decline_correct(question: dict, result: AnswerResult) -> bool:
    # A decline is correct when the knitter is told why, whether the router declined or
    # the calculator rejected the inputs (e.g. a negative width).
    if question["expect_decline"]:
        return bool(result.decline_reason)
    return not result.decline_reason


def _ask_correct(question: dict, result: AnswerResult) -> bool:
    if question["expect_ask"]:
        return set(result.missing) == set(question.get("expected_missing", []))
    return not result.missing


def _golden_values_match(expected_calc: CalcResult, golden_values: dict) -> bool:
    """The brief's worked examples, pinned by hand. Unlike every other check they fail
    when domain.yaml changes; that is the point: re-derive and update them together."""
    return all(
        _close(expected_calc.result.get(name), value, 0.0) for name, value in golden_values.items()
    )


def _numbers_ok(text: str | None, intent_name: str, expected: CalcResult, tolerance: float) -> bool:
    """Every number traces to the expected calculation, and the main answer is stated."""
    if not text:
        return False
    return guard.verify(text, expected, tolerance) and _headline_present(text, intent_name, expected)


def _headline_present(text: str, intent_name: str, calc: CalcResult) -> bool:
    """The reply must state the main answer with its unit, not just avoid wrong numbers.

    This is the eval's own check, kept separate from guard.py on purpose so the eval
    measures the guard instead of trusting it.
    """
    numbers_in_text = guard.labelled_numbers(text)
    result = calc.result

    def states(value: float, kind: str, tolerance: float) -> bool:
        for number, number_kind in numbers_in_text:
            if number_kind == kind and math.isclose(abs(number), abs(value), rel_tol=tolerance, abs_tol=0.05):
                return True
        return False

    if intent_name == "yarn_quantity":
        return states(result["metres"], "m", 0.05) and states(result["balls"], "count", 0.0)
    if intent_name == "needle_recommendation":
        return states(result["metric_mm"], "mm", 0.0)
    # Tension: the full diagnosis phrase ("too tight"), not just its last word, because
    # "gauge" (from "on gauge") appears in nearly every tension reply.
    return result["diagnosis"] in text.lower() and states(result["diff_pct"], "pct", 0.0)


def _close(actual: object, expected: object, tolerance: float) -> bool:
    """Numbers within tolerance; anything else must be equal."""
    if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        return math.isclose(float(actual), float(expected), rel_tol=tolerance, abs_tol=0.01)
    return actual == expected


# =============================================================================
# Summary and thresholds
# =============================================================================


def summarise(rows: list[dict], provider_calls: int, used_llm: bool) -> dict:
    """Pass counts per metric as (passed, total), plus latency percentiles."""
    latencies = [row["latency_ms"] for row in rows]
    calculation_rows = [row for row in rows if row["numbers_post"] is not None]
    golden_rows = [row for row in rows if row["golden_correct"] is not None]

    def passed_of(check: str, subset: list[dict]) -> tuple[int, int]:
        return sum(1 for row in subset if row[check]), len(subset)

    return {
        "intent": passed_of("intent_correct", rows),
        "params": passed_of("params_correct", rows),
        "numbers_pre": passed_of("numbers_pre", calculation_rows),
        "numbers_post": passed_of("numbers_post", calculation_rows),
        "decline": passed_of("decline_correct", rows),
        "ask": passed_of("ask_correct", rows),
        "golden": passed_of("golden_correct", golden_rows),
        "guard_rejections": sum(1 for row in rows if row["guard_rejected"]),
        "route_fallbacks": sum(1 for row in rows if row["route"] == "rules") if used_llm else 0,
        "p50_ms": _percentile(latencies, 0.5),
        "p95_ms": _percentile(latencies, 0.95),
        "max_ms": max(latencies),
        "provider_calls": provider_calls,
    }


def check_thresholds(mode: str, summary: dict) -> list[str]:
    """Metrics below their minimum pass rate. Accuracy only; latency is never gated."""
    failures = []
    for metric, minimum in THRESHOLDS[mode].items():
        passed, total = summary[metric]
        if total and passed / total < minimum:
            failures.append(f"{metric} {passed}/{total} < {minimum:.0%}")
    return failures


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


# =============================================================================
# Markdown report
# =============================================================================


def render(meta: dict, sets: list[dict]) -> str:
    """The report: one column per question set, so tuned and held-out are read side by side."""
    lines = _summary_table(meta, sets) + _explanation()
    for one_set in sets:
        lines += _per_question_table(one_set) + _failures(one_set)
    return "\n".join(lines) + "\n"


def set_label(name: str) -> str:
    return SET_LABELS.get(name, name)


def _summary_table(meta: dict, sets: list[dict]) -> list[str]:
    total_questions = sum(len(one_set["rows"]) for one_set in sets)
    column_titles = [f"{set_label(one_set['name'])} (n={len(one_set['rows'])})" for one_set in sets]

    def table_row(title: str, cell) -> str:
        cells = [cell(one_set["summary"]) for one_set in sets]
        return f"| {title} | " + " | ".join(cells) + " |"

    def golden_cell(summary: dict) -> str:
        return _as_percent(*summary["golden"]) if summary["golden"][1] else "–"

    def latency_cell(summary: dict) -> str:
        return f"{summary['p50_ms']:.0f} / {summary['p95_ms']:.0f} / {summary['max_ms']:.0f} ms"

    lines = [
        "# Assistant evaluation report",
        f"run: {meta['timestamp']}  git: {meta['git']}  mode: {meta['mode']}  questions: {total_questions}",
        "",
        "## Summary",
        "| metric | " + " | ".join(column_titles) + " |",
        "|---" * (len(sets) + 1) + "|",
        table_row("intent accuracy", lambda summary: _as_percent(*summary["intent"])),
        table_row("params correct", lambda summary: _as_percent(*summary["params"])),
        table_row("numbers match (pre-guard)", lambda summary: _as_percent(*summary["numbers_pre"])),
        table_row("numbers match (post-guard)", lambda summary: _as_percent(*summary["numbers_post"])),
        table_row("decline correct", lambda summary: _as_percent(*summary["decline"])),
        table_row("ask correct", lambda summary: _as_percent(*summary["ask"])),
        table_row("golden values (pinned)", golden_cell),
        table_row("guard rejections", lambda summary: str(summary["guard_rejections"])),
        table_row("route fell back to rules", lambda summary: str(summary["route_fallbacks"])),
        table_row("latency p50 / p95 / max (reported, not gated)", latency_cell),
        table_row("provider calls", lambda summary: str(summary["provider_calls"])),
    ]
    threshold_cells = [_threshold_cell(one_set) for one_set in sets]
    lines.append("| thresholds | " + " | ".join(threshold_cells) + " |")
    return lines


def _threshold_cell(one_set: dict) -> str:
    if not one_set["gated"]:
        return "not gated (diagnostic)"
    if not one_set["fails"]:
        return "PASS"
    return "FAIL: " + "; ".join(one_set["fails"])


def _explanation() -> list[str]:
    return [
        "",
        "Numbers match = every number in the reply traces to the calculator's result for the expected inputs, "
        "and the headline answer is stated. Pre-guard scores the provider's draft; post-guard scores what the user sees.",
        "Golden values = the brief's worked examples, hand-pinned; they fail on purpose if a domain constant changes.",
        "",
        "> The **tuned** set is the set the rule router was fitted on, so its score measures fit, not generalisation. "
        "The **held-out** set was written afterwards from phrasings the router never saw; it is reported honestly and "
        "is not a pass/fail gate. Read the held-out column as the realistic offline accuracy.",
    ]


def _per_question_table(one_set: dict) -> list[str]:
    lines = [
        "",
        f"## Per question — {set_label(one_set['name'])} ({one_set['name']}.jsonl)",
        "| id | category | intent | params | numbers (pre/post) | decline/ask | golden | route/phrase | guard | ms |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in one_set["rows"]:
        if row["guard_rejected"]:
            guard_cell = "REJECTED"
        elif row["numbers_post"] is not None:
            guard_cell = "pass"
        else:
            guard_cell = "–"
        lines.append(
            f"| {row['id']} | {row['category']} | {_mark(row['intent_correct'])} | {_mark(row['params_correct'])} | "
            f"{_mark(row['numbers_pre'])} / {_mark(row['numbers_post'])} | "
            f"{_mark(row['decline_correct'] and row['ask_correct'])} | {_mark(row['golden_correct'])} | "
            f"{row['route']}/{row['phrase']} | {guard_cell} | {row['latency_ms']:.0f} |"
        )
    return lines


def _failures(one_set: dict) -> list[str]:
    """Raw detail for failed questions, and for any the guard had to rescue."""
    lines = ["", f"### Failures (raw) — {set_label(one_set['name'])}"]
    failing = [
        row for row in one_set["rows"]
        if not row["passed"] or row["guard_rejected"] or row["numbers_pre"] is False
    ]
    if not failing:
        lines.append("None.")
    for row in failing:
        lines += [
            f"#### {row['id']}",
            f"- params: `{json.dumps(row['params'])}` missing: `{row['missing']}`",
            f"- expected result: `{json.dumps(row.get('expected_result'))}`",
            f"- draft: {row['draft']!r}",
            f"- reply: {row['reply']!r}",
        ]
    return lines


def _as_percent(passed: int, total: int) -> str:
    return f"{passed}/{total} ({(100 * passed / total) if total else 0:.0f}%)"


def _mark(value: bool | None) -> str:
    if value is None:
        return "–"
    return "✓" if value else "✗"


def _git_sha() -> str:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=HERE
        )
        return completed.stdout.strip() or "unknown"
    except OSError:
        return "unknown"


if __name__ == "__main__":
    sys.exit(main())
