"""Golden time: what a day's assigned rooms *should* take, versus what it did.

Three things live here:

1. `assignment_comparison()` - per housekeeper per day. Joins logged room
   assignments to logged hours with an OUTER join on (hotel, date, employee),
   deliberately: a day where one side exists and the other doesn't is the
   finding, not a row to drop. Both directions are flagged -
   "No hours logged" (assigned rooms, no time recorded - someone covered
   rooms without logging) and "No assignment logged" (time recorded, no
   message entered yet).

2. Rollups - week and month averages per person. A single day's variance is
   noisy (a hard day, a slow-forming standard, an unusual room mix), so the
   UI leads with these and keeps day-level detail secondary.

3. `golden_line()` - the same maths at hotel and portfolio level: what the
   period would have cost if everyone hit the target. Room counts come from
   logged assignments where they exist and Mews rooms-to-clean otherwise,
   since assignment logging is incomplete by nature and Mews covers every
   day.

On the two averages: `golden_avg_min_per_room` is compared against the flat
`actual_avg_min_per_room` on purpose. Two people at the same flat minutes per
room can sit at very different distances from target if their check-out /
stay-over mix differs, because a check-out room is allowed twice the time of
a stay-over. The variance against target is the number that means something;
the flat average alone is not a ranking.
"""
from __future__ import annotations

import pandas as pd

from hk_dashboard.reception_hours import daily_reception_hours
from hk_dashboard.settings_store import GoldenSettings, golden_settings_for
from hk_dashboard.weeks import add_week_columns

FLAG_NO_HOURS = "No hours logged"
FLAG_NO_ASSIGNMENT = "No assignment logged"

COMPARISON_COLUMNS = [
    "hotel", "date", "month", "week_number", "week_label", "employee",
    "checkout_count", "stayover_count", "rooms_assigned",
    "checkout_rooms", "stayover_rooms",
    "golden_minutes", "golden_avg_min_per_room",
    "hours_logged", "actual_minutes", "actual_room_minutes",
    "actual_avg_min_per_room", "variance_minutes", "variance_pct",
    "extra_tasks_minutes", "flag", "notes",
]


def assignment_comparison(
    assignments: pd.DataFrame,
    shifts: pd.DataFrame,
    settings_df: pd.DataFrame,
) -> pd.DataFrame:
    """One row per (hotel, date, employee) present in either source."""
    if assignments.empty and shifts.empty:
        return pd.DataFrame(columns=COMPARISON_COLUMNS)

    hours = daily_reception_hours(shifts)
    assignment_cols = [
        "hotel", "date", "employee", "checkout_count", "stayover_count",
        "checkout_rooms", "stayover_rooms", "notes",
    ]
    left = (
        assignments[assignment_cols].copy()
        if not assignments.empty
        else pd.DataFrame(columns=assignment_cols)
    )
    right = (
        hours[["hotel", "date", "employee", "hours"]].copy()
        if not hours.empty
        else pd.DataFrame(columns=["hotel", "date", "employee", "hours"])
    )

    # Named indicator, not the default "_merge": itertuples() below renames
    # any leading-underscore column to a positional placeholder.
    # Only compare hours against the span each hotel actually has assignment
    # logging for. Without this, every shift ever worked before logging began
    # comes back flagged "No assignment logged" - thousands of rows that say
    # nothing except that this feature is new, burying the handful of real
    # gaps inside the logged period.
    if left.empty:
        right = right.iloc[0:0]
    else:
        spans = left.groupby("hotel")["date"].agg(logged_from="min", logged_to="max").reset_index()
        right = right.merge(spans, on="hotel", how="inner")
        right = right[
            (right["date"] >= right["logged_from"]) & (right["date"] <= right["logged_to"])
        ].drop(columns=["logged_from", "logged_to"])

    merged = left.merge(
        right, on=["hotel", "date", "employee"], how="outer", indicator="present_in"
    )
    if merged.empty:
        return pd.DataFrame(columns=COMPARISON_COLUMNS)

    records = []
    for row in merged.itertuples(index=False):
        settings = golden_settings_for(settings_df, row.hotel)
        has_assignment = row.present_in in ("left_only", "both")
        has_hours = row.present_in in ("right_only", "both") and pd.notna(row.hours)

        checkout = float(row.checkout_count) if has_assignment and pd.notna(row.checkout_count) else None
        stayover = float(row.stayover_count) if has_assignment and pd.notna(row.stayover_count) else None
        rooms = (checkout + stayover) if has_assignment else None

        golden_minutes = settings.room_minutes(checkout, stayover) if has_assignment else None
        hours_logged = float(row.hours) if has_hours else None
        actual_minutes = hours_logged * 60 if has_hours else None
        # The extras bundle is per person per day, so it comes off the logged
        # time once - what's left is the time that went into rooms.
        actual_room_minutes = (
            actual_minutes - settings.extra_tasks_minutes if has_hours else None
        )

        variance = (
            actual_room_minutes - golden_minutes
            if (actual_room_minutes is not None and golden_minutes is not None)
            else None
        )
        # Guard the divide: an assignment that parsed to zero rooms would
        # otherwise produce an infinite percentage.
        variance_pct = (
            variance / golden_minutes
            if (variance is not None and golden_minutes)
            else None
        )

        if not has_hours:
            flag = FLAG_NO_HOURS
        elif not has_assignment:
            flag = FLAG_NO_ASSIGNMENT
        else:
            flag = ""

        records.append(
            {
                "hotel": row.hotel,
                "date": row.date,
                "employee": row.employee,
                "checkout_count": checkout,
                "stayover_count": stayover,
                "rooms_assigned": rooms,
                "checkout_rooms": getattr(row, "checkout_rooms", "") if has_assignment else "",
                "stayover_rooms": getattr(row, "stayover_rooms", "") if has_assignment else "",
                "golden_minutes": golden_minutes,
                "golden_avg_min_per_room": (golden_minutes / rooms) if (golden_minutes is not None and rooms) else None,
                "hours_logged": hours_logged,
                "actual_minutes": actual_minutes,
                "actual_room_minutes": actual_room_minutes,
                "actual_avg_min_per_room": (actual_room_minutes / rooms) if (actual_room_minutes is not None and rooms) else None,
                "variance_minutes": variance,
                "variance_pct": variance_pct,
                "extra_tasks_minutes": settings.extra_tasks_minutes,
                "flag": flag,
                "notes": getattr(row, "notes", "") if has_assignment else "",
            }
        )

    df = pd.DataFrame.from_records(records)
    df["month"] = df["date"].apply(lambda d: f"{d.year:04d}-{d.month:02d}")
    df = add_week_columns(df, "date")
    return df[COMPARISON_COLUMNS].sort_values(["date", "hotel", "employee"]).reset_index(drop=True)


