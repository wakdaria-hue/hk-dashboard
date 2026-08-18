"""Resolve raw schedule names against employee_access, and roll parsed shift
records up into a per-person monthly summary."""
from __future__ import annotations

import calendar
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

import pandas as pd

from mh_dashboard.config import SHIFT_HOURS
from mh_dashboard.parser import ShiftRecord, UnmappedName


@dataclass
class ResolvedShift:
    date: date
    shift_label: str
    full_name: str


@dataclass
class PersonMonth:
    full_name: str
    shift_count: int
    total_hours: float
    dates_worked: list[date]


def resolve_shifts(
    records: list[ShiftRecord], employee_access_df: pd.DataFrame, month_tab: str
) -> tuple[list[ResolvedShift], list[UnmappedName]]:
    """Look up each record's raw_name in employee_access (schedule_name
    column, case-insensitive exact match). Unresolved names are never
    guessed at or silently dropped from consideration - they come back as a
    separate list so the caller can log them to mapping_issues; they're just
    excluded from every person's totals since there's no one to attribute
    them to yet.
    """
    if employee_access_df.empty:
        lookup: dict[str, str] = {}
    else:
        lookup = {
            str(row["schedule_name"]).strip().lower(): str(row["full_name"]).strip()
            for _, row in employee_access_df.iterrows()
            if str(row["schedule_name"]).strip()
        }

    resolved: list[ResolvedShift] = []
    unmapped: list[UnmappedName] = []
    seen_unmapped: set[str] = set()
    for record in records:
        full_name = lookup.get(record.raw_name.lower())
        if full_name is None:
            if record.raw_name.lower() not in seen_unmapped:
                unmapped.append(UnmappedName(month_tab=month_tab, raw_name=record.raw_name))
                seen_unmapped.add(record.raw_name.lower())
            continue
        resolved.append(ResolvedShift(date=record.date, shift_label=record.shift_label, full_name=full_name))
    return resolved, unmapped


def monthly_summary(resolved_shifts: list[ResolvedShift]) -> dict[str, PersonMonth]:
    """Per person: total shift *instances* (a double shift on one day counts
    as 2) but a deduplicated list of dates worked (that day still only
    appears once in dates_worked)."""
    shifts_by_person: dict[str, list[ResolvedShift]] = defaultdict(list)
    for shift in resolved_shifts:
        shifts_by_person[shift.full_name].append(shift)

    return {
        full_name: PersonMonth(
            full_name=full_name,
            shift_count=len(shifts),
            total_hours=len(shifts) * SHIFT_HOURS,
            dates_worked=sorted({s.date for s in shifts}),
        )
        for full_name, shifts in shifts_by_person.items()
    }


def weeks_touching_month(year: int, month: int) -> int:
    """Count of distinct Mon-Sun ISO weeks that touch any day of this
    calendar month - the basis for converting a fixed weekly-hours contract
    (FIXED_WEEKLY_HOURS) into a monthly total. Usually 4, sometimes 5,
    depending on where the month's start/end fall relative to Monday."""
    days_in_month = calendar.monthrange(year, month)[1]
    iso_weeks = {date(year, month, day).isocalendar()[:2] for day in range(1, days_in_month + 1)}
    return len(iso_weeks)
