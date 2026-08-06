"""Mobile Host monthly hours confirmation (see config.CONFIRMATIONS_HEADER),
written by the login-free mobile_hosts/confirm_app.py.

Many independent concurrent writers (different hosts confirming within the
same few-day window each month) - upsert-by-key, not clear-and-rewrite, same
reasoning as hk_dashboard.self_report_store.
"""
from __future__ import annotations

from datetime import date, datetime

import pandas as pd

from hk_dashboard.sheets_client import fetch_rate_store_worksheet
from hk_dashboard.timeutil import now_amsterdam
from mh_dashboard.config import CONFIRMATIONS_HEADER, CONFIRMATIONS_WORKSHEET

_LAST_COL = "I"  # CONFIRMATIONS_HEADER has 9 columns, A-I


class ConfirmationWriteError(Exception):
    """Raised when a confirmation write fails even after one retry."""


def _ensure_header(ws) -> None:
    first_row = ws.row_values(1)
    if first_row != CONFIRMATIONS_HEADER:
        ws.update("A1", [CONFIRMATIONS_HEADER])


def read_confirmations(spreadsheet_id: str) -> pd.DataFrame:
    ws = fetch_rate_store_worksheet(spreadsheet_id, CONFIRMATIONS_WORKSHEET)
    _ensure_header(ws)
    values = ws.get_all_records()
    df = pd.DataFrame(values, columns=CONFIRMATIONS_HEADER)
    if not df.empty:
        df["shift_count"] = pd.to_numeric(df["shift_count"], errors="coerce")
        df["total_hours"] = pd.to_numeric(df["total_hours"], errors="coerce")
    return df


def _stringify(row: dict) -> list[str]:
    return ["" if pd.isna(row.get(c)) or row.get(c) is None else str(row[c]) for c in CONFIRMATIONS_HEADER]


def _find_row_index(ws, month: str, full_name: str) -> int | None:
    """Row index (1-based) of an existing (month, full_name) record, or
    None. Only reads columns A-B, not the whole tab."""
    key = (month, full_name)
    key_rows = ws.get("A2:B")
    for i, row in enumerate(key_rows, start=2):
        padded = tuple((row + ["", ""])[:2])
        if padded == key:
            return i
    return None


def _do_upsert(spreadsheet_id: str, record: dict) -> None:
    ws = fetch_rate_store_worksheet(spreadsheet_id, CONFIRMATIONS_WORKSHEET)
    _ensure_header(ws)
    row_values = _stringify(record)
    row_idx = _find_row_index(ws, record["month"], record["full_name"])
    if row_idx is not None:
        ws.update(f"A{row_idx}:{_LAST_COL}{row_idx}", [row_values])
    else:
        ws.append_row(row_values)


def upsert_confirmation(
    spreadsheet_id: str,
    month: str,  # "YYYY-MM"
    full_name: str,
    status: str,  # "Confirmed" | "Disputed"
    shift_count: int,
    total_hours: float,
    dates_worked: list[date],
    disputed_dates: list[date] | None = None,
    comment: str = "",
    confirmed_at: datetime | None = None,
) -> None:
    """Upsert keyed on (month, full_name) - last write wins, no duplicates.

    Retries once on any failure before raising ConfirmationWriteError, so the
    caller can show "couldn't save, try again" rather than a false success.
    """
    record = {
        "month": month,
        "full_name": full_name,
        "status": status,
        "shift_count": shift_count,
        "total_hours": total_hours,
        "dates_worked": ", ".join(d.isoformat() for d in dates_worked),
        "disputed_dates": ", ".join(d.isoformat() for d in (disputed_dates or [])),
        "comment": comment,
        "confirmed_at": (confirmed_at or now_amsterdam()).isoformat(timespec="seconds"),
    }
    try:
        _do_upsert(spreadsheet_id, record)
    except Exception:
        try:
            _do_upsert(spreadsheet_id, record)
        except Exception as e:
            raise ConfirmationWriteError(f"Could not save to the confirmation sheet: {e}") from e
