"""Phase 2: forecast cleaning hours and cost from uploaded Mews occupancy.

Two steps, kept separate so every forecast number stays traceable to the
historical figure that produced it:

1. `compute_baselines()` - per hotel, from historical actuals only:
   - `minutes_per_room` = HK minutes worked / rooms to clean, both summed over
     the same set of days. Calibrated over **all available history** by
     default rather than a trailing window, so every day that has both hours
     and a room count contributes and the figure keeps improving as history
     accumulates; a shorter window stays selectable for checking whether the
     team's pace has actually shifted. Team-wide by necessity: on most days
     several housekeepers work the same rooms with no record of who cleaned
     which, so there's no honest way to split it per person.
   - Room counts come from Mews occupancy first and logged room assignments
     only as a fallback. That's the opposite priority to the golden line, and
     deliberate: this is a *ratio*, so a day where only some housekeepers'
     assignment messages were logged would undercount rooms and inflate
     minutes-per-room. Mews covers every day of its range by construction.
   - `blended_hourly_rate` = cost / hours over the same window, i.e. weighted
     by hours actually worked rather than averaging the listed rates (a
     part-timer's rate shouldn't count as much as a full-timer's).
   - `solo_minutes_per_room` - the same ratio computed only over days where
     exactly one person worked and therefore demonstrably cleaned every room
     alone. Used for the per-person staffing estimate (see staffing.py), never
     for the cost forecast.

   Both inputs are payroll-gated: only months whose "Overzicht Loonkosten"
   PDF has been uploaded contribute, so the baseline and the rate it's paired
   with always come from the same closed-out months.

2. `build_forecast()` - applies those baselines to future-dated occupancy
   rows. A hotel with no usable baseline produces rows with blank predictions
   and a stated reason, never a guessed number.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

from hk_dashboard.config import TYPICAL_SHIFT_HOURS_FALLBACK
from hk_dashboard.weeks import add_week_columns


@dataclass
class HotelBaseline:
    hotel: str
    window_start: date
    window_end: date
    days_matched: int  # days with BOTH occupancy and payroll-gated hours
    hours_in_window: float
    rooms_in_window: float
    minutes_per_room: float | None
    blended_hourly_rate: float | None
    rated_hours_in_window: float
    unrated_hours_in_window: float
    solo_minutes_per_room: float | None
    solo_day_count: int
    typical_shift_hours: float
    # Measured per-person pace from logged room assignments (median across
    # this hotel's people with enough history), extras already removed. The
    # best of the three person-throughput figures when it exists.
    assignment_minutes_per_room: float | None = None
    note: str | None = None

    @property
    def is_usable(self) -> bool:
        return self.minutes_per_room is not None

    @property
    def unrated_hours_share(self) -> float:
        total = self.rated_hours_in_window + self.unrated_hours_in_window
        return (self.unrated_hours_in_window / total) if total else 0.0


def _window_bounds(today: date, window_days: int | None) -> tuple[date, date]:
    """Window ends yesterday - today is still in progress, so including it
    would divide a partial day's hours by a full day's rooms."""
    window_end = today - timedelta(days=1)
    if window_days is None:
        return date.min, window_end
    return today - timedelta(days=window_days), window_end


def rooms_by_hotel_day(
    occupancy_df: pd.DataFrame, assignments: pd.DataFrame | None = None
) -> pd.DataFrame:
    """Rooms to clean per hotel per day, from Mews first and logged
    assignments only where Mews has no row for that day.

    Mews-first on purpose - see this module's docstring. Returns columns
    hotel, date, rooms_to_clean, rooms_source.
    """
    frames = []
    if occupancy_df is not None and not occupancy_df.empty:
        mews = occupancy_df[["hotel", "date", "rooms_to_clean"]].copy()
        mews["rooms_source"] = "Mews"
        frames.append(mews)

    if assignments is not None and not assignments.empty:
        logged = assignments.groupby(["hotel", "date"], as_index=False).agg(
            rooms_to_clean=("rooms_assigned", "sum")
        )
        logged["rooms_source"] = "Logged assignments"
        frames.append(logged)

    if not frames:
        return pd.DataFrame(columns=["hotel", "date", "rooms_to_clean", "rooms_source"])

    combined = pd.concat(frames, ignore_index=True)
    # Mews rows come first, so keep="first" is what makes Mews win a day both
    # sources cover.
    return combined.drop_duplicates(subset=["hotel", "date"], keep="first").reset_index(drop=True)


def compute_baselines(
    gated_shifts: pd.DataFrame,
    occupancy_df: pd.DataFrame,
    today: date,
    window_days: int | None = None,
    assignments: pd.DataFrame | None = None,
    person_paces: dict[str, float] | None = None,
) -> dict[str, HotelBaseline]:
    """Per-hotel baseline from historical actuals.

    `gated_shifts` is get_dashboard_data()'s payroll-gated shifts (it carries
    hours, hourly_rate_eur, cost_eur and rate_missing); `occupancy_df` is the
    occupancy store; `assignments` (optional) supplies room counts for days
    Mews doesn't cover. `window_days=None` - the default - uses every
    matching historical day rather than ageing older days out.
    """
    window_start, window_end = _window_bounds(today, window_days)
    baselines: dict[str, HotelBaseline] = {}
    person_paces = person_paces or {}

    rooms_df = rooms_by_hotel_day(occupancy_df, assignments)
    if rooms_df.empty:
        return baselines

    past_occupancy = rooms_df[
        (rooms_df["date"] >= window_start) & (rooms_df["date"] <= window_end)
    ]

    for hotel in sorted(rooms_df["hotel"].dropna().unique()):
        hotel_occupancy = past_occupancy[past_occupancy["hotel"] == hotel]
        hotel_shifts = (
            gated_shifts[
                (gated_shifts["hotel"] == hotel)
                & (gated_shifts["date"] >= window_start)
                & (gated_shifts["date"] <= window_end)
            ]
            if not gated_shifts.empty
            else gated_shifts
        )

        # Only days present on BOTH sides can calibrate anything: dividing all
        # of the window's hours by a different set of days' rooms would be
        # quietly wrong whenever one source has a gap.
        matched_days = (
            sorted(set(hotel_occupancy["date"]) & set(hotel_shifts["date"]))
            if not hotel_shifts.empty
            else []
        )

        if not matched_days:
            reason = (
                "no occupancy uploaded for this window"
                if hotel_occupancy.empty
                else (
                    "no hours in this window from a payroll-uploaded month - check the "
                    "sidebar for how far this hotel's schedule sheet runs, and that the "
                    "month's payroll PDF is uploaded"
                )
            )
            baselines[hotel] = HotelBaseline(
                hotel=hotel,
                window_start=window_start,
                window_end=window_end,
                days_matched=0,
                hours_in_window=0.0,
                rooms_in_window=0.0,
                minutes_per_room=None,
                blended_hourly_rate=None,
                rated_hours_in_window=0.0,
                unrated_hours_in_window=0.0,
                solo_minutes_per_room=None,
                solo_day_count=0,
                typical_shift_hours=TYPICAL_SHIFT_HOURS_FALLBACK,
                assignment_minutes_per_room=person_paces.get(hotel),
                note=reason,
            )
            continue

        shifts_in_scope = hotel_shifts[hotel_shifts["date"].isin(matched_days)]
        occupancy_in_scope = hotel_occupancy[hotel_occupancy["date"].isin(matched_days)]

        hours = float(shifts_in_scope["hours"].sum())
        rooms = float(occupancy_in_scope["rooms_to_clean"].sum())

        rated = shifts_in_scope[~shifts_in_scope["rate_missing"]]
        rated_hours = float(rated["hours"].sum())
        rated_cost = float(rated["cost_eur"].sum()) if rated_hours else 0.0
        unrated_hours = float(shifts_in_scope.loc[shifts_in_scope["rate_missing"], "hours"].sum())

        per_person_day = shifts_in_scope.groupby(["date", "employee"])["hours"].sum()
        headcount_by_day = shifts_in_scope.groupby("date")["employee"].nunique()
        solo_days = [d for d, n in headcount_by_day.items() if n == 1]
        solo_hours = float(shifts_in_scope.loc[shifts_in_scope["date"].isin(solo_days), "hours"].sum())
        solo_rooms = float(
            occupancy_in_scope.loc[occupancy_in_scope["date"].isin(solo_days), "rooms_to_clean"].sum()
        )

        baselines[hotel] = HotelBaseline(
            hotel=hotel,
            window_start=min(matched_days),
            window_end=max(matched_days),
            days_matched=len(matched_days),
            hours_in_window=hours,
            rooms_in_window=rooms,
            minutes_per_room=(hours * 60 / rooms) if rooms > 0 else None,
            blended_hourly_rate=(rated_cost / rated_hours) if rated_hours > 0 else None,
            rated_hours_in_window=rated_hours,
            unrated_hours_in_window=unrated_hours,
            solo_minutes_per_room=(solo_hours * 60 / solo_rooms) if solo_rooms > 0 else None,
            solo_day_count=len(solo_days),
            typical_shift_hours=float(per_person_day.median())
            if not per_person_day.empty
            else TYPICAL_SHIFT_HOURS_FALLBACK,
            assignment_minutes_per_room=person_paces.get(hotel),
            note=None if rooms > 0 else "occupancy rows exist but show no rooms to clean",
        )

    return baselines


def build_forecast(
    occupancy_df: pd.DataFrame,
    baselines: dict[str, HotelBaseline],
    today: date,
) -> pd.DataFrame:
    """Per-hotel-per-day forecast for today onward, from uploaded occupancy.

    Every row states its basis. Predicted hours/cost are left blank (never
    defaulted) when the hotel has no usable baseline or no blended rate.
    """
    columns = [
        "hotel", "date", "month", "week_number", "week_label",
        "rooms_to_clean", "predicted_hours", "predicted_cost_eur",
        "minutes_per_room", "blended_hourly_rate", "report_created", "basis",
    ]
    if occupancy_df.empty:
        return pd.DataFrame(columns=columns)

    future = occupancy_df[occupancy_df["date"] >= today].copy()
    if future.empty:
        return pd.DataFrame(columns=columns)

    records = []
    for row in future.itertuples(index=False):
        baseline = baselines.get(row.hotel)
        minutes = baseline.minutes_per_room if baseline else None
        rate = baseline.blended_hourly_rate if baseline else None
        rooms = float(row.rooms_to_clean) if pd.notna(row.rooms_to_clean) else None

        hours = (rooms * minutes / 60) if (rooms is not None and minutes) else None
        cost = (hours * rate) if (hours is not None and rate) else None

        if minutes is None:
            basis = f"no baseline - {baseline.note}" if baseline and baseline.note else "no baseline yet"
        elif rate is None:
            basis = "hours forecast only - no blended rate on file"
        else:
            basis = "Forecasted"

        records.append(
            {
                "hotel": row.hotel,
                "date": row.date,
                "rooms_to_clean": rooms,
                "predicted_hours": hours,
                "predicted_cost_eur": cost,
                "minutes_per_room": minutes,
                "blended_hourly_rate": rate,
                "report_created": getattr(row, "report_created", ""),
                "basis": basis,
            }
        )

    df = pd.DataFrame.from_records(records)
    df["month"] = df["date"].apply(lambda d: f"{d.year:04d}-{d.month:02d}")
    df = add_week_columns(df, "date")
    return df[columns].sort_values(["date", "hotel"]).reset_index(drop=True)


def _aggregate(df: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    if df.empty:
        return df
    grouped = df.groupby(group_cols, as_index=False).agg(
        rooms_to_clean=("rooms_to_clean", lambda s: s.sum(min_count=1)),
        predicted_hours=("predicted_hours", lambda s: s.sum(min_count=1)),
        predicted_cost_eur=("predicted_cost_eur", lambda s: s.sum(min_count=1)),
        days=("date", "nunique"),
    )
    return grouped


def forecast_by_month(df: pd.DataFrame) -> pd.DataFrame:
    return _aggregate(df, ["hotel", "month"]).sort_values(["month", "hotel"])


def forecast_by_week(df: pd.DataFrame, month: str) -> pd.DataFrame:
    scoped = df[df["month"] == month]
    return _aggregate(scoped, ["hotel", "week_number", "week_label"]).sort_values(
        ["week_number", "hotel"]
    )


def forecast_by_day(df: pd.DataFrame, month: str) -> pd.DataFrame:
    scoped = df[df["month"] == month]
    if scoped.empty:
        return scoped
    return _aggregate(scoped, ["hotel", "date"]).sort_values(["date", "hotel"])


def baselines_to_df(baselines: dict[str, HotelBaseline]) -> pd.DataFrame:
    """The assumptions table - what produced every forecast number, so it can
    be sanity-checked each time a new occupancy export is uploaded."""
    return pd.DataFrame(
        [
            {
                "hotel": b.hotel,
                "window": f"{b.window_start:%d %b %Y} - {b.window_end:%d %b %Y}"
                if b.days_matched
                else "-",
                "days_matched": b.days_matched,
                "hours_in_window": b.hours_in_window,
                "rooms_in_window": b.rooms_in_window,
                "minutes_per_room": b.minutes_per_room,
                "blended_hourly_rate": b.blended_hourly_rate,
                "hours_without_rate": b.unrated_hours_in_window,
                "solo_minutes_per_room": b.solo_minutes_per_room,
                "solo_days": b.solo_day_count,
                "assignment_minutes_per_room": b.assignment_minutes_per_room,
                "typical_shift_hours": b.typical_shift_hours,
                "note": b.note or "",
            }
            for b in sorted(baselines.values(), key=lambda x: x.hotel)
        ]
    )
