"""How many shifts a forecasted day probably needs - a rough first pass.

Deliberately a swappable module, not logic baked into the forecast page: the
even-split assumption below is the best that can be done with today's data,
and is expected to be replaced once per-room, per-person assignment data
exists. Anything wanting a staffing estimate calls `estimate_shifts()` and
gets back a list of suggested shifts; swap `DEFAULT_ESTIMATOR` (or pass
`estimator=`) to change the method without touching the UI.

Why an estimate can't be more precise yet: on a normal day several
housekeepers work the same rooms and only a daily hours total per person is
recorded, so there's no way to attribute rooms to people. A regression on
VGH's data was already tried and fit near-randomly - too few people repeating
across too few team combinations - so this does not attempt attribution. It
does use one honest signal where it exists: on a solo day, one person
demonstrably cleaned every room, so that hotel's solo minutes-per-room is a
real measure of one person's throughput and is preferred over the team-wide
average, which carries the overhead of several people on shift together.

The result is a count of shifts needed, never named individuals - who works
is a rostering decision this doesn't try to make.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Callable, Protocol

from hk_dashboard.forecast import HotelBaseline

# How far a single shift may run past the hotel's typical length before the
# estimate calls for another person. Without it, a day needing 5.4h against a
# 5.0h typical shift suggests two 2.7h shifts rather than one slightly long
# one - which is not how the day would actually be staffed.
SHIFT_LENGTH_TOLERANCE = 1.15


@dataclass
class SuggestedShift:
    hotel: str
    date: date
    hours: float
    basis: str  # "solo-calibrated" or "team-average"


class StaffingEstimator(Protocol):
    def __call__(
        self, predicted_rooms: float, predicted_hours: float, hotel: str, day: date,
        baseline: HotelBaseline,
    ) -> list[SuggestedShift]: ...


def even_split_estimator(
    predicted_rooms: float,
    predicted_hours: float,
    hotel: str,
    day: date,
    baseline: HotelBaseline,
) -> list[SuggestedShift]:
    """Split the day's work into equal shifts of that hotel's typical length.

    Uses solo-day throughput where the hotel has any (one person's real
    minutes-per-room), otherwise falls back to the team-wide average, which
    is what `predicted_hours` was built from.
    """
    shift_length = baseline.typical_shift_hours
    if not shift_length or shift_length <= 0:
        return []

    if baseline.solo_minutes_per_room and predicted_rooms:
        person_hours = predicted_rooms * baseline.solo_minutes_per_room / 60
        basis = "solo-calibrated"
    else:
        person_hours = predicted_hours
        basis = "team-average"

    if not person_hours or person_hours <= 0:
        return []

    shift_count = max(1, math.ceil(person_hours / (shift_length * SHIFT_LENGTH_TOLERANCE)))
    hours_each = person_hours / shift_count
    return [
        SuggestedShift(hotel=hotel, date=day, hours=hours_each, basis=basis)
        for _ in range(shift_count)
    ]


DEFAULT_ESTIMATOR: Callable[..., list[SuggestedShift]] = even_split_estimator


def estimate_shifts(
    predicted_rooms: float,
    predicted_hours: float,
    hotel: str,
    day: date,
    baseline: HotelBaseline,
    estimator: Callable[..., list[SuggestedShift]] | None = None,
) -> list[SuggestedShift]:
    return (estimator or DEFAULT_ESTIMATOR)(
        predicted_rooms, predicted_hours, hotel, day, baseline
    )


def team_average_shift_count(predicted_hours: float, baseline: HotelBaseline) -> int | None:
    """The unadjusted `predicted_hours / typical shift length` headcount.

    Shown alongside a solo-calibrated estimate so the difference between the
    two bases is visible rather than hidden inside one number.
    """
    if not predicted_hours or not baseline.typical_shift_hours:
        return None
    return max(
        1,
        math.ceil(predicted_hours / (baseline.typical_shift_hours * SHIFT_LENGTH_TOLERANCE)),
    )
