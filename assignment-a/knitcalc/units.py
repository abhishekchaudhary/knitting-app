"""Unit conversions: centimetres <-> inches, and needle sizes between mm, US and UK.

Needle sizes come from the table in domain.yaml (DOMAIN.needles.rows), one row per
size with its metric, US and UK label. Some rows have no US or UK size, so a lookup
says whether it found an exact match. No constant here is a literal: the numbers
all come from domain.yaml.

Example:
    convert_needle(4.0, "mm", "us").row.us -> "6"
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from knitcalc.domain import DOMAIN, NeedleRow

# The three needle sizing systems, named as the columns of the needle table.
System = Literal["mm", "us", "uk"]


def cm_to_in(cm: float) -> float:
    """Centimetres to inches."""
    return cm / DOMAIN.units.cm_per_inch


def in_to_cm(inches: float) -> float:
    """Inches to centimetres."""
    return inches * DOMAIN.units.cm_per_inch


@dataclass(frozen=True)
class NeedleMatch:
    """A needle table row found by a lookup, and whether it matched exactly."""

    row: NeedleRow
    exact: bool  # False when the requested system had no size at this row and we snapped to nearest


def needle_row_for(value: float | str, system: System) -> NeedleMatch:
    """Find the needle table row matching `value` in `system` (mm/us/uk).

    mm lookups match the nearest row by absolute distance (mm is continuous).
    us/uk lookups match the row whose column equals the given label exactly and
    raise ValueError when no row carries that label (see the comment below);
    convert_needle() is the one that snaps and reports exact=False.
    """
    rows = DOMAIN.needles.rows
    if system == "mm":
        return _nearest_row_by_mm(float(value))

    label = str(value).strip()
    for row in rows:
        if _size_in_system(row, system) == label:
            return NeedleMatch(row=row, exact=True)

    # No row carries this label in this system (e.g. a US size with no UK equivalent).
    # "Nearest" only makes sense in mm, and the US and UK scales do not run in the same
    # direction, so there is no safe way to snap. A caller that wants an approximate
    # answer looks the size up by mm, or uses convert_needle(), which snaps and says so.
    raise ValueError(f"no needle row has {system}={value!r}")


def convert_needle(value: float | str, from_system: System, to_system: System) -> NeedleMatch:
    """Convert a needle size between mm/us/uk.

    Round-trips exactly for mm->system->mm when the row has both columns.
    When the target system has no entry at that row, the nearest mm row that
    *does* is returned with `exact=False`.
    """
    match = needle_row_for(value, from_system)
    if _size_in_system(match.row, to_system) is not None:
        return NeedleMatch(row=match.row, exact=match.exact)

    closest_row = _closest_row_with_size_in(to_system, match.row)
    if closest_row is None:
        raise ValueError(f"no needle row has a {to_system} size at all")
    return NeedleMatch(row=closest_row, exact=False)


# --- Helpers -------------------------------------------------------------------------


def _size_in_system(row: NeedleRow, system: System) -> Optional[str] | float:
    """The row's size in one system: a float for mm, a label (or None) for us/uk."""
    return getattr(row, system)


def _nearest_row_by_mm(target_mm: float) -> NeedleMatch:
    """The row closest to target_mm; exact only when a row has exactly that size.

    On a tie the smaller needle (earlier row) wins.
    """
    rows = DOMAIN.needles.rows
    nearest = min(rows, key=lambda row: abs(row.mm - target_mm))
    exact = any(row.mm == target_mm for row in rows)
    return NeedleMatch(row=nearest, exact=exact)


def _closest_row_with_size_in(system: System, start_row: NeedleRow) -> Optional[NeedleRow]:
    """The row nearest to start_row (counting rows) that has a size in `system`.

    On a tie the earlier (smaller) row wins. None when no row has a size in `system`.
    """
    rows = DOMAIN.needles.rows
    start_position = rows.index(start_row)
    closest_row: Optional[NeedleRow] = None
    closest_distance: Optional[int] = None
    for row in rows:
        if _size_in_system(row, system) is None:
            continue
        distance = abs(rows.index(row) - start_position)
        if closest_distance is None or distance < closest_distance:
            closest_row = row
            closest_distance = distance
    return closest_row
