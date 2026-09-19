"""Read the knitter's inputs out of the question text. No LLM, no guessing.

Each `read_*` function looks for one input and returns it, or None when the
question doesn't state it. The router decides what to do with a None (usually:
ask the knitter). Words are matched against the aliases in domain.yaml, so
adding an alias there teaches the reader a new word.

    read_dimensions("a 50 x 60cm blanket")      -> ((50.0, 60.0), False)
    read_weight("How much DK yarn ...")          -> ("light", "dk")
    read_tension_pair("swatch is 24 ... says 22") -> (24.0, 22.0)
"""

from __future__ import annotations

import re
from typing import Any

from knitcalc.domain import DOMAIN
from knitcalc.units import in_to_cm

# --- Numbers --------------------------------------------------------------------

# A number as a knitter writes it. "50,5" is a European decimal; "1,000" is a thousands
# separator (a comma followed by exactly three digits). A leading minus is kept on
# purpose: the calculator rejects "-50" with a clear error, which is safer than
# silently answering for 50.
NUMBER = r"-?\d+(?:,\d{3})*(?:[.,]\d+)?"
THOUSANDS_SEPARATOR = re.compile(r"(?<=\d),(?=\d{3}(?!\d))")
PLAIN_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def to_float(number_text: str) -> float:
    """ "50,5" -> 50.5 (decimal comma); "1,000" -> 1000.0 (thousands separator)."""
    without_thousands = THOUSANDS_SEPARATOR.sub("", number_text)
    return float(without_thousands.replace(",", "."))


def numbers_in(text: str) -> set[float]:
    """Every number written in the text. "1,000" counts as one number, not 1 and 000."""
    without_thousands = THOUSANDS_SEPARATOR.sub("", text)
    return {float(number) for number in PLAIN_NUMBER.findall(without_thousands)}


# --- Dimensions (width x height) ------------------------------------------------

# ASSUMPTION: a pair written without units ("50x60") is centimetres, but only when both
# numbers are at least this big. "1x1" and "2x2" are rib names, not a blanket size.
MIN_UNITLESS_DIMENSION_CM = 10.0
UNITLESS_DIMENSION_ASSUMPTION = "No units given for the dimensions; read them as centimetres."


def _number_with_unit(name: str) -> str:
    """Regex for a number named `name`, optionally followed by a unit.

    The unit is written with a space ("60 cm", "2 metres") or glued to the number
    ("24in", '24"'). A spaced "in" is not a unit: "60 in stockinette" means the stitch.
    Three alternative groups are needed for this; `_unit_of` reads whichever matched.
    """
    spaced_unit = r"cm|centimet(?:er|re)s?|inch(?:es)?|met(?:er|re)s?|m"
    return (
        rf"(?P<{name}>{NUMBER})"
        rf"(?:\s*(?P<{name}_spaced_unit>{spaced_unit})(?![a-z])"
        rf"|(?P<{name}_glued_inch>in)(?![a-z])"
        rf'|(?P<{name}_quote_inch>"))?'
    )


# "50 x 60cm", "50cm by 60cm", "50 × 60"
SIZE_PAIR = re.compile(
    _number_with_unit("width") + r"\s*(?:x|×|by)\s*" + _number_with_unit("height"),
    re.IGNORECASE,
)
# "50cm wide and 60cm long"
SIZE_WIDE_LONG = re.compile(
    _number_with_unit("width") + r"\s*wide.*?" + _number_with_unit("height") + r"\s*long",
    re.IGNORECASE | re.DOTALL,
)
# "a 30cm square"
SIZE_SQUARE = re.compile(_number_with_unit("side") + r"\s+square", re.IGNORECASE)
# Any number, with its unit if one is written.
ANY_NUMBER_WITH_UNIT = re.compile(_number_with_unit("value"), re.IGNORECASE)


