"""Questions the assistant declines, and the fixed sentence it gives for each.

A decline reason is always one of the sentences written here, never text from an
LLM. The LLM router may only pick a category name from DECLINE_CATEGORIES.

    matching_declines("Is wool warmer than acrylic?")
        -> [("material_comparison", "comparing fibres or materials is ...")]
"""

from __future__ import annotations

import re

# category -> (words that trigger it, the reason shown to the knitter)
DECLINES: dict[str, tuple[re.Pattern[str], str]] = {
    "crochet": (
        re.compile(r"\bcrochet\b", re.IGNORECASE),
        "this assistant covers knitting only; crochet isn't supported.",
    ),
    "material_comparison": (
        re.compile(r"\b(warmer than|cooler than|versus|vs\.?|better than)\b", re.IGNORECASE),
        "comparing fibres or materials is a matter of opinion and experience, not a calculation.",
    ),
    "colour_or_dye_lot": (
        re.compile(r"\bdye lots?\b", re.IGNORECASE),
        "colour or dye-lot matching isn't something this assistant can calculate.",
    ),
    "time_estimate": (
        re.compile(r"\bhow long\b|\bhow much time\b|\bhow many hours\b", re.IGNORECASE),
        "there's no reliable calculation for knitting time; it depends too much on the knitter.",
    ),
    "garment_sizing": (
        re.compile(r"\braglan\b|\bsize\s+(?:XS|S|M|L|XL|XXL|small|medium|large)\b", re.IGNORECASE),
        "garment sizing charts aren't supported; give the exact width and height instead.",
    ),
    # How-to questions often name a yarn weight ("a stretchy cast-on in 4ply"), which
    # would otherwise look like a needle question.
    "technique": (
        re.compile(
            r"\bcast[- ]?ons?\b|\bcasting on\b|\bcast[- ]?off\b|\bbind[- ]?off\b"
            r"|\bbinding off\b|\bseam(?:ing|s|ed)?\b|\bmattress stitch\b|\bblocking\b"
            r"|\bpick(?:ing)?\s+up\s+stitch(?:es)?\b|\bgraft(?:ing)?\b|\bkitchener\b"
            r"|\bweav(?:e|ing)\s+in\b|\bshort[- ]rows?\b|\bsteek(?:ing|s)?\b",
            re.IGNORECASE,
        ),
        "that's a technique question rather than a calculation; this assistant only works out "
        "yarn quantity, needle size and tension.",
    ),
}

# The categories the LLM router may choose from ("other" = none of the above).
DECLINE_CATEGORIES = (*DECLINES, "other")

# Used when the question isn't about yarn, needles or tension at all.
FALLBACK_DECLINE_REASON = (
    "this assistant only answers yarn quantity, needle size and tension questions."
)

# ASSUMPTION: row gauge is a real question, but it needs a rows-per-10cm model we don't
# have, so it gets its own decline instead of being misread as a stitch count.
ROW_GAUGE = re.compile(r"\d+(?:\.\d+)?\s*rows?\b", re.IGNORECASE)
ROW_GAUGE_DECLINE_REASON = (
    "row gauge isn't supported yet; give the stitch counts per 10cm and I can diagnose those."
)

# Declines that name a cause. When the LLM misses one of these, the router keeps it.
# The general FALLBACK_DECLINE_REASON is not in this set: a question the rules can't
# place is exactly the kind the LLM should be allowed to understand.
SPECIFIC_DECLINE_REASONS = {reason for _pattern, reason in DECLINES.values()} | {
    ROW_GAUGE_DECLINE_REASON
}


def matching_declines(text: str) -> list[tuple[str, str]]:
    """[(category, reason), ...] for every decline category whose words appear in `text`,
    in the order DECLINES lists them."""
    matches = []
    for category, (pattern, reason) in DECLINES.items():
        if pattern.search(text):
            matches.append((category, reason))
    return matches


def mentions_row_gauge(text: str) -> bool:
    """True for "30 rows per 10cm" and similar."""
    return bool(ROW_GAUGE.search(text))


def reason_for_category(category: str | None) -> str:
    """The fixed reason for a category name the LLM picked; the general reason otherwise."""
    if category in DECLINES:
        return DECLINES[category][1]
    return FALLBACK_DECLINE_REASON