def _rollup(comparison: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    """Average variance per person over a period.

    Averages the per-day percentages rather than dividing summed minutes, so
    one huge day can't dominate a person's month; days with no comparable
    pair (a flag) contribute to the counts but never to the averages.
    """
    if comparison.empty:
        return comparison
    comparable = comparison[comparison["variance_minutes"].notna()]
    if comparable.empty:
        return pd.DataFrame(columns=[*group_cols, "days", "rooms_assigned"])

    grouped = comparable.groupby(group_cols, as_index=False).agg(
        days=("date", "nunique"),
        rooms_assigned=("rooms_assigned", "sum"),
        golden_minutes=("golden_minutes", "sum"),
        actual_room_minutes=("actual_room_minutes", "sum"),
        avg_variance_minutes=("variance_minutes", "mean"),
        avg_variance_pct=("variance_pct", "mean"),
        golden_avg_min_per_room=("golden_avg_min_per_room", "mean"),
        actual_avg_min_per_room=("actual_avg_min_per_room", "mean"),
    )
    return grouped


def comparison_by_month(comparison: pd.DataFrame) -> pd.DataFrame:
    return _rollup(comparison, ["employee", "hotel", "month"]).sort_values(["month", "employee"])


def comparison_by_week(comparison: pd.DataFrame) -> pd.DataFrame:
    return _rollup(comparison, ["employee", "hotel", "month", "week_number", "week_label"]).sort_values(
        ["month", "week_number", "employee"]
    )


def comparison_by_day(comparison: pd.DataFrame) -> pd.DataFrame:
    return _rollup(comparison, ["employee", "hotel", "date"]).sort_values(["date", "employee"])


def person_pace(comparison: pd.DataFrame, min_days: int) -> pd.DataFrame:
    """Each person's golden-adjusted pace: actual room minutes per room.

    This is the "better data" the Phase 2 staffing estimate was left open for
    - a measured per-person rate with the daily extras bundle already removed,
    rather than a team-wide average that carries the overhead of several
    people being on shift together.
    """
    if comparison.empty:
        return pd.DataFrame(columns=["hotel", "employee", "days", "minutes_per_room"])
    comparable = comparison[
        comparison["actual_room_minutes"].notna() & comparison["rooms_assigned"].notna()
    ]
    if comparable.empty:
        return pd.DataFrame(columns=["hotel", "employee", "days", "minutes_per_room"])

    grouped = comparable.groupby(["hotel", "employee"], as_index=False).agg(
        days=("date", "nunique"),
        room_minutes=("actual_room_minutes", "sum"),
        rooms=("rooms_assigned", "sum"),
    )
    grouped = grouped[(grouped["days"] >= min_days) & (grouped["rooms"] > 0)].copy()
    grouped["minutes_per_room"] = grouped["room_minutes"] / grouped["rooms"]
    return grouped[["hotel", "employee", "days", "minutes_per_room"]]


def hotel_person_pace(comparison: pd.DataFrame, min_days: int) -> dict[str, float]:
    """Median per-person pace per hotel, for the forecast's staffing estimate.

    A future date has no named housekeeper, so the median of that hotel's
    measured people is the closest honest stand-in for "a person's pace"
    there - not any one individual's number.
    """
    paces = person_pace(comparison, min_days)
    if paces.empty:
        return {}
    return paces.groupby("hotel")["minutes_per_room"].median().to_dict()


def golden_line(
    comparison: pd.DataFrame,
    occupancy: pd.DataFrame,
    settings_df: pd.DataFrame,
    blended_rates: dict[str, float],
    headcount_by_hotel_day: dict[tuple[str, object], int] | None = None,
) -> pd.DataFrame:
    """Per hotel per day: the cost if every room hit its golden target.

    Room counts come from logged assignments where a day has them, and from
    Mews (departures = check-outs, stayovers = stay-overs) otherwise - Mews
    carries the same split the golden maths needs, so the fallback is exact
    rather than a proxy. The per-person extras bundle needs a headcount,
    which Mews alone can't give; where one is known it's included and the row
    says so, so an extras-less row is never mistaken for a complete target.
    """
    rows: dict[tuple[str, object], dict] = {}
    headcount_by_hotel_day = headcount_by_hotel_day or {}

    if not occupancy.empty:
        for row in occupancy.itertuples(index=False):
            settings = golden_settings_for(settings_df, row.hotel)
            checkout = float(row.departures) if pd.notna(row.departures) else 0.0
            stayover = float(row.stayovers) if pd.notna(row.stayovers) else 0.0
            rows[(row.hotel, row.date)] = {
                "hotel": row.hotel,
                "date": row.date,
                "checkout_count": checkout,
                "stayover_count": stayover,
                "golden_room_minutes": settings.room_minutes(checkout, stayover),
                "rooms_source": "Mews",
                "extras_minutes": 0.0,
                "extras_basis": "no headcount",
            }

    if not comparison.empty:
        logged = comparison[comparison["rooms_assigned"].notna()]
        if not logged.empty:
            grouped = logged.groupby(["hotel", "date"], as_index=False).agg(
                checkout_count=("checkout_count", "sum"),
                stayover_count=("stayover_count", "sum"),
                golden_room_minutes=("golden_minutes", "sum"),
                people=("employee", "nunique"),
                extras_each=("extra_tasks_minutes", "first"),
            )
            for row in grouped.itertuples(index=False):
                rows[(row.hotel, row.date)] = {
                    "hotel": row.hotel,
                    "date": row.date,
                    "checkout_count": row.checkout_count,
                    "stayover_count": row.stayover_count,
                    "golden_room_minutes": row.golden_room_minutes,
                    "rooms_source": "Logged assignments",
                    "extras_minutes": row.people * row.extras_each,
                    "extras_basis": f"{row.people} logged",
                }

    if not rows:
        return pd.DataFrame(
            columns=["hotel", "date", "month", "week_number", "week_label", "golden_hours",
                     "golden_cost_eur", "rooms_source", "extras_basis"]
        )

    records = []
    for (hotel, day), record in rows.items():
        extras = record["extras_minutes"]
        basis = record["extras_basis"]
        if not extras:
            known = headcount_by_hotel_day.get((hotel, day))
            if known:
                settings = golden_settings_for(settings_df, hotel)
                extras = known * settings.extra_tasks_minutes
                basis = f"{known} estimated"
        golden_minutes = record["golden_room_minutes"] + extras
        golden_hours = golden_minutes / 60
        rate = blended_rates.get(hotel)
        records.append(
            {
                **record,
                "extras_minutes": extras,
                "extras_basis": basis,
                "golden_minutes": golden_minutes,
                "golden_hours": golden_hours,
                "golden_cost_eur": (golden_hours * rate) if rate else None,
            }
        )

    df = pd.DataFrame.from_records(records)
    df["month"] = df["date"].apply(lambda d: f"{d.year:04d}-{d.month:02d}")
    df = add_week_columns(df, "date")
    return df.sort_values(["date", "hotel"]).reset_index(drop=True)


def golden_by_month(golden_df: pd.DataFrame, hotel: str | None = None) -> pd.DataFrame:
    """Portfolio-level unless a hotel is given."""
    if golden_df.empty:
        return golden_df
    scoped = golden_df if hotel is None else golden_df[golden_df["hotel"] == hotel]
    if scoped.empty:
        return scoped
    return scoped.groupby("month", as_index=False).agg(
        golden_hours=("golden_hours", "sum"),
        golden_cost_eur=("golden_cost_eur", lambda s: s.sum(min_count=1)),
    ).sort_values("month")