def read_dimensions(text: str) -> tuple[tuple[float, float] | None, bool]:
    """((width_cm, height_cm), assumed_cm) from the question, or (None, False).

    `assumed_cm` is True when no unit was written, so the caller can tell the knitter
    that the numbers were read as centimetres.
    """
    for match in SIZE_PAIR.finditer(text):
        size = _width_and_height_cm(match)
        if size:
            return size, _has_no_units(match)

    match = SIZE_WIDE_LONG.search(text)
    if match:
        size = _width_and_height_cm(match)
        if size:
            return size, _has_no_units(match)

    match = SIZE_SQUARE.search(text)
    if match:
        unit = _unit_of(match, "side")
        if unit:
            side_cm = round(to_cm(to_float(match["side"]), unit), 2)
            return (side_cm, side_cm), False

    return None, False


def read_unit_after(text: str, value: float) -> str | None:
    """The unit written right after `value` in the text ("60cm" -> "cm"), if any."""
    for match in ANY_NUMBER_WITH_UNIT.finditer(text):
        if to_float(match["value"]) != value:
            continue
        unit = _unit_of(match, "value")
        if unit:
            return unit
    return None


def to_cm(value: float, unit: str | None) -> float:
    """Convert a length to centimetres. No unit means centimetres."""
    if unit is None or unit.startswith("c"):
        return value
    if unit.startswith("m"):
        return value * 100
    return in_to_cm(value)


def _width_and_height_cm(match: re.Match[str]) -> tuple[float, float] | None:
    width = to_float(match["width"])
    height = to_float(match["height"])
    width_unit = _unit_of(match, "width")
    height_unit = _unit_of(match, "height")

    if width_unit is None and height_unit is None:
        if min(abs(width), abs(height)) < MIN_UNITLESS_DIMENSION_CM:
            return None  # "1x1" is a rib, not a size
        return round(width, 2), round(height, 2)

    # A unit written once applies to both numbers: "50 x 60cm" and "50cm x 60".
    if width_unit is None:
        width_unit = height_unit
    if height_unit is None:
        height_unit = width_unit
    return round(to_cm(width, width_unit), 2), round(to_cm(height, height_unit), 2)


def _has_no_units(match: re.Match[str]) -> bool:
    return _unit_of(match, "width") is None and _unit_of(match, "height") is None


def _unit_of(match: re.Match[str], name: str) -> str | None:
    """The unit matched after the number called `name`, lower-cased, or None."""
    for group in (f"{name}_spaced_unit", f"{name}_glued_inch", f"{name}_quote_inch"):
        if match[group]:
            return match[group].lower()
    return None


# --- Yarn weight, stitch pattern, project, fabric -------------------------------

# The fabric words the needle recommender understands, straight from domain.yaml.
# providers.router_schema() offers the same list to the LLM.
FABRIC_TOKENS: tuple[str, ...] = tuple(DOMAIN.needle_recommender.fabric.model_dump())


def _ambiguous_weight_aliases() -> set[str]:
    """Weight aliases that are also everyday words in a knitting question.

    "baby blanket", "a rug", "an afghan", "a light, airy scarf" don't name a yarn weight.
    Words shared with the project and stitch vocabularies are found automatically; the
    rest are listed here.
    ASSUMPTION: these words only name a weight when written as "<word> weight",
    "in <word>" or "<word> yarn" (see read_weight).
    """
    project_and_stitch_words = set()
    for item in (*DOMAIN.needle_recommender.projects, *DOMAIN.stitches.items):
        for alias in item.aliases:
            project_and_stitch_words.add(alias.lower())
    return project_and_stitch_words | {"baby", "rug", "afghan", "craft", "light", "sport"}


AMBIGUOUS_WEIGHT_ALIASES = _ambiguous_weight_aliases()

# How a weight is usually stated, strongest signal first. "in lace stitch" names the
# stitch pattern, not the yarn, so "in <alias>" skips it.
WEIGHT_PHRASINGS = [
    r"\b{alias}\s+weight\b",
    r"\bin\s+{alias}\b(?!\s+(?:stitch|pattern))",
    r"\b{alias}\s+yarn\b",
]

# "<word> stitch" names a stitch pattern, unless the word is one of these.
WORD_BEFORE_STITCH = re.compile(r"\b(?P<word>[a-z][a-z'-]+)\s+stitch(?:es)?\b", re.IGNORECASE)
NOT_A_STITCH_NAME = {
    "one", "a", "an", "the", "each", "every", "per", "this", "that", "my", "your",
    "knit", "purl", "first", "last", "next", "same", "extra", "more", "fewer",
}


