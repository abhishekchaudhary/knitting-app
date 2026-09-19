"""The trust check: a reply may only contain numbers the calculator produced.

The LLM writes a friendly reply from a CalcResult, and it can misremember or invent
a number. Before a reply reaches the knitter, this file checks two things:

1. Every number is a calculator value of the right kind. A number is read together
   with its label ("429 m", "4 balls", "9.1%", "5.0mm", "US 8"). "60 balls" fails even
   though 60 is the height, because 60 is not a ball count. A number with no label
   must equal one of the calculated answers.
2. The reply states the headline answer (metres and balls, the needle size, or the
   tension diagnosis) and doesn't contradict it ("too loose" when it is too tight).

If either check fails, assistant.py sends the template reply instead.

    problems("You need about 429 m, so 4 balls.", calc)   -> []
    problems("You need about 500 m, so 4 balls.", calc)   -> ["number:500", "headline:metres"]

Knitting notation such as "1x1", "k2p2" or "4 ply" is not a quantity and is skipped.
"""

from __future__ import annotations

import math
import re

from knitcalc.calculators import CalcResult
from knitcalc.domain import DOMAIN
from knitcalc.units import cm_to_in

# --- Labels: what kind of quantity a number is ---------------------------------

# The label written next to a number -> the kind of quantity it names.
LABEL_TO_KIND = {
    "mm": "mm", "cm": "cm", "m": "m", "metre": "m", "metres": "m", "meter": "m", "meters": "m",
    "ball": "count", "balls": "count", "skein": "count", "skeins": "count",
    "g": "g", "gram": "g", "grams": "g", "%": "pct", "percent": "pct",
    "st": "sts", "sts": "sts", "stitch": "sts", "stitches": "sts",
    "in": "in", "inch": "in", "inches": "in", '"': "in", "us": "us", "uk": "uk",
}

# Kind of quantity -> the CalcResult fields a number of that kind may match.
KIND_TO_FIELDS = {
    "m": {"metres", "ball_metres", "m_per_100cm2"},
    "count": {"balls"},
    "mm": {"metric_mm", "range_min_mm", "range_max_mm", "target_mm", "suggested_needle_change_mm", "mm_per_stitch"},
    "cm": {"width_cm", "height_cm", "gauge_width_cm"},
    "in": {"width_in", "height_in", "gauge_width_in"},
    "g": {"ball_grams"},
    "pct": {"diff_pct", "safety_margin_pct"},
    "sts": {"gauge_sts_10cm", "typical_gauge", "actual_sts_10cm", "target_sts_10cm", "stitches_per_needle_size"},
    "us": {"us"},
    "uk": {"uk"},
}

# How close a number must be to count as the same value: (relative, absolute) per kind.
# Rounding in prose ("429 m" for 428.6) is allowed; a different ball count is not.
# A relative tolerance of None would mean "use the caller's `tolerance` argument".
KIND_TOLERANCE: dict[str, tuple[float | None, float]] = {
    "m": (0.0, 0.5), "count": (0.0, 0.0), "mm": (0.0, 0.05), "cm": (0.01, 0.05), "in": (0.01, 0.05),
    "g": (0.0, 0.0), "pct": (0.0, 0.15), "sts": (0.0, 0.05), "us": (0.0, 0.0), "uk": (0.0, 0.0),
}

# A number with no label must be one of the calculated answers, within this.
UNLABELLED_TOLERANCE = 0.05

NUMBER_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "dozen": 12,
}

# --- Patterns --------------------------------------------------------------------

LABEL = r'mm|cm|metres?|meters?|m|balls?|skeins?|grams?|g|%|percent|stitch(?:es)?|sts?|inch(?:es)?|in|"'

# Knitting notation that looks numeric but isn't a quantity: removed before checking.
STITCH_RATIO = re.compile(r"(?<![\d.])(?:\d+x\d+|k\d+p\d+)(?![\d.])", re.IGNORECASE)
NOT_A_QUANTITY = re.compile(
    r"(?<![\d.])\d+(?:\.\d+)?\s*(?:ply|needle sizes?|sizes?)\b", re.IGNORECASE
)

# A number, with an optional "US"/"UK" prefix (upper case only) and optional label after it.
NUMBER_WITH_LABEL = re.compile(
    rf"(?:\b(?P<prefix>(?-i:US|UK))\s*)?"
    rf"(?<![\d.])(?P<number>-?\d[\d,]*(?:\.\d+)?)"
    rf"(?:\s*(?P<label>{LABEL})(?![A-Za-z]))?",
    re.IGNORECASE,
)
# A number written as a word, followed by a label: "four balls".
NUMBER_WORD_WITH_LABEL = re.compile(
    rf"\b(?P<word>{'|'.join(NUMBER_WORDS)})\s+(?P<label>{LABEL})(?![A-Za-z])", re.IGNORECASE
)

# The opposite of each diagnosis word: a reply that says this contradicts the calculator.
DIAGNOSIS_OPPOSITES = {"tight": ("loose",), "loose": ("tight",), "gauge": ("tight", "loose")}


# =============================================================================
# Public checks
# =============================================================================


def verify(draft: str, calc: CalcResult, tolerance: float = 0.05) -> bool:
    """True when the draft passes every check."""
    return not problems(draft, calc, tolerance)


