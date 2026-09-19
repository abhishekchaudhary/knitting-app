"""Load and validate domain.yaml: the single home of every knitting constant.

Each section of domain.yaml has a pydantic model below, and every field name is the
YAML key. The file is read and checked once, at import, into the DOMAIN object, so a
typo or a bad value fails before any calculation runs. Calculators read constants
from DOMAIN; nothing is hard-coded elsewhere.

Example:
    DOMAIN.weight_by_alias("DK").key   -> "light"
    DOMAIN.stitch_by_alias("moss").key -> "seed"
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Iterable, Optional, TypeVar, Union

import yaml
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

DOMAIN_YAML_PATH = Path(__file__).parent / "domain.yaml"


class StrictModel(BaseModel):
    """Every domain model forbids unknown keys, so a typo in domain.yaml fails at
    import time with the key named, instead of as a KeyError mid-answer."""

    model_config = ConfigDict(extra="forbid")


# --- Yarn weights (the CYC table) ---------------------------------------------------


class Ball(StrictModel):
    """A standard ball of yarn for one weight."""

    grams: float
    metres: float


class Weight(StrictModel):
    """One yarn weight: its gauge, needle range, yardage and standard ball."""

    key: str
    cyc: int
    name: str
    aliases: list[str]
    gauge_sts_10cm: tuple[float, float]
    typical_gauge: float
    needle_mm: tuple[float, float]
    us_needle: tuple[Optional[str], Optional[str]]
    m_per_100cm2: float
    ball: Ball
    source: str
    note: str
    approximation: bool = False
    calibrate: Optional[str] = None


# --- Needle size table ----------------------------------------------------------------


class NeedleRow(StrictModel):
    """One needle size in metric, US and UK. US or UK is None where no size exists."""

    mm: float
    us: Optional[str] = None
    uk: Optional[str] = None


class Needles(StrictModel):
    source: list[str]
    note: str
    rows: list[NeedleRow]


# --- Stitch patterns --------------------------------------------------------------------


class StitchItem(StrictModel):
    """One stitch pattern and how much yarn it uses relative to stockinette."""

    key: str
    aliases: list[str]
    multiplier: float
    range: tuple[float, float]
    note: str


class Stitches(StrictModel):
    source: str
    approximation: bool
    calibrate: Optional[str] = None
    note: str
    items: list[StitchItem]


# --- Calculator settings ----------------------------------------------------------------


class YarnQuantityConfig(StrictModel):
    safety_margin: float
    source: str
    approximation: bool
    note: str
    calibrate: Optional[str] = None


class FabricPositions(StrictModel):
    """Where in a weight's needle range each fabric feel sits (0 = smallest, 1 = largest)."""

    firm: float
    balanced: float
    drapey: float


class ProjectNudge(StrictModel):
    """A project type and how far it moves the recommended needle, in mm."""

    key: str
    aliases: list[str]
    nudge_mm: float
    note: str


class NeedleRecommenderConfig(StrictModel):
    source: str
    approximation: bool
    note: str
    calibrate: Optional[str] = None
    fabric: FabricPositions
    default_fabric: str
    projects: list[ProjectNudge]
    default_project: str


class Severity(StrictModel):
    """Thresholds on |diff| / target. At or above moderate_below the diagnosis is major."""

    minor_below: float
    moderate_below: float


class Constant(StrictModel):
    """A single tunable number that still has to carry its provenance (a `source` and a `note`)."""

    value: float
    source: str
    note: str


class TensionConfig(StrictModel):
    source: str
    approximation: bool
    note: str
    calibrate: Optional[str] = None
    mm_per_stitch: float
    sts_per_needle_size: Constant
    severity: Severity
    substitution_above: float
    fixes: list[str]


# --- Units, input limits and sources ----------------------------------------------------


class Units(StrictModel):
    cm_per_inch: float
    gauge_width_cm: float
    gauge_width_in: float
    source: str
    note: str


class Limits(StrictModel):
    """The plausible range for user inputs; anything outside is declined."""

    max_dimension_cm: float
    min_gauge_sts_10cm: float
    max_gauge_sts_10cm: float
    source: str
    note: str


class Source(StrictModel):
    """A citable source for the constants that name it."""

    title: str
    url: Optional[str] = None
    checked: Optional[Union[date, str]] = None


# --- The whole file ---------------------------------------------------------------------