def read_weight(text: str) -> tuple[str | None, str | None]:
    """(weight key, the alias as written), or (None, None).

    First tries the explicit phrasings ("sport weight", "in DK", "worsted yarn"), then a
    bare word. Ambiguous words ("baby", "light") are never read as a bare word, so the
    knitter is asked for the weight instead of being given the wrong one.
    """
    aliases = _aliases_longest_first(DOMAIN.weights)
    for phrasing in WEIGHT_PHRASINGS:
        for weight_key, alias in aliases:
            pattern = phrasing.format(alias=re.escape(alias))
            if re.search(pattern, text, re.IGNORECASE):
                return weight_key, alias
    return _find_alias(text, aliases, skip=AMBIGUOUS_WEIGHT_ALIASES)


def weight_is_really_stated(text: str, weight_key: str) -> bool:
    """True unless the only word supporting `weight_key` is an ambiguous one.

    Used to check the LLM's reading: "baby blanket" contains "baby", but that doesn't
    make the yarn baby weight.
    """
    weight_key_read, _alias = read_weight(text)
    if weight_key_read is not None:
        return True
    weight = DOMAIN.weight_by_alias(weight_key)
    words_for_weight = [*weight.aliases, weight.key.replace("_", " ")]
    for word in words_for_weight:
        if mentions_any(text, [word]) and word.lower() not in AMBIGUOUS_WEIGHT_ALIASES:
            return True
    return False


def read_stitch(text: str, weight_alias: str | None = None) -> tuple[str | None, bool]:
    """(stitch key, unknown_stitch_named).

    `weight_alias` is the word already read as the yarn weight (e.g. "lace" in "lace
    yarn"). It only counts as the stitch too when written as "lace stitch" or "lace
    pattern", so "lace yarn" doesn't also apply the lace stitch multiplier.
    `unknown_stitch_named` is True when the text says "<word> stitch" and no alias
    matches: the caller asks, rather than assuming stockinette.
    """
    stitch_key, alias = _find_alias(text, _aliases_longest_first(DOMAIN.stitches.items))

    alias_is_the_weight = (
        stitch_key and weight_alias and alias and alias.lower() == weight_alias.lower()
    )
    if alias_is_the_weight:
        written_as_stitch = rf"\b{re.escape(alias)}\s+(?:stitch|pattern)\b"
        if not re.search(written_as_stitch, text, re.IGNORECASE):
            stitch_key = None

    if stitch_key:
        return stitch_key, False

    match = WORD_BEFORE_STITCH.search(text)
    unknown_stitch_named = bool(match and match["word"].lower() not in NOT_A_STITCH_NAME)
    return None, unknown_stitch_named


def read_project(text: str) -> str | None:
    """The project key ("scarf", "socks", ...) named in the text, or None."""
    project_key, _alias = _find_alias(
        text, _aliases_longest_first(DOMAIN.needle_recommender.projects)
    )
    return project_key


def read_fabric(text: str) -> str | None:
    """"firm", "balanced" or "drapey" if the text says so, else None."""
    for fabric in FABRIC_TOKENS:
        if re.search(rf"\b{fabric}\b", text, re.IGNORECASE):
            return fabric
    return None


def mentions_any(text: str, words: list[str]) -> bool:
    """True when any of `words` appears in the text as a whole word."""
    for word in words:
        if re.search(rf"\b{re.escape(word)}\b", text, re.IGNORECASE):
            return True
    return False


def _aliases_longest_first(items: list[Any]) -> list[tuple[str, str]]:
    """[(key, alias), ...] for every alias of every item. Longest alias first, so
    "super bulky" is found before "bulky"."""
    pairs = []
    for item in items:
        for alias in item.aliases:
            pairs.append((item.key, alias))
    return sorted(pairs, key=lambda key_and_alias: len(key_and_alias[1]), reverse=True)


def _find_alias(
    text: str, aliases: list[tuple[str, str]], skip: set[str] | None = None
) -> tuple[str | None, str | None]:
    """(key, alias) of the first alias written as a whole word, ignoring `skip`."""
    for key, alias in aliases:
        if skip and alias.lower() in skip:
            continue
        if re.search(rf"\b{re.escape(alias)}\b", text, re.IGNORECASE):
            return key, alias
    return None, None


