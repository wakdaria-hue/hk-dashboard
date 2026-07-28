"""Monday-start weeks, numbered 1-5, restarting at the start of each month.

Week 1 is always the Monday-Sunday week containing the 1st of the month, even
if that week began in the previous month (only days that fall within the
target month are counted). The first and/or last week of a month can
therefore be partial - callers should always show the date-range label
alongside the week number rather than implying a full 7-day week.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class WeekInfo:
    year: int
    month: int
    week_number: int  # 1-based, restarts each month
    range_start: date  # clipped to the month
    range_end: date  # clipped to the month

    @property
    def label(self) -> str:
        return f"Week {self.week_number} ({self.range_start:%d %b} - {self.range_end:%d %b})"


def _monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def week_info_for_date(d: date) -> WeekInfo:
    first_of_month = d.replace(day=1)
    first_monday = _monday_of(first_of_month)
    this_monday = _monday_of(d)
    week_number = ((this_monday - first_monday).days // 7) + 1

    # last day of month
    if d.month == 12:
        next_month_first = date(d.year + 1, 1, 1)
    else:
        next_month_first = date(d.year, d.month + 1, 1)
    last_of_month = next_month_first - timedelta(days=1)

    range_start = max(this_monday, first_of_month)
    range_end = min(this_monday + timedelta(days=6), last_of_month)

    return WeekInfo(
        year=d.year,
        month=d.month,
        week_number=week_number,
        range_start=range_start,
        range_end=range_end,
    )


def add_week_columns(df, date_col: str = "date"):
    """Add week_number and week_label columns to a DataFrame in a place-safe way.

    Deliberately does NOT write a "year" or "month" column: callers (see
    aggregations.load_all_hotel_shifts) already derive a "month" column as a
    "YYYY-MM" string from the same date, which the rate store and every
    aggregation join on - overwriting it here with a plain 1-12 integer would
    silently break those joins.
    """
    infos = df[date_col].apply(week_info_for_date)
    df = df.copy()
    df["week_number"] = infos.apply(lambda w: w.week_number)
    df["week_label"] = infos.apply(lambda w: w.label)
    return df
