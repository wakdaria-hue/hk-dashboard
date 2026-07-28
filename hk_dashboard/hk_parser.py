"""Parse HK schedule sheet rows into clean shift records.

Handles the documented real-data quirks defensively:
- a literal "[merged]" prefix left over from merged source cells, OR a
  genuinely blank cell where the Sheets API collapsed a merge (forward-fill
  either way)
- duration given as an HTML <span type="duration" hours=.. minutes=..> tag
  (older Drive-export shape), OR as an exact UNFORMATTED_VALUE day-fraction
  (real Sheets API shape), OR as a plain "H:MM:SS" string (fallback, may be
  rounded)
- rows with zero duration are dropped (no shift actually happened)
- names that are nicknames get normalized via NAME_MAP; anything that isn't
  mapped and doesn't already look like "Initials Surname" is flagged, not
  silently dropped, since new employees get added regularly
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

import pandas as pd

from hk_dashboard.config import MONTH_NAMES_NL_EN, NAME_MAP

MERGED_PREFIX_RE = re.compile(r"^\s*\[merged\]\s*", re.IGNORECASE)
DATE_RE = re.compile(r"^\s*(\d{1,2})-([A-Za-z]+)-(\d{4})\s*$")
SPAN_DURATION_RE = re.compile(
    r'hours="(\d+)"\s+minutes="(\d+)"(?:\s+seconds="(\d+)")?', re.IGNORECASE
)
HMS_RE = re.compile(r"^\s*(\d{1,3}):(\d{2})(?::(\d{2}))?\s*$")
INITIALS_SURNAME_RE = re.compile(
    r"^(?:[A-Z]{1,3}\.?\s+){1,2}[A-Z][A-Za-zÀ-ſ'\-]*(?:\s+[A-Z][A-Za-zÀ-ſ'\-]*)*$"
)


@dataclass
class UnmappedName:
    hotel: str
    raw_name: str
    row_date: date | None


def strip_merged(text: str) -> str:
    return MERGED_PREFIX_RE.sub("", text or "").strip()


def parse_date_cell(raw: str) -> date | None:
    cleaned = strip_merged(raw)
    m = DATE_RE.match(cleaned)
    if not m:
        return None
    day, month_name, year = m.groups()
    month = MONTH_NAMES_NL_EN.get(month_name.lower())
    if not month:
        return None
    try:
        return date(int(year), month, int(day))
    except ValueError:
        return None


def parse_duration_hours(formatted_cell: str, unformatted_cell) -> float | None:
    """Return exact shift duration in hours, or None if the cell is unparseable."""
    text = formatted_cell or ""

    span_match = SPAN_DURATION_RE.search(text)
    if span_match:
        h, mi, s = span_match.groups()
        return int(h) + int(mi) / 60 + (int(s) if s else 0) / 3600

    if isinstance(unformatted_cell, (int, float)):
        # Sheets stores durations as a fraction of a 24h day; this is exact,
        # unlike the rounded "4:30:00" formatted text.
        return round(float(unformatted_cell) * 24, 6)

    hms_match = HMS_RE.match(strip_merged(text))
    if hms_match:
        h, mi, s = hms_match.groups()
        return int(h) + int(mi) / 60 + (int(s) if s else 0) / 3600

    return None


def normalize_name(raw_name: str) -> tuple[str, bool]:
    """Return (normalized_name, is_flagged_unmapped)."""
    cleaned = strip_merged(raw_name)
    key = cleaned.lower()
    if key in NAME_MAP:
        return NAME_MAP[key], False
    if INITIALS_SURNAME_RE.match(cleaned):
        return cleaned, False
    return cleaned, True


def parse_hotel_sheet(
    hotel_code: str, formatted_rows: list[list[str]], unformatted_rows: list[list]
) -> tuple[pd.DataFrame, list[UnmappedName]]:
    """Parse one hotel's raw sheet grid into a shifts DataFrame.

    Assumes columns, in order: date, name, start time, end time, duration.
    A header row (or any row that isn't a real shift row) is skipped
    automatically because its date cell won't parse.
    """
    records = []
    unmapped: list[UnmappedName] = []
    last_date: date | None = None

    for f_row, u_row in zip(formatted_rows, unformatted_rows):
        if len(f_row) < 5:
            continue
        date_cell, name_cell, start_cell, end_cell, duration_cell = f_row[:5]
        duration_unformatted = u_row[4] if len(u_row) > 4 else None

        parsed_date = parse_date_cell(date_cell)
        if parsed_date is not None:
            last_date = parsed_date
        elif strip_merged(date_cell) == "" and last_date is not None:
            parsed_date = last_date
        else:
            # Neither a parseable date nor a blank/merged continuation ->
            # this is a header row, a blank separator row, or junk. Skip it.
            continue

        raw_name = strip_merged(name_cell)
        if not raw_name:
            continue

        hours = parse_duration_hours(duration_cell, duration_unformatted)
        if hours is None or hours <= 0:
            continue

        employee, flagged = normalize_name(raw_name)
        if flagged:
            unmapped.append(UnmappedName(hotel=hotel_code, raw_name=raw_name, row_date=parsed_date))

        records.append(
            {
                "hotel": hotel_code,
                "date": parsed_date,
                "raw_name": raw_name,
                "employee": employee,
                "name_flagged": flagged,
                "start": strip_merged(start_cell),
                "end": strip_merged(end_cell),
                "hours": hours,
            }
        )

    df = pd.DataFrame.from_records(
        records,
        columns=["hotel", "date", "raw_name", "employee", "name_flagged", "start", "end", "hours"],
    )
    return df, unmapped
