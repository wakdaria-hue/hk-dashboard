"""Persistent store of logged room assignments (a tab in the rate-store Sheet).

Same pattern as occupancy_store: upsert on (date, hotel, employee), one row
per housekeeper per day, read-merge-write once rather than row-by-row (the
Sheets per-minute quota).

The room lists are stored as comma-joined strings rather than a count alone -
the counts drive every calculation, but the actual codes are what make a
disputed or odd-looking day checkable after the fact.
"""
from __future__ import annotations

from datetime import date, datetime

import pandas as pd

from hk_dashboard.config import ASSIGNMENT_HEADER, ASSIGNMENT_WORKSHEET
from hk_dashboard.sheets_client import fetch_rate_store_worksheet

_NUMERIC_COLUMNS = ["checkout_count", "stayover_count"]


def _ensure_capacity(ws, needed_rows: int) -> None:
    """New tabs are 1000x10 (see sheets_client.fetch_rate_store_worksheet) and
    writing past the grid is a hard API error, not an auto-expand."""
    if ws.col_count < len(ASSIGNMENT_HEADER):
        ws.add_cols(len(ASSIGNMENT_HEADER) - ws.col_count)
    if ws.row_count < needed_rows:
        ws.add_rows(needed_rows - ws.row_count)


def _ensure_header(ws) -> None:
    _ensure_capacity(ws, needed_rows=2)
    first_row = ws.row_values(1)
    if first_row == ASSIGNMENT_HEADER:
        return
    if not first_row:
        ws.update("A1", [ASSIGNMENT_HEADER])
        return
    all_values = ws.get_all_values()
    old_header, old_rows = all_values[0], all_values[1:]
    migrated = [
        [dict(zip(old_header, row)).get(col, "") for col in ASSIGNMENT_HEADER] for row in old_rows
    ]
    ws.clear()
    ws.update("A1", [ASSIGNMENT_HEADER] + migrated)


def read_assignments(spreadsheet_id: str) -> pd.DataFrame:
    ws = fetch_rate_store_worksheet(spreadsheet_id, ASSIGNMENT_WORKSHEET)
    _ensure_header(ws)
    df = pd.DataFrame(ws.get_all_records(), columns=ASSIGNMENT_HEADER)
    if df.empty:
        return df
    for col in _NUMERIC_COLUMNS:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    df = df[df["date"].notna()].copy()
    df["rooms_assigned"] = df["checkout_count"] + df["stayover_count"]
    df["month"] = df["date"].apply(lambda d: f"{d.year:04d}-{d.month:02d}")
    return df.sort_values(["date", "hotel", "employee"]).reset_index(drop=True)


def upsert_assignment(
    spreadsheet_id: str,
    entry_date: date,
    hotel: str,
    employee: str,
    raw_name: str,
    checkout_rooms: list[str],
    stayover_rooms: list[str],
    notes: str,
    entered_at: datetime | None = None,
) -> pd.DataFrame:
    """Save one housekeeper's assignment for one day, replacing any existing
    row for that (date, hotel, employee)."""
    existing = read_assignments(spreadsheet_id)
    new_row = pd.DataFrame(
        [
            {
                "date": entry_date,
                "hotel": hotel,
                "employee": employee,
                "raw_name": raw_name,
                "checkout_rooms": ",".join(checkout_rooms),
                "checkout_count": len(checkout_rooms),
                "stayover_rooms": ",".join(stayover_rooms),
                "stayover_count": len(stayover_rooms),
                "notes": notes,
                "entered_at": (entered_at or datetime.now()).isoformat(timespec="seconds"),
            }
        ]
    )

    if existing.empty:
        merged = new_row
    else:
        key_cols = ["date", "hotel", "employee"]
        existing_keyed = existing.drop(columns=["month", "rooms_assigned"]).set_index(key_cols)
        new_keyed = new_row.set_index(key_cols)
        existing_keyed = existing_keyed[~existing_keyed.index.isin(new_keyed.index)]
        merged = pd.concat([existing_keyed, new_keyed]).reset_index()

    merged = merged.sort_values(["date", "hotel", "employee"]).reset_index(drop=True)
    _write_assignments(spreadsheet_id, merged)
    return merged


def delete_assignments(
    spreadsheet_id: str, keys: list[tuple[date, str, str]]
) -> pd.DataFrame:
    """Remove specific (date, hotel, employee) rows."""
    existing = read_assignments(spreadsheet_id)
    if existing.empty or not keys:
        return existing
    remaining = existing[
        ~existing.set_index(["date", "hotel", "employee"]).index.isin(keys)
    ].reset_index(drop=True)
    _write_assignments(
        spreadsheet_id, remaining.drop(columns=["month", "rooms_assigned"], errors="ignore")
    )
    return remaining


def _write_assignments(spreadsheet_id: str, df: pd.DataFrame) -> None:
    ws = fetch_rate_store_worksheet(spreadsheet_id, ASSIGNMENT_WORKSHEET)
    frame = df.reindex(columns=ASSIGNMENT_HEADER)
    # Plain str(v) per value - pandas' Arrow-backed string dtype can leave
    # NaN/pd.NA un-stringified, which then fails to JSON-encode for Sheets.
    rows = [
        ["" if pd.isna(v) else str(v) for v in row]
        for row in frame.itertuples(index=False, name=None)
    ]
    _ensure_capacity(ws, needed_rows=len(rows) + 1)
    ws.clear()
    ws.update("A1", [ASSIGNMENT_HEADER] + rows)
