"""Parse a Mews "Availability report" .xlsx export into per-day room counts.

Format verified against real exports (Vondel Garden Hotel, July and August
2026):

- A `Parameters` tab of key/value rows carries the report's identity:
  `Enterprise` (the hotel's full Mews name), `Start`/`End` (the exported date
  range) and `Created` (when Mews generated it). `Created` matters for a
  forward-looking export: it dates the bookings the numbers are based on, so
  a forecast can say what it was true "as of" rather than implying the future
  is settled.
- Every other tab is the same shape: row 1 is
  ["Service", "Space category", <one datetime per day>, "Total"], then one
  row per space category (SGL, DBL, ...), then a final "Total" row. Both the
  trailing Total *column* and the final Total *row* have to be skipped or
  they'd be counted a second time - the per-day figure comes from the Total
  row's date columns only, which are identified by their header being a real
  datetime rather than by position.

Only `Departures` and `Stayovers` feed the rooms-to-clean formula;
`Occupied` and `Spaces` are read too, purely so the upload preview and the
stored history stay sanity-checkable by eye.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

import openpyxl
import pandas as pd

from hk_dashboard.config import MEWS_ENTERPRISE_TO_HOTEL

TOTAL_LABEL = "total"
SERVICE_COLUMN = 1
REQUIRED_TABS = ("Departures", "Stayovers")
OPTIONAL_TABS = ("Occupied", "Spaces")


class AvailabilityReportError(Exception):
    """Raised when a file isn't a readable Mews Availability report."""


@dataclass
class DailyOccupancy:
    date: date
    departures: float
    stayovers: float
    occupied: float | None
    rooms_total: float | None

    @property
    def rooms_to_clean(self) -> float:
        """Checkout rooms needing a full clean, plus occupied rooms needing a
        refresh. Deliberately not `Occupied`, which undercounts a day where a
        room turns over (checkout + new arrival in the same room)."""
        return self.departures + self.stayovers


@dataclass
class AvailabilityReport:
    filename: str
    enterprise: str
    hotel: str | None  # resolved short code, or None if the enterprise is unknown
    start: date | None
    end: date | None
    created: datetime | None
    days: list[DailyOccupancy]


def _to_number(value) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", "."))
    except ValueError:
        return None


def _as_date(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def _read_parameters(wb) -> dict[str, object]:
    if "Parameters" not in wb.sheetnames:
        raise AvailabilityReportError(
            "This file has no 'Parameters' tab, so it doesn't look like a Mews "
            "Availability report export. Re-export it from Mews as .xlsx."
        )
    params: dict[str, object] = {}
    for row in wb["Parameters"].iter_rows(values_only=True):
        if not row or not isinstance(row[0], str) or not row[0].strip():
            continue
        value = row[1] if len(row) > 1 else None
        if value is not None:
            params[row[0].strip()] = value
    return params


def _read_daily_totals(wb, tab: str) -> dict[date, float]:
    """Per-day totals from one grid tab, keyed by date.

    Reads the sheet's own "Total" row where present; otherwise sums the
    per-space-category rows, so a hotel exported with a single category (or a
    Mews variant that omits the Total row) still parses.
    """
    ws = wb[tab]
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        raise AvailabilityReportError(f"The '{tab}' tab in this export is empty.")

    header = rows[0]
    date_columns = {
        idx: parsed
        for idx, value in enumerate(header)
        if idx > SERVICE_COLUMN and (parsed := _as_date(value)) is not None
    }
    if not date_columns:
        raise AvailabilityReportError(
            f"The '{tab}' tab has no dated columns in its header row - the "
            "export's layout isn't what this parser expects."
        )

    total_row = next(
        (
            row
            for row in rows[1:]
            if row and isinstance(row[0], str) and row[0].strip().lower() == TOTAL_LABEL
        ),
        None,
    )

    totals: dict[date, float] = {}
    if total_row is not None:
        for idx, day in date_columns.items():
            totals[day] = _to_number(total_row[idx] if idx < len(total_row) else None) or 0.0
        return totals

    for day in date_columns.values():
        totals[day] = 0.0
    for row in rows[1:]:
        if not row or (isinstance(row[0], str) and row[0].strip().lower() == TOTAL_LABEL):
            continue
        for idx, day in date_columns.items():
            totals[day] += _to_number(row[idx] if idx < len(row) else None) or 0.0
    return totals


def parse_availability_workbook(file, filename: str) -> AvailabilityReport:
    """Parse an uploaded Mews Availability report into an AvailabilityReport."""
    try:
        wb = openpyxl.load_workbook(file, data_only=True)
    except Exception as e:  # noqa: BLE001 - any openpyxl failure is "not a usable xlsx"
        raise AvailabilityReportError(
            f"Couldn't open '{filename}' as an .xlsx workbook: {e}"
        ) from e

    params = _read_parameters(wb)

    missing = [tab for tab in REQUIRED_TABS if tab not in wb.sheetnames]
    if missing:
        raise AvailabilityReportError(
            f"'{filename}' is missing the {', '.join(missing)} tab(s). The "
            "rooms-to-clean figure needs both Departures and Stayovers, so "
            "export the report with all tabs included."
        )

    departures = _read_daily_totals(wb, "Departures")
    stayovers = _read_daily_totals(wb, "Stayovers")
    occupied = _read_daily_totals(wb, "Occupied") if "Occupied" in wb.sheetnames else {}
    spaces = _read_daily_totals(wb, "Spaces") if "Spaces" in wb.sheetnames else {}

    days = [
        DailyOccupancy(
            date=day,
            departures=departures[day],
            stayovers=stayovers.get(day, 0.0),
            occupied=occupied.get(day),
            rooms_total=spaces.get(day),
        )
        for day in sorted(departures)
    ]
    if not days:
        raise AvailabilityReportError(
            f"'{filename}' parsed but contained no dated columns - nothing to save."
        )

    enterprise = str(params.get("Enterprise", "") or "").strip()
    created = params.get("Created")

    return AvailabilityReport(
        filename=filename,
        enterprise=enterprise,
        hotel=MEWS_ENTERPRISE_TO_HOTEL.get(enterprise.lower()),
        start=_as_date(params.get("Start")),
        end=_as_date(params.get("End")),
        created=created if isinstance(created, datetime) else None,
        days=days,
    )


def report_to_rows(report: AvailabilityReport, hotel: str) -> pd.DataFrame:
    """Flatten a parsed report into occupancy-store rows for one hotel."""
    return pd.DataFrame(
        [
            {
                "hotel": hotel,
                "date": d.date,
                "departures": d.departures,
                "stayovers": d.stayovers,
                "rooms_to_clean": d.rooms_to_clean,
                "occupied": d.occupied,
                "rooms_total": d.rooms_total,
                "enterprise": report.enterprise,
                "report_created": report.created.isoformat(timespec="seconds")
                if report.created
                else "",
            }
            for d in report.days
        ]
    )


def rows_to_preview_df(report: AvailabilityReport, hotel: str) -> pd.DataFrame:
    """Human-checkable preview of what was parsed, before anything is saved."""
    df = report_to_rows(report, hotel)
    return df[
        ["hotel", "date", "departures", "stayovers", "rooms_to_clean", "occupied", "rooms_total"]
    ]
