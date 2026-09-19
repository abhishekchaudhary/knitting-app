"""The three knitting calculators: yarn quantity, needle size, and tension diagnosis.

Each calculator takes plain inputs, reads its constants from domain.yaml (via DOMAIN),
and returns a CalcResult holding the answer, the formula, the inputs used, the
assumptions made and the source of the constants. The LLM never computes: the phraser
may only describe these numbers, and the guard checks every number it writes.

Example:
    yarn_quantity(width_cm=50, height_cm=60, weight="dk").result
    -> {"metres": 429.0, "balls": 4}
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from knitcalc.domain import DOMAIN, ProjectNudge, StitchItem, Weight
from knitcalc.units import NeedleMatch, needle_row_for


# --- The result every calculator returns -------------------------------------------


@dataclass(frozen=True)
class CalcResult:
    """Contract every calculator returns.

    result: the computed answer, e.g. {"metres": 823.5, "balls": 5}
    formula: short human-readable formula string, for "how this was calculated"
    inputs: the (validated, normalised) inputs used
    assumptions: list of plain-language assumption strings (ASSUMPTION: tags)
    source: domain.yaml source key(s) this calculation drew constants from
    """

    result: dict[str, Any]
    formula: str
    inputs: dict[str, Any]
    assumptions: list[str] = field(default_factory=list)
    source: str = "internal"

    def named_values(self) -> dict[str, float]:
        """Every top-level numeric field of result + inputs, by name: the guard's allow-list.

        Numbers only ever reach the user through these fields (assumption text reuses them).
        """
        numbers_by_name: dict[str, float] = {}
        for name, value in (*self.result.items(), *self.inputs.items()):
            number = _as_number(value)
            if number is not None:
                numbers_by_name[name] = number
        return numbers_by_name

    def values(self) -> list[float]:
        """The numbers from named_values(), without their names."""
        return list(self.named_values().values())


# --- Calculator 1: how much yarn ----------------------------------------------------


def yarn_quantity(
    width_cm: float,
    height_cm: float,
    weight: str,
    stitch: str = "stockinette",
    gauge_sts_10cm: float | None = None,
) -> CalcResult:
    """How many metres and balls of yarn a flat rectangle needs.

    metres = area/100 * m_per_100cm2 * stitch_multiplier * gauge_factor * (1+safety_margin);
    balls = ceil(metres / metres_per_ball). Constants: domain.yaml; sources and calibration: DECISIONS.md §3.
    Raises ValueError for out-of-range sizes or gauge, or an unknown weight or stitch.
    """
    _check_dimension("width_cm", width_cm)
    _check_dimension("height_cm", height_cm)
    yarn_weight = DOMAIN.weight_by_alias(weight)
    stitch_pattern = DOMAIN.stitch_by_alias(stitch)

    assumptions: list[str] = []
    if gauge_sts_10cm is None:
        gauge_sts_10cm = yarn_weight.typical_gauge
        gauge_factor = 1.0
        assumptions.append(
            f"No gauge given; used {yarn_weight.name}'s typical gauge of "
            f"{yarn_weight.typical_gauge} sts/10cm."
        )
    else:
        _check_gauge("gauge_sts_10cm", gauge_sts_10cm)
        gauge_factor = gauge_sts_10cm / yarn_weight.typical_gauge

    safety_margin = DOMAIN.yarn_quantity.safety_margin
    # Round once here so the percentage in the assumption text and in inputs agree.
    safety_margin_pct = round(safety_margin * 100)

    metres = _metres_of_yarn(
        width_cm * height_cm, yarn_weight, stitch_pattern, gauge_factor, safety_margin
    )
    balls = math.ceil(metres / yarn_weight.ball.metres)
    assumptions += _yarn_assumptions(yarn_weight, stitch_pattern, safety_margin_pct)

    return CalcResult(
        result={"metres": round(metres, 1), "balls": balls},
        formula=(
            "metres = (width_cm * height_cm / 100) * m_per_100cm2 * stitch_multiplier "
            "* (gauge/typical_gauge) * (1 + safety_margin); balls = ceil(metres / ball_metres)"
        ),
        inputs={
            "width_cm": width_cm,
            "height_cm": height_cm,
            "weight": yarn_weight.key,
            "stitch": stitch_pattern.key,
            "gauge_sts_10cm": gauge_sts_10cm,
            "ball_metres": yarn_weight.ball.metres,
            "ball_grams": yarn_weight.ball.grams,
            "typical_gauge": yarn_weight.typical_gauge,
            "m_per_100cm2": yarn_weight.m_per_100cm2,
            "stitch_multiplier": stitch_pattern.multiplier,
            "safety_margin_pct": safety_margin_pct,
        },
        assumptions=assumptions,
        source="cyc_weights + internal (m_per_100cm2, stitch multiplier, safety margin)",
    )


# --- Calculator 2: which needle size ------------------------------------------------


def needle_recommendation(
    weight: str,
    fabric: str | None = None,
    project: str | None = None,
) -> CalcResult:
    """Which needle size to use for a yarn weight, fabric feel and project.

    target_mm = min + fabric_position*(max-min) + project_nudge_mm, snapped to the
    nearest table row. Constants: domain.yaml; sources: DECISIONS.md §3.
    Raises ValueError for an unknown weight, fabric or project.
    """
    yarn_weight = DOMAIN.weight_by_alias(weight)
    recommender = DOMAIN.needle_recommender

    assumptions: list[str] = []
    if fabric is None:
        fabric = recommender.default_fabric
        assumptions.append(f"No fabric preference given; assumed '{fabric}'.")
    if fabric not in recommender.fabric.model_dump():
        raise ValueError(f"unknown fabric preference: {fabric!r}")

    if project is None:
        project_type = DOMAIN.project_by_alias(recommender.default_project)
        assumptions.append(f"No project given; assumed '{project_type.key}'.")
    else:
        project_type = DOMAIN.project_by_alias(project)

    range_min_mm, range_max_mm = yarn_weight.needle_mm
    target_mm = _target_needle_mm(yarn_weight, fabric, project_type)
    needle = needle_row_for(target_mm, "mm")
    assumptions += _needle_assumptions(target_mm, needle, project_type)

    return CalcResult(
        result={
            "metric_mm": needle.row.mm,
            "us": needle.row.us,
            "uk": needle.row.uk,
            "range_min_mm": range_min_mm,
            "range_max_mm": range_max_mm,
        },
        formula="target_mm = range_min + fabric_position*(range_max-range_min) + project_nudge_mm; snap to nearest table row",
        inputs={
            "weight": yarn_weight.key,
            "fabric": fabric,
            "project": project_type.key,
            "target_mm": round(target_mm, 2),
        },
        assumptions=assumptions,
        source="cyc_weights (needle_mm range) + internal (fabric position, project nudge)",
    )


# --- Calculator 3: why is my gauge off ----------------------------------------------


def tension_diagnosis(actual_sts_10cm: float, target_sts_10cm: float) -> CalcResult:
    """Compare a knitter's gauge with the pattern's and say how to fix it.

    diff_pct = (actual-target)/target; actual>target => too tight => size up;
    actual<target => too loose => size down. Constants: domain.yaml; sources: DECISIONS.md §3.
    Raises ValueError when either gauge is outside the plausible range.
    """
    _check_gauge("actual_sts_10cm", actual_sts_10cm)
    _check_gauge("target_sts_10cm", target_sts_10cm)
    tension = DOMAIN.tension

    diff_pct = (actual_sts_10cm - target_sts_10cm) / target_sts_10cm
    diagnosis, direction = _diagnosis_and_direction(diff_pct)
    stitch_difference = abs(actual_sts_10cm - target_sts_10cm)
    suggested_change_mm = round(stitch_difference * tension.mm_per_stitch, 2)
    if direction == "none":
        suggested_change_mm = 0.0

    stitches_per_needle_size = tension.sts_per_needle_size.value
    assumptions = [
        f"One needle size (~{tension.mm_per_stitch}mm) is assumed to change gauge by about "
        f"{stitches_per_needle_size:g} stitch per 10cm; individual tension varies."
    ]

    return CalcResult(
        result={
            "diagnosis": diagnosis,
            "direction": direction,
            "severity": _severity(abs(diff_pct)),
            "diff_pct": round(diff_pct * 100, 1),
            "suggested_needle_change_mm": suggested_change_mm,
            "fixes": _suggested_fixes(abs(diff_pct)),
        },
        formula="diff_pct = (actual_sts - target_sts) / target_sts; needle_change_mm = |actual-target| * mm_per_stitch",
        inputs={
            "actual_sts_10cm": actual_sts_10cm,
            "target_sts_10cm": target_sts_10cm,
            "mm_per_stitch": tension.mm_per_stitch,
            "stitches_per_needle_size": stitches_per_needle_size,
        },
        assumptions=assumptions,
        source="internal (tension heuristic)",
    )


# --- Input checks -------------------------------------------------------------------


def _check_dimension(name: str, value: float) -> None:
    """Reject a width or height that is zero, negative or implausibly large."""
    limit = DOMAIN.limits.max_dimension_cm
    if not 0 < value <= limit:
        raise ValueError(f"{name} must be between 0 and {limit:g} cm, got {value:g}")


def _check_gauge(name: str, value: float) -> None:
    """Reject a gauge (stitches per 10cm) outside the plausible range in domain.yaml."""
    lowest = DOMAIN.limits.min_gauge_sts_10cm
    highest = DOMAIN.limits.max_gauge_sts_10cm
    if not lowest <= value <= highest:
        raise ValueError(
            f"{name} must be between {lowest:g} and {highest:g} stitches per 10cm, got {value:g}"
        )


# --- Yarn quantity steps ------------------------------------------------------------


def _metres_of_yarn(
    area_cm2: float,
    yarn_weight: Weight,
    stitch_pattern: StitchItem,
    gauge_factor: float,
    safety_margin: float,
) -> float:
    """Area in units of 100 sq cm, times metres per unit, adjusted for stitch, gauge and margin."""
    return (
        area_cm2
        / 100.0
        * yarn_weight.m_per_100cm2
        * stitch_pattern.multiplier
        * gauge_factor
        * (1 + safety_margin)
    )


def _yarn_assumptions(
    yarn_weight: Weight, stitch_pattern: StitchItem, safety_margin_pct: int
) -> list[str]:
    """The assumptions behind a yarn estimate, in the order the reply lists them."""
    assumptions: list[str] = []
    if yarn_weight.approximation:
        assumptions.append(
            f"{yarn_weight.name} yardage ({yarn_weight.m_per_100cm2} m per 100 sq cm of stockinette) "
            "is an approximation, calibrated against published patterns."
        )
    if stitch_pattern.multiplier != 1.0:
        assumptions.append(
            f"{stitch_pattern.key} stitch uses ~{stitch_pattern.multiplier}x the yarn of "
            "stockinette (approximation)."
        )
    assumptions.append(f"{safety_margin_pct}% safety margin included for swatching/dye lots.")
    # ASSUMPTION: a standard put-up for this weight. A knitter holding 100 g balls needs half
    # as many, so the ball size is stated and can be overridden.
    assumptions.append(
        f"Ball count assumes a {yarn_weight.ball.grams:g} g ball of {yarn_weight.ball.metres:g} m; "
        "tell me your ball's length for an exact count."
    )
    return assumptions


# --- Needle recommendation steps ----------------------------------------------------


def _target_needle_mm(yarn_weight: Weight, fabric: str, project_type: ProjectNudge) -> float:
    """Pick a point in the weight's needle range by fabric feel, then nudge it for the project."""
    range_min_mm, range_max_mm = yarn_weight.needle_mm
    fabric_position = getattr(DOMAIN.needle_recommender.fabric, fabric)
    target_mm = range_min_mm + fabric_position * (range_max_mm - range_min_mm) + project_type.nudge_mm
    # The project nudge must not push the needle outside the weight's CYC range.
    return min(max(target_mm, range_min_mm), range_max_mm)