class Domain(StrictModel):
    """All of domain.yaml, plus cross-section checks and lookups by alias."""

    version: int
    sources: dict[str, Source]
    units: Units
    limits: Limits
    weights: list[Weight]
    needles: Needles
    stitches: Stitches
    yarn_quantity: YarnQuantityConfig
    needle_recommender: NeedleRecommenderConfig
    tension: TensionConfig

    # Checks run in the order written; each raises ValueError, which pydantic reports
    # as a ValidationError naming the problem.

    @field_validator("weights")
    @classmethod
    def _weight_aliases_unique(cls, weights: list[Weight]) -> list[Weight]:
        _reject_duplicate_aliases(weights, "weight")
        return weights

    @model_validator(mode="after")
    def _needle_rows_sorted(self) -> "Domain":
        sizes_mm = [row.mm for row in self.needles.rows]
        if sizes_mm != sorted(sizes_mm):
            raise ValueError("needles.rows must be sorted ascending by mm")
        return self

    @model_validator(mode="after")
    def _weight_needle_bounds_in_table(self) -> "Domain":
        """Every weight's needle range must be inside the needle table, so it can be snapped."""
        table_min = self.needles.rows[0].mm
        table_max = self.needles.rows[-1].mm
        for weight in self.weights:
            range_min_mm, range_max_mm = weight.needle_mm
            if range_min_mm < table_min or range_max_mm > table_max:
                raise ValueError(
                    f"weight {weight.key!r} needle_mm {weight.needle_mm} outside needle table "
                    f"[{table_min}, {table_max}]"
                )
        return self

    @model_validator(mode="after")
    def _stitch_aliases_unique(self) -> "Domain":
        _reject_duplicate_aliases(self.stitches.items, "stitch")
        return self

    @model_validator(mode="after")
    def _defaults_exist(self) -> "Domain":
        """The default fabric and project must be real entries, not typos."""
        recommender = self.needle_recommender
        fabrics = list(recommender.fabric.model_dump())
        if recommender.default_fabric not in fabrics:
            raise ValueError(
                f"default_fabric {recommender.default_fabric!r} is not one of {fabrics}"
            )
        try:
            self.project_by_alias(recommender.default_project)
        except ValueError as exc:
            raise ValueError(
                f"default_project {recommender.default_project!r} is not a project"
            ) from exc
        return self

    @model_validator(mode="after")
    def _project_aliases_unique(self) -> "Domain":
        _reject_duplicate_aliases(self.needle_recommender.projects, "project")
        return self

    # Lookups: match a user's word against each entry's aliases (case-insensitive) or key.

    def weight_by_alias(self, name: str) -> Weight:
        """The yarn weight called `name`, e.g. "DK" -> the 'light' weight. Raises ValueError."""
        weight = _find_by_alias(self.weights, name)
        if weight is None:
            raise ValueError(f"unknown yarn weight: {name!r}")
        return weight

    def stitch_by_alias(self, name: str) -> StitchItem:
        """The stitch pattern called `name`, e.g. "moss" -> 'seed'. Raises ValueError."""
        stitch = _find_by_alias(self.stitches.items, name)
        if stitch is None:
            raise ValueError(f"unknown stitch pattern: {name!r}")
        return stitch

    def project_by_alias(self, name: str) -> ProjectNudge:
        """The project type called `name`, e.g. "scarf". Raises ValueError."""
        project = _find_by_alias(self.needle_recommender.projects, name)
        if project is None:
            raise ValueError(f"unknown project type: {name!r}")
        return project


# --- Alias helpers (used by Domain) -----------------------------------------------------

# Anything with a `key` and a list of `aliases`: Weight, StitchItem or ProjectNudge.
AliasedEntry = TypeVar("AliasedEntry", Weight, StitchItem, ProjectNudge)


def _normalise(alias: str) -> str:
    """Compare aliases ignoring case and surrounding spaces."""
    return alias.strip().lower()


def _find_by_alias(entries: list[AliasedEntry], name: str) -> Optional[AliasedEntry]:
    """The first entry whose aliases include `name`, or whose key equals it; else None."""
    wanted = _normalise(name)
    for entry in entries:
        aliases = [_normalise(alias) for alias in entry.aliases]
        if wanted in aliases or wanted == entry.key:
            return entry
    return None


def _reject_duplicate_aliases(entries: Iterable[AliasedEntry], kind: str) -> None:
    """Raise if two entries share an alias, since a lookup could then pick the wrong one."""
    seen: set[str] = set()
    for entry in entries:
        for alias in entry.aliases:
            normalised = _normalise(alias)
            if normalised in seen:
                raise ValueError(f"duplicate {kind} alias {alias!r}")
            seen.add(normalised)


# --- Loading --------------------------------------------------------------------------


def load_domain(path: Path = DOMAIN_YAML_PATH) -> Domain:
    """Read a domain.yaml file and validate it. Raises pydantic.ValidationError if it is wrong."""
    with open(path, "r", encoding="utf-8") as yaml_file:
        parsed_yaml = yaml.safe_load(yaml_file)
    return Domain.model_validate(parsed_yaml)


# Loaded once at import, so a broken domain.yaml fails immediately.
DOMAIN = load_domain()
