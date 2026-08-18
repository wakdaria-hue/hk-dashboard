"""Staff identity list for HK Hours Self-Confirmation (a tab in the
confirmation spreadsheet - see config.CONFIRMATION_STAFF_WORKSHEET).

Low-frequency, single-writer (Daria, via pages/8_Staff_Identity.py) - safe to
reuse rate_store.py's clear-and-rewrite-the-whole-tab pattern, unlike
self_report_store.py which has many independent concurrent writers.
"""
from __future__ import annotations

from datetime import date

import pandas as pd

from hk_dashboard.config import STAFF_HEADER, CONFIRMATION_STAFF_WORKSHEET
from hk_dashboard.dateparse import parse_birthdate
from hk_dashboard.sheets_client import fetch_rate_store_worksheet


def _ensure_header(ws) -> None:
    first_row = ws.row_values(1)
    if first_row != STAFF_HEADER:
        ws.update("A1", [STAFF_HEADER])


def _normalized_birthdate(raw) -> str:
    parsed = parse_birthdate(raw)
    return parsed.isoformat() if parsed else ""


def read_staff(spreadsheet_id: str) -> pd.DataFrame:
    ws = fetch_rate_store_worksheet(spreadsheet_id, CONFIRMATION_STAFF_WORKSHEET)
    _ensure_header(ws)
    values = ws.get_all_records()
    df = pd.DataFrame(values, columns=STAFF_HEADER)
    if not df.empty:
        df["active"] = df["active"].astype(str).str.lower().isin(["true", "1", "yes"])
        # Normalize to ISO regardless of how the cell got its value - the
        # app always writes ISO, but a birthdate typed by hand straight into
        # the sheet renders in the sheet's locale format instead (see
        # dateparse.py).
        df["birthdate"] = df["birthdate"].apply(_normalized_birthdate)
    return df


def active_staff_for_hotel(spreadsheet_id: str, hotel: str) -> pd.DataFrame:
    df = read_staff(spreadsheet_id)
    if df.empty:
        return df
    return df[(df["hotel"] == hotel) & df["active"]].sort_values("name").reset_index(drop=True)


def upsert_staff_row(
    spreadsheet_id: str, name: str, hotel: str, birthdate: date, active: bool
) -> pd.DataFrame:
    """Upsert keyed on (name, hotel) - the same person at two hotels is two rows."""
    existing = read_staff(spreadsheet_id)
    new_row = pd.DataFrame(
        [{"name": name, "hotel": hotel, "birthdate": birthdate.isoformat(), "active": active}]
    )

    if existing.empty:
        merged = new_row
    else:
        key_cols = ["name", "hotel"]
        existing_keyed = existing.set_index(key_cols)
        new_keyed = new_row.set_index(key_cols)
        existing_keyed = existing_keyed[~existing_keyed.index.isin(new_keyed.index)]
        merged = pd.concat([existing_keyed, new_keyed]).reset_index()

    merged = merged.sort_values(["hotel", "name"]).reset_index(drop=True)
    _write_staff(spreadsheet_id, merged)
    return merged


def delete_staff_rows(spreadsheet_id: str, keys: list[tuple[str, str]]) -> pd.DataFrame:
    """keys: list of (name, hotel)."""
    existing = read_staff(spreadsheet_id)
    if existing.empty or not keys:
        return existing
    remaining = existing[~existing.set_index(["name", "hotel"]).index.isin(keys)].reset_index(drop=True)
    _write_staff(spreadsheet_id, remaining)
    return remaining


def _write_staff(spreadsheet_id: str, df: pd.DataFrame) -> None:
    ws = fetch_rate_store_worksheet(spreadsheet_id, CONFIRMATION_STAFF_WORKSHEET)
    ws.clear()
    ws.update("A1", [STAFF_HEADER] + _rows_for_sheet(df))


def _rows_for_sheet(df: pd.DataFrame) -> list[list[str]]:
    # Same NaN-safe stringification as rate_store._rows_for_sheet - pandas'
    # Arrow-backed string dtype can leave NaN/pd.NA un-stringified, which
    # then fails to JSON-encode for the Sheets API request.
    rows = []
    for row in df[STAFF_HEADER].itertuples(index=False, name=None):
        rows.append(["" if pd.isna(v) else str(v) for v in row])
    return rows