def problems(draft: str, calc: CalcResult, tolerance: float = 0.05) -> list[str]:
    """Everything wrong with the draft: unknown numbers first, then headline problems.

    Each entry is a short code for the log, e.g. "number:500" or "headline:metres".
    """
    number_problems = [f"number:{value:g}" for value in find_leaks(draft, calc, tolerance)]
    return number_problems + _headline_problems(draft, calc)


def find_leaks(draft: str, calc: CalcResult, tolerance: float = 0.05) -> list[float]:
    """Numbers in the draft that aren't a calculator value of the matching kind."""
    allowed_by_field = _allowed_values(calc)
    answers = _answer_values(calc)

    leaks = []
    for value, kind in labelled_numbers(draft):
        if kind is None:
            is_known = _matches_any(value, answers, 0.0, UNLABELLED_TOLERANCE)
        else:
            is_known = _matches_field_of_kind(value, kind, allowed_by_field, tolerance)
        if not is_known:
            leaks.append(value)
    return leaks


def labelled_numbers(text: str) -> list[tuple[float, str | None]]:
    """(value, kind) for every number in the text. kind is None when there is no label."""
    text = STITCH_RATIO.sub(" ", text)
    text = NOT_A_QUANTITY.sub(" ", text)

    found: list[tuple[float, str | None]] = []
    for match in NUMBER_WITH_LABEL.finditer(text):
        value = float(match["number"].replace(",", ""))
        label = match["prefix"] or match["label"]
        kind = LABEL_TO_KIND[label.lower()] if label else None
        found.append((value, kind))

    for match in NUMBER_WORD_WITH_LABEL.finditer(text):
        value = float(NUMBER_WORDS[match["word"].lower()])
        found.append((value, LABEL_TO_KIND[match["label"].lower()]))
    return found


def extract_numbers(text: str) -> list[float]:
    """Every number in the text, without its kind."""
    return [value for value, _kind in labelled_numbers(text)]


# =============================================================================
# Helpers
# =============================================================================


def _allowed_values(calc: CalcResult) -> dict[str, float]:
    """Every value a labelled number may match: the calculator's inputs and results,
    plus the same sizes in inches and the standard 10 cm / 4 in gauge swatch."""
    allowed = calc.named_values()
    for side in ("width", "height"):
        if f"{side}_cm" in allowed:
            allowed[f"{side}_in"] = round(cm_to_in(allowed[f"{side}_cm"]), 2)
    allowed["gauge_width_cm"] = DOMAIN.units.gauge_width_cm
    allowed["gauge_width_in"] = DOMAIN.units.gauge_width_in
    return allowed


def _answer_values(calc: CalcResult) -> list[float]:
    """Only the calculated answers (named_values() also holds the inputs)."""
    named = calc.named_values()
    return [named[field_name] for field_name in calc.result if field_name in named]


def _matches_field_of_kind(
    value: float, kind: str, allowed_by_field: dict[str, float], tolerance: float
) -> bool:
    relative, absolute = KIND_TOLERANCE[kind]
    if relative is None:
        relative = tolerance
    for field_name in KIND_TO_FIELDS[kind]:
        if field_name in allowed_by_field and _is_close(
            value, allowed_by_field[field_name], relative, absolute
        ):
            return True
    return False


def _matches_any(value: float, candidates: list[float], relative: float, absolute: float) -> bool:
    return any(_is_close(value, candidate, relative, absolute) for candidate in candidates)


def _is_close(value: float, expected: float, relative: float, absolute: float) -> bool:
    """Equal within tolerance, ignoring sign ("-9.1%" and "9.1% smaller" are the same)."""
    return math.isclose(
        abs(value), abs(expected), rel_tol=relative, abs_tol=max(absolute, 1e-9)
    )


def _headline_problems(draft: str, calc: CalcResult) -> list[str]:
    """The reply must state the answer it was asked for (the eval uses the same rule)."""
    numbers_in_draft = labelled_numbers(draft)
    result = calc.result
    found = []

    if "metres" in result:
        if not _states(numbers_in_draft, result["metres"], "m"):
            found.append("headline:metres")
        if not _states(numbers_in_draft, float(result["balls"]), "count"):
            found.append("headline:balls")

    elif "metric_mm" in result:
        if not _states(numbers_in_draft, result["metric_mm"], "mm"):
            found.append("headline:metric_mm")

    elif "diagnosis" in result:
        found += _diagnosis_problems(draft, result["diagnosis"])
        if not _states(numbers_in_draft, result["diff_pct"], "pct"):
            found.append("headline:diff_pct")

    return found


def _diagnosis_problems(draft: str, diagnosis: object) -> list[str]:
    """The diagnosis word ("tight", "loose", "gauge") must appear, and its opposite must not."""
    diagnosis_word = str(diagnosis).split()[-1].lower()
    draft_lower = draft.lower()
    found = []
    if diagnosis_word not in draft_lower:
        found.append("headline:diagnosis")
    for opposite in DIAGNOSIS_OPPOSITES.get(diagnosis_word, ()):
        if re.search(rf"\b{opposite}\b", draft_lower):
            found.append(f"contradiction:{opposite}")
    return found


def _states(numbers_in_draft: list[tuple[float, str | None]], value: float, kind: str) -> bool:
    """True when the draft contains `value` labelled as `kind`."""
    relative, absolute = KIND_TOLERANCE[kind]
    for number, number_kind in numbers_in_draft:
        if number_kind == kind and _is_close(number, value, relative or 0.0, absolute):
            return True
    return False
