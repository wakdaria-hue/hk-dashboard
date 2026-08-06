"""Parse the Mobile Host schedule grid into raw shift records.

The schedule is hand-maintained in Google Sheets with no fixed column
layout Daria could guarantee ahead of time (leading blank columns, sidebar
note columns, and an occasional second unlabeled grid all vary row to row -
confirmed against the real August 2026 tab on 2026-08-06). So instead of
hardcoding column indices, every row is scanned for content that identifies
what it is:

- A date-header row is found by its first "<Month> <day>" cell (e.g.
  "August 1"); the 7 cells starting there are that week's Monday-Sunday
  dates. Every date after the first is just "anchor + 1 day", which avoids
  parsing month names for the other 6 cells and makes month/year rollover
  (e.g. "July 27 ... August 2") free.
- A shift row is found by its first cell matching one of the 4 exact shift
  labels; the 7 cells immediately after it are that week's Monday-Sunday
  values.

Taking only the *first* match per row is what makes this naturally ignore
the second, unlabeled grid that sometimes sits further right in the same
row (confirmed with Daria: only the left grid is real data) - without
needing to hardcode where the sidebar/second grid starts.

Validated against live data (via the actual Sheets API, not a text export)
for June-September 2026 on 2026-08-06: zero missing days, zero duplicate
shift-labels-per-day, across all four tabs. Two real quirks that first
validation pass caught, both now handled:
- The sidebar/second-grid region (columns 20+) sometimes contains its own
  stray "<Month> <day>" text (e.g. a right-grid date header bleeding into
  the same physical row as a real left-grid shift row). Without
  MAX_HEADER_COLUMN restricting date-header detection to the left grid's
  own columns, that stray text was mistaken for a real week-header update -
  which, combined with an early `continue`, silently dropped that row's
  real shift data entirely.
- One week's header used abbreviated month names ("3 Aug" instead of
  "August 3") - MONTH_NUMBERS accepts both forms.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

from mh_dashboard.config import DAYS_PER_WEEK_BLOCK, PLACEHOLDER_TOKENS, SHIFT_LABELS

MERGED_PREFIX_RE = re.compile(r"^\s*\[merged\]\s*", re.IGNORECASE)
MONTH_DAY_RE = re.compile(r"^([A-Za-z]+)\s+(\d{1,2})$")
DAY_MONTH_RE = re.compile(r"^(\d{1,2})\s+([A-Za-z]+)$")  # e.g. "3 Aug" - seen for one week in a real tab
TAB_TITLE_RE = re.compile(r"^([A-Za-z]+)\s+(\d{4})$")
TIME_RANGE_RE = re.compile(r"^\d{1,2}([.:]\d{2})?\s*-\s*\d{1,2}([.:]\d{2})?$")

# The real week grid always starts at this column (label at col 5, the 7
# day values/dates at cols 6-12) - confirmed against the live August 2026
# tab. A second, unlabeled block sometimes sits far to the right in the same
# physical row (columns 20+) and occasionally contains its own stray
# "<Month> <day>" text; matches beyond this column are that bleed-through,
# not a real week header, and must be ignored rather than treated as an
# update to the current week.
MAX_HEADER_COLUMN = 10

_MONTH_FULL_NAMES = [
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
]
# Both full ("August") and abbreviated ("Aug") spellings - the real sheet
# uses full names in most week headers but abbreviated ones in at least one
# ("3 Aug" instead of "August 3").
MONTH_NUMBERS = {name: i + 1 for i, name in enumerate(_MONTH_FULL_NAMES)}
MONTH_NUMBERS.update({name[:3]: i + 1 for i, name in enumerate(_MONTH_FULL_NAMES)})


@dataclass
class ShiftRecord:
    date: date
    shift_label: str
    raw_name: str


@dataclass
class UnmappedName:
    month_tab: str
    raw_name: str


def strip_merged(text: str) -> str:
    return MERGED_PREFIX_RE.sub("", text or "").strip()


def parse_tab_title(title: str) -> tuple[int, int] | None:
    """'August 2026' -> (2026, 8), or None if the title isn't a month tab."""
    m = TAB_TITLE_RE.match(title.strip())
    if not m:
        return None
    month = MONTH_NUMBERS.get(m.group(1).lower())
    if month is None:
        return None
    return int(m.group(2)), month


def _row_week_dates(row: list[str], tab_year: int, tab_month: int) -> list[date] | None:
    for i, cell in enumerate(row[: MAX_HEADER_COLUMN + 1]):
        cleaned = strip_merged(cell)
        m = MONTH_DAY_RE.match(cleaned)
        if m:
            month_name, day_str = m.group(1), m.group(2)
        else:
            m = DAY_MONTH_RE.match(cleaned)
            if not m:
                continue
            day_str, month_name = m.group(1), m.group(2)
        month = MONTH_NUMBERS.get(month_name.lower())
        if month is None:
            continue
        day = int(day_str)
        year = tab_year
        if month != tab_month:
            if month == 12 and tab_month == 1:
                year = tab_year - 1
            elif month == 1 and tab_month == 12:
                year = tab_year + 1
        try:
            anchor = date(year, month, day)
        except ValueError:
            continue
        return [anchor + timedelta(days=d) for d in range(DAYS_PER_WEEK_BLOCK)]
    return None


def _row_shift_label(row: list[str]) -> tuple[int, str] | None:
    for i, cell in enumerate(row):
        cleaned = strip_merged(cell)
        if cleaned in SHIFT_LABELS:
            return i, cleaned
    return None


def _looks_like_time_range(text: str) -> bool:
    return bool(TIME_RANGE_RE.match(text))


def parse_month_tab(month_tab: str, rows: list[list[str]]) -> list[ShiftRecord]:
    """Parse one month tab's raw grid into shift records (left grid only).

    Name resolution against employee_access happens separately (see
    mh_dashboard.aggregation.resolve_shifts) - this function only extracts
    (date, shift_label, raw_name) triples, filtering out blanks, known
    non-person placeholder tokens, and time-range strings like "10-14".
    """
    year_month = parse_tab_title(month_tab)
    if year_month is None:
        raise ValueError(f"'{month_tab}' doesn't look like a month tab (expected e.g. 'August 2026')")
    tab_year, tab_month = year_month

    records: list[ShiftRecord] = []
    current_week_dates: list[date] | None = None

    for row in rows:
        week_dates = _row_week_dates(row, tab_year, tab_month)
        if week_dates is not None:
            current_week_dates = week_dates
            # Deliberately no `continue` here: a genuine shift row can carry
            # real left-grid data on the exact same physical row that also
            # happens to contain a right-grid date string further along (see
            # MAX_HEADER_COLUMN) - skipping the label check on that row
            # would silently drop that week's real data.

        label_match = _row_shift_label(row)
        if label_match is None or current_week_dates is None:
            continue
        col, shift_label = label_match

        for offset in range(DAYS_PER_WEEK_BLOCK):
            cell_index = col + 1 + offset
            if cell_index >= len(row):
                break
            raw_name = strip_merged(row[cell_index])
            if not raw_name:
                continue
            if raw_name.lower() in PLACEHOLDER_TOKENS:
                continue
            if _looks_like_time_range(raw_name):
                continue
            records.append(
                ShiftRecord(date=current_week_dates[offset], shift_label=shift_label, raw_name=raw_name)
            )

    return records