def _needle_assumptions(
    target_mm: float, needle: NeedleMatch, project_type: ProjectNudge
) -> list[str]:
    """Say when the size was rounded to a real needle, and why the project moved it."""
    assumptions: list[str] = []
    if not needle.exact:
        assumptions.append(
            f"Target {target_mm:.2f}mm has no exact needle size; rounded to the nearest one."
        )
    if project_type.nudge_mm != 0:
        assumptions.append(project_type.note)
    return assumptions


# --- Tension diagnosis steps --------------------------------------------------------


def _diagnosis_and_direction(diff_pct: float) -> tuple[str, str]:
    """More stitches than the pattern means tight knitting (go up a size); fewer means loose."""
    if diff_pct > 0:
        return "too tight", "up"
    if diff_pct < 0:
        return "too loose", "down"
    return "on gauge", "none"


def _severity(abs_diff_pct: float) -> str:
    """Grade the size of the gauge difference using the thresholds in domain.yaml."""
    thresholds = DOMAIN.tension.severity
    if abs_diff_pct < thresholds.minor_below:
        return "minor"
    if abs_diff_pct < thresholds.moderate_below:
        return "moderate"
    return "major"


def _suggested_fixes(abs_diff_pct: float) -> list[str]:
    """The configured fixes; a yarn substitution is only suggested for a large difference."""
    fixes = list(DOMAIN.tension.fixes)
    if abs_diff_pct <= DOMAIN.tension.substitution_above:
        fixes = [fix for fix in fixes if fix != "consider_yarn_substitution"]
    return fixes


# --- Value helpers ------------------------------------------------------------------


def _as_number(value: Any) -> float | None:
    """The value as a float, or None when it is not a number.

    Numeric strings count: needle sizes (US/UK) are strings ("8", "10.5", "000")
    because some rows have no size in a given system. Booleans do not count.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None
