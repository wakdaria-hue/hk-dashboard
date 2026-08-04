"""Bridge the raw per-shift-row `shifts` table (hk_dashboard.aggregations.
load_all_hotel_shifts) into one logical record per (hotel, date, employee) -
what the confirmation feature shows/compares against, everywhere.

Kept separate from aggregations.py, which is payroll-cost-focused (rate
lookups, monthly gating) - this only ever needs raw hours, never a cost.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd


@dataclass
class DailyReceptionHours:
    hotel: str
    date: date
    employee: str
    hours: float
    display_range: str  # e.g. "14:00-18:00, 19:00-22:00"


def daily_reception_hours(shifts: pd.DataFrame) -> pd.DataFrame:
    """Group shifts by (hotel, date, employee): sum hours, join each shift's
    start-end range with ", " (handles the rare split-shift day).

    Returns columns: hotel, date, employee, hours, display_range.
    """
    if shifts.empty:
        return pd.DataFrame(columns=["hotel", "date", "employee", "hours", "display_range"])

    df = shifts.copy()
    df["range"] = df["start"].fillna("") + "-" + df["end"].fillna("")

    grouped = df.groupby(["hotel", "date", "employee"], as_index=False).agg(
        hours=("hours", "sum"),
        display_range=("range", lambda s: ", ".join(sorted(s))),
    )
    return grouped


def reception_hours_for(
    shifts: pd.DataFrame, hotel: str, employee: str, date_: date
) -> DailyReceptionHours | None:
    """Single (hotel, employee, date) lookup for the confirm-app wizard."""
    daily = daily_reception_hours(shifts)
    if daily.empty:
        return None
    match = daily[
        (daily["hotel"] == hotel) & (daily["employee"] == employee) & (daily["date"] == date_)
    ]
    if match.empty:
        return None
    row = match.iloc[0]
    return DailyReceptionHours(
        hotel=row["hotel"],
        date=row["date"],
        employee=row["employee"],
        hours=float(row["hours"]),
        display_range=row["display_range"],
    )
