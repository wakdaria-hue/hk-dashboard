"""Housekeeper self-reported hours (a tab in the confirmation spreadsheet -
see config.CONFIRMATION_SELF_REPORTS_WORKSHEET), written by the login-free
confirm_app.py.

Many independent concurrent writers (different housekeepers tapping "Yes"/
"No" at end-of-shift, at possibly the same hotel around the same time) -
deliberately does NOT reuse rate_store.py's clear-and-rewrite-the-whole-tab
pattern (that's fine for a table one person edits; here it would risk
clobbering a concurrent submission). Instead: look up just the key columns
to find an existing row, then update only that row or append a new one.
"""
from __future__ import annotations

from datetime import date, datetime

import pandas as pd

from hk_dashboard.config import SELF_REPORTS_HEADER, CONFIRMATION_SELF_REPORTS_WORKSHEET
from hk_dashboard.sheets_client import fetch_rate_store_worksheet
from hk_dashboard.timeutil import now_amsterdam

_LAST_COL = "J"  # SELF_REPORTS_HEADER has 10 columns, A-J


class SelfReportWriteError(Exception):
    """Raised when a self-report write fails even after one retry."""


def _ensure_header(ws) -> None:
    first_row = ws.row_values(1)
    if first_row != SELF_REPORTS_HEADER:
        ws.update("A1", [SELF_REPORTS_HEADER])


def read_self_reports(spreadsheet_id: str) -> pd.DataFrame:
    ws = fetch_rate_store_worksheet(spreadsheet_id, CONFIRMATION_SELF_REPORTS_WORKSHEET)
    _ensure_header(ws)
    values = ws.get_all_records()
    df = pd.DataFrame(values, columns=SELF_REPORTS_HEADER)
    if not df.empty:
        df["reception_hours_numeric"] = pd.to_numeric(df["reception_hours_numeric"], errors="coerce")
        df["disputed_hours_numeric"] = pd.to_numeric(df["disputed_hours_numeric"], errors="coerce")
    return df


def _stringify(row: dict) -> list[str]:
    return ["" if pd.isna(row.get(c)) or row.get(c) is None else str(row[c]) for c in SELF_REPORTS_HEADER]


def _find_row_index(ws, date_str: str, hotel: str, name: str) -> int | None:
    """Row index (1-based, matching sheet rows) of an existing (date, hotel,
    name) record, or None. Only reads columns A-C, not the whole tab."""
    key = (date_str, hotel, name)
    key_rows = ws.get("A2:C")
    for i, row in enumerate(key_rows, start=2):
        padded = tuple((row + ["", "", ""])[:3])
        if padded == key:
            return i
    return None


def _do_upsert(spreadsheet_id: str, record: dict) -> None:
    ws = fetch_rate_store_worksheet(spreadsheet_id, CONFIRMATION_SELF_REPORTS_WORKSHEET)
    _ensure_header(ws)
    row_values = _stringify(record)
    row_idx = _find_row_index(ws, record["date"], record["hotel"], record["name"])
    if row_idx is not None:
        ws.update(f"A{row_idx}:{_LAST_COL}{row_idx}", [row_values])
    else:
        ws.append_row(row_values)


def upsert_self_report(
    spreadsheet_id: str,
    date_: date,
    hotel: str,
    name: str,
    reception_hours_shown: str,
    reception_hours_numeric: float,
    status: str,  # "Confirmed" | "Disputed"
    disputed_start: str = "",
    disputed_end: str = "",
    disputed_hours_numeric: float | None = None,
    confirmed_at: datetime | None = None,
) -> None:
    """Upsert keyed on (date, hotel, name) - last write wins, no duplicates.

    Retries once on any failure before raising SelfReportWriteError, so the
    caller can show "couldn't save, try again" rather than a false success.
    """
    record = {
        "date": date_.isoformat(),
        "hotel": hotel,
        "name": name,
        "reception_hours_shown": reception_hours_shown,
        "reception_hours_numeric": reception_hours_numeric,
        "status": status,
        "disputed_start": disputed_start,
        "disputed_end": disputed_end,
        "disputed_hours_numeric": disputed_hours_numeric,
        "confirmed_at": (confirmed_at or now_amsterdam()).isoformat(timespec="seconds"),
    }
    try:
        _do_upsert(spreadsheet_id, record)
    except Exception:
        try:
            _do_upsert(spreadsheet_id, record)
        except Exception as e:
            raise SelfReportWriteError(f"Could not save to the confirmation sheet: {e}") from e


def monthly_confirmed_hours(self_reports_df: pd.DataFrame, hotel: str, name: str, month: str) -> float:
    """Sum reception_hours_numeric where status == 'Confirmed', for a given
    hotel+name+month ('YYYY-MM') - the housekeeper's month-end popup total.
    Disputed rows don't count: there's no agreed number for those yet."""
    if self_reports_df.empty:
        return 0.0
    match = self_reports_df[
        (self_reports_df["hotel"] == hotel)
        & (self_reports_df["name"] == name)
        & (self_reports_df["date"].astype(str).str.startswith(month))
        & (self_reports_df["status"] == "Confirmed")
    ]
    return float(match["reception_hours_numeric"].sum())