# --- Gauge (stitches per 10 cm) -------------------------------------------------

STITCHES_WORD = r"(?:sts?|stitch(?:es)?)"
PER_WORD = r"(?:per|to|over|in|/)"

# "24 sts to 10cm", "24 stitches per 10 cm", "24 sts/10cm"
GAUGE_PER_10CM = re.compile(
    rf"(?P<stitches>\d+(?:\.\d+)?)\s*{STITCHES_WORD}\s*{PER_WORD}\s*10\s*cm", re.IGNORECASE
)
# "22 stitches over 4 inches". Gauge labels print "sts per 4 inches (10 cm)", so 4 in is
# the name of the standard 10 cm swatch, not a length to convert: same number, no rescale
# (domain.yaml units.gauge_width_in).
GAUGE_PER_4IN = re.compile(
    rf"(?P<stitches>\d+(?:\.\d+)?)\s*{STITCHES_WORD}\s*{PER_WORD}\s*"
    rf"{DOMAIN.units.gauge_width_in:g}"
    r"\s*(?:in\b|inch(?:es)?|\")",
    re.IGNORECASE,
)
# "my gauge is 24"
GAUGE_IS = re.compile(r"gauge (?:is|of)\s*(?P<stitches>\d+(?:\.\d+)?)", re.IGNORECASE)


def read_gauge(text: str) -> float | None:
    """The knitter's own gauge in stitches per 10 cm, or None."""
    for pattern in (GAUGE_PER_10CM, GAUGE_PER_4IN, GAUGE_IS):
        match = pattern.search(text)
        if match:
            return float(match["stitches"])
    return None


def is_stitch_count(text: str, value: float) -> bool:
    """True when `value` is written as a stitch count: "26 stitches", "26 sts", "gauge is 26"."""
    number = rf"{value:g}(?:\.0+)?"
    followed_by_stitches = rf"(?<![\d.]){number}\s*(?:sts?|stitch(?:es)?)\b"
    after_the_word_gauge = rf"gauge\D{{0,20}}(?<![\d.]){number}(?![\d.])"
    return bool(
        re.search(followed_by_stitches, text, re.IGNORECASE)
        or re.search(after_the_word_gauge, text, re.IGNORECASE)
    )


# --- Tension: the knitter's gauge vs the pattern's gauge ------------------------

COUNT = r"\s*(?P<count>\d+(?:\.\d+)?)"

# Ways a knitter states their own count ...
KNITTER_COUNT_PHRASINGS = [
    re.compile(r"swatch (?:is|has|gives)" + COUNT, re.IGNORECASE),
    re.compile(r"(?:i'?m|i am)\s+getting" + COUNT, re.IGNORECASE),
    re.compile(r"\bi got" + COUNT, re.IGNORECASE),
    re.compile(r"\bmy (?:gauge|tension|swatch)(?: is| comes out at| of)?" + COUNT, re.IGNORECASE),
    re.compile(r"\bgetting" + COUNT, re.IGNORECASE),
]
# ... and the pattern's count. Any knitter phrasing pairs with any pattern phrasing.
PATTERN_COUNT_PHRASINGS = [
    re.compile(
        r"pattern (?:says|wants|calls for|asks for|needs|specifies|is)" + COUNT, re.IGNORECASE
    ),
    re.compile(r"pattern(?:'s)? (?:gauge|tension) (?:is|of)" + COUNT, re.IGNORECASE),
    re.compile(r"(?:should|supposed to) (?:be|get)" + COUNT, re.IGNORECASE),
]


def read_tension_pair(text: str) -> tuple[float, float] | None:
    """(knitter's stitches per 10cm, pattern's stitches per 10cm), or None unless both are found."""
    actual = _first_count(KNITTER_COUNT_PHRASINGS, text)
    target = _first_count(PATTERN_COUNT_PHRASINGS, text)
    if actual is None or target is None:
        return None
    return actual, target


def _first_count(phrasings: list[re.Pattern[str]], text: str) -> float | None:
    for phrasing in phrasings:
        match = phrasing.search(text)
        if match:
            return float(match["count"])
    return None
