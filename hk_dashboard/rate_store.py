"""Persistent store of parsed payroll rates (a tab in a Google Sheet).

Streamlit Community Cloud has no persistent local disk, so this is the only
thing that survives an app restart. Writing is an upsert on (name, month):
re-uploading a payroll PDF that covers a month already stored (e.g. a fresh
cumulative export) overwrites that month's rate rather than duplicating it.
"""
from __future__ import annotations

from datetime import date

import pandas as pd

from hk_dashboard.config import RATE_STORE_HEADER, RATE_STORE_WORKSHEET
from hk_dashboard.payroll_pdf import LoonkostenRow
from hk_dashboard.sheets_client import fetch_rate_store_worksheet


def _ensure_header(ws) -> None:
    first_row = ws.row_values(1)
    if first_row != RATE_STORE_HEADER:
        ws.update("A1", [RATE_STORE_HEADER])


def read_rate_store(spreadsheet_id: str) -> pd.DataFrame:
    ws = fetch_rate_store_worksheet(spreadsheet_id, RATE_STORE_WORKSHEET)
    _ensure_header(ws)
    values = ws.get_all_records()
    df = pd.DataFrame(values, columns=RATE_STORE_HEADER)
    if not df.empty:
        df["hourly_rate_eur"] = pd.to_numeric(df["hourly_rate_eur"], errors="coerce")
    return df


def get_rate(rates_df: pd.DataFrame, name: str, month: str) -> float | None:
    """month is 'YYYY-MM'. Returns None if no rate is on file for that person+month."""
    if rates_df.empty:
        return None
    match = rates_df[(rates_df["name"] == name) & (rates_df["month"] == month)]
    if match.empty:
        return None
    return float(match.iloc[0]["hourly_rate_eur"])


def upsert_rates(
    spreadsheet_id: str,
    rows: list[LoonkostenRow],
    source_label: str,
    upload_date: date | None = None,
) -> pd.DataFrame:
    """Write parsed payroll rows into the rate store, overwriting same (name, month) rows.

    Returns the resulting full rate-store DataFrame.
    """
    upload_date = upload_date or date.today()
    existing = read_rate_store(spreadsheet_id)

    new_df = pd.DataFrame(
        [
            {
                "name": r.name,
                "month": r.month_str,
                "hourly_rate_eur": r.hourly_rate_eur,
                "source": source_label,
                "upload_date": upload_date.isoformat(),
            }
            for r in rows
        ]
    )

    if existing.empty:
        merged = new_df
    else:
        key_cols = ["name", "month"]
        existing_keyed = existing.set_index(key_cols)
        new_keyed = new_df.set_index(key_cols)
        existing_keyed = existing_keyed[~existing_keyed.index.isin(new_keyed.index)]
        merged = pd.concat([existing_keyed, new_keyed]).reset_index()

    merged = merged.sort_values(["name", "month"]).reset_index(drop=True)

    ws = fetch_rate_store_worksheet(spreadsheet_id, RATE_STORE_WORKSHEET)
    ws.clear()
    ws.update("A1", [RATE_STORE_HEADER] + merged[RATE_STORE_HEADER].astype(str).values.tolist())

    return merged
