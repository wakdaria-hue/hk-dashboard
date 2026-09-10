"""Persistent store of uploaded Mews occupancy figures (a tab in a Google Sheet).

Same shape and reasoning as rate_store.py: Streamlit Community Cloud has no
persistent disk, so a Sheets tab is the only thing that survives a restart.
Writing is an upsert on (hotel, date) - re-uploading an overlapping export
(e.g. a fresher forecast for a range already stored) replaces those days
rather than duplicating them, which is exactly what you want when bookings
for a future date have moved since the last export.

Past and future dates live in the same tab on purpose: past-dated rows
calibrate the historical baseline (minutes per room), future-dated rows drive
the forecast. Which role a row plays is decided by its date at read time, not
by where it's stored.
"""
from __future__ import annotations

from datetime import date

import pandas as pd

from hk_dashboard.config import OCCUPANCY_HEADER, OCCUPANCY_WORKSHEET
from hk_dashboard.sheets_client import fetch_rate_store_worksheet

_NUMERIC_COLUMNS = ["departures", "stayovers", "rooms_to_clean", "occupied", "rooms_total"]


def _ensure_capacity(ws, needed_rows: int) -> None:
    """Grow the worksheet grid if it's too small to hold the write.

    New tabs are created 1000 rows x 10 columns (see
    sheets_client.fetch_rate_store_worksheet), but this store is 11 columns
    wide and accumulates a row per hotel per day - four hotels over a year is
    ~1,500 rows. Writing past the grid's edge is a hard Sheets API error, not
    an auto-expand, so the grid has to be widened first.
    """
    if ws.col_count < len(OCCUPANCY_HEADER):
        ws.add_cols(len(OCCUPANCY_HEADER) - ws.col_count)
    if ws.row_count < needed_rows:
        ws.add_rows(needed_rows - ws.row_count)


def _ensure_header(ws) -> None:
    _ensure_capacity(ws, needed_rows=2)
    first_row = ws.row_values(1)
    if first_row == OCCUPANCY_HEADER:
        return
    if not first_row:
        ws.update("A1", [OCCUPANCY_HEADER])
        return
    # Re-key existing rows by whatever header is actually there, then rewrite
    # under the current one, so a column added later comes out blank for old
    # rows instead of misaligning everything after it (see rate_store).
    all_values = ws.get_all_values()
    old_header, old_rows = all_values[0], all_values[1:]
    migrated = [
        [dict(zip(old_header, row)).get(col, "") for col in OCCUPANCY_HEADER] for row in old_rows
    ]
    ws.clear()
    ws.update("A1", [OCCUPANCY_HEADER] + migrated)


def read_occupancy_store(spreadsheet_id: str) -> pd.DataFrame:
    ws = fetch_rate_store_worksheet(spreadsheet_id, OCCUPANCY_WORKSHEET)
    _ensure_header(ws)
    df = pd.DataFrame(ws.get_all_records(), columns=OCCUPANCY_HEADER)
    if df.empty:
        return df
    for col in _NUMERIC_COLUMNS:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    df = df[df["date"].notna()]
    df["month"] = df["date"].apply(lambda d: f"{d.year:04d}-{d.month:02d}")
    return df.sort_values(["hotel", "date"]).reset_index(drop=True)


def upsert_occupancy(
    spreadsheet_id: str,
    new_rows: pd.DataFrame,
    source_label: str,
    upload_date: date | None = None,
) -> pd.DataFrame:
    """Write parsed occupancy rows, replacing same (hotel, date) rows.

    Takes one DataFrame for every file being saved (the upload page can hand
    over several hotels' exports at once) and writes the merged result in a
    single Sheets call - one row at a time would burn the API's per-minute
    quota on a 90-day range.
    """
    upload_date = upload_date or date.today()
    existing = read_occupancy_store(spreadsheet_id)

    incoming = new_rows.copy()
    incoming["source"] = source_label
    incoming["upload_date"] = upload_date.isoformat()

    if existing.empty:
        merged = incoming
    else:
        key_cols = ["hotel", "date"]
        existing_keyed = existing.drop(columns=["month"]).set_index(key_cols)
        incoming_keyed = incoming.set_index(key_cols)
        existing_keyed = existing_keyed[~existing_keyed.index.isin(incoming_keyed.index)]
        merged = pd.concat([existing_keyed, incoming_keyed]).reset_index()

    merged = merged.sort_values(["hotel", "date"]).reset_index(drop=True)
    _write_occupancy_store(spreadsheet_id, merged)
    return merged


def delete_occupancy_rows(spreadsheet_id: str, keys: list[tuple[str, date]]) -> pd.DataFrame:
    """Remove specific (hotel, date) rows. Returns the resulting DataFrame."""
    existing = read_occupancy_store(spreadsheet_id)
    if existing.empty or not keys:
        return existing
    remaining = existing[
        ~existing.set_index(["hotel", "date"]).index.isin(keys)
    ].reset_index(drop=True)
    _write_occupancy_store(spreadsheet_id, remaining.drop(columns=["month"], errors="ignore"))
    return remaining


def clear_occupancy_store(spreadsheet_id: str) -> pd.DataFrame:
    empty = pd.DataFrame(columns=OCCUPANCY_HEADER)
    _write_occupancy_store(spreadsheet_id, empty)
    return empty


def _write_occupancy_store(spreadsheet_id: str, df: pd.DataFrame) -> None:
    ws = fetch_rate_store_worksheet(spreadsheet_id, OCCUPANCY_WORKSHEET)
    rows = _rows_for_sheet(df)
    _ensure_capacity(ws, needed_rows=len(rows) + 1)
    ws.clear()
    ws.update("A1", [OCCUPANCY_HEADER] + rows)


def _rows_for_sheet(df: pd.DataFrame) -> list[list[str]]:
    # Plain str(v) per value via itertuples - pandas' Arrow-backed string
    # dtype (pandas 3.x) can leave NaN/pd.NA un-stringified, which then fails
    # to JSON-encode for the Sheets API request (same root cause as the
    # earlier rate-store and Excel-export crashes).
    frame = df.reindex(columns=OCCUPANCY_HEADER)
    return [
        ["" if pd.isna(v) else str(v) for v in row]
        for row in frame.itertuples(index=False, name=None)
    ]
