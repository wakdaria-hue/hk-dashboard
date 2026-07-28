"""Combine parsed HK shifts with payroll rates into the dashboard's views.

Cost is left as NaN (never guessed/defaulted) whenever a housekeeper's hours
for a given month have no matching rate in the rate store - callers should
render that as "no rate available" rather than a number.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from hk_dashboard.config import HOTEL_SHEETS
from hk_dashboard.hk_parser import UnmappedName, parse_hotel_sheet
from hk_dashboard.rate_store import get_rate
from hk_dashboard.sheets_client import SheetAccessError, fetch_hotel_sheet_raw
from hk_dashboard.weeks import add_week_columns


@dataclass
class LoadResult:
    shifts: pd.DataFrame
    coverage: dict[str, dict] = field(default_factory=dict)  # hotel -> {max_date, error, rows}
    unmapped_names: list[UnmappedName] = field(default_factory=list)


def load_all_hotel_shifts() -> LoadResult:
    all_frames = []
    coverage: dict[str, dict] = {}
    unmapped: list[UnmappedName] = []

    for hotel, sheet_id in HOTEL_SHEETS.items():
        try:
            formatted, unformatted = fetch_hotel_sheet_raw(sheet_id)
        except SheetAccessError as e:
            coverage[hotel] = {"max_date": None, "error": str(e), "rows": 0}
            continue

        df, hotel_unmapped = parse_hotel_sheet(hotel, formatted, unformatted)
        unmapped.extend(hotel_unmapped)

        if df.empty:
            coverage[hotel] = {"max_date": None, "error": None, "rows": 0}
            continue

        all_frames.append(df)
        coverage[hotel] = {"max_date": df["date"].max(), "error": None, "rows": len(df)}

    shifts = (
        pd.concat(all_frames, ignore_index=True)
        if all_frames
        else pd.DataFrame(columns=["hotel", "date", "raw_name", "employee", "name_flagged", "start", "end", "hours"])
    )
    if not shifts.empty:
        shifts["month"] = shifts["date"].apply(lambda d: f"{d.year:04d}-{d.month:02d}")
        shifts = add_week_columns(shifts, "date")

    return LoadResult(shifts=shifts, coverage=coverage, unmapped_names=unmapped)


def attach_costs(shifts: pd.DataFrame, rates_df: pd.DataFrame) -> pd.DataFrame:
    if shifts.empty:
        return shifts.assign(hourly_rate_eur=pd.Series(dtype=float), cost_eur=pd.Series(dtype=float))

    df = shifts.copy()
    df["hourly_rate_eur"] = df.apply(
        lambda r: get_rate(rates_df, r["employee"], r["month"]), axis=1
    )
    df["cost_eur"] = df["hours"] * df["hourly_rate_eur"]
    df["rate_missing"] = df["hourly_rate_eur"].isna()
    return df


def by_hotel_month(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    g = df.groupby(["hotel", "month"], as_index=False).agg(
        hours=("hours", "sum"),
        cost_eur=("cost_eur", lambda s: s.sum(min_count=1)),
        hours_without_rate=("hours", lambda s: s[df.loc[s.index, "rate_missing"]].sum()),
    )
    return g.sort_values(["hotel", "month"])


def by_week(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    g = df.groupby(["hotel", "month", "week_number", "week_label"], as_index=False).agg(
        hours=("hours", "sum"),
        cost_eur=("cost_eur", lambda s: s.sum(min_count=1)),
        hours_without_rate=("hours", lambda s: s[df.loc[s.index, "rate_missing"]].sum()),
    )
    return g.sort_values(["month", "week_number", "hotel"])


def by_housekeeper(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    g = df.groupby(["employee", "hotel", "month"], as_index=False).agg(
        hours=("hours", "sum"),
        days_worked=("date", "nunique"),
        hourly_rate_eur=("hourly_rate_eur", "first"),
        cost_eur=("cost_eur", lambda s: s.sum(min_count=1)),
        rate_missing=("rate_missing", "any"),
    )
    g["avg_hours_per_day"] = (g["hours"] / g["days_worked"]).round(2)
    return g.sort_values(["employee", "month", "hotel"])


def daily_person_matrix(df: pd.DataFrame, month: str, value: str = "cost_eur") -> pd.DataFrame:
    """Pivot: rows=employee, columns=date, values=cost_eur (or 'hours'), for one month ('YYYY-MM')."""
    if df.empty:
        return pd.DataFrame()
    month_df = df[df["month"] == month]
    if month_df.empty:
        return pd.DataFrame()
    pivot = month_df.pivot_table(
        index="employee", columns="date", values=value, aggfunc="sum", fill_value=0
    )
    pivot.columns = [c.isoformat() for c in pivot.columns]
    return pivot


def trend_by_month(df: pd.DataFrame, hotel: str | None = None, employee: str | None = None) -> pd.DataFrame:
    if df.empty:
        return df
    filtered = df
    if hotel:
        filtered = filtered[filtered["hotel"] == hotel]
    if employee:
        filtered = filtered[filtered["employee"] == employee]
    if filtered.empty:
        return filtered
    g = filtered.groupby("month", as_index=False).agg(
        hours=("hours", "sum"),
        cost_eur=("cost_eur", lambda s: s.sum(min_count=1)),
    )
    return g.sort_values("month")
