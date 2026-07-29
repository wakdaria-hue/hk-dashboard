"""Persistent store of parsed payroll rates (a tab in a Google Sheet).

Streamlit Community Cloud has no persistent local disk, so this is the only
thing that survives an app restart. Writing is an upsert on (name, month):
re-uploading a payroll PDF that covers a month already stored (e.g. a fresh
cumulative export) overwrites that month's hourly rate rather than
duplicating it - except netto_salary_eur, which is only overwritten when
the new upload actually has a value for that name+month (payslips only
cover the upload's own pay period, not the full cumulative history the
Overzicht Loonkosten table does), so a later upload never blanks out a net
salary that an earlier upload already recorded.
"""
from __future__ import annotations

from datetime import date

import pandas as pd

from hk_dashboard.config import RATE_STORE_HEADER, RATE_STORE_WORKSHEET
from hk_dashboard.payroll_pdf import PayrollData
from hk_dashboard.sheets_client import fetch_rate_store_worksheet


def _ensure_header(ws) -> None:
    first_row = ws.row_values(1)
    if first_row == RATE_STORE_HEADER:
        return
    if not first_row:
        ws.update("A1", [RATE_STORE_HEADER])
        return
    # Migrate from an older header shape (e.g. before netto_salary_eur existed):
    # re-key existing rows by whatever header is actually there, then rewrite
    # under the current header - any new column comes out blank for old rows
    # rather than misaligning every column after it.
    all_values = ws.get_all_values()
    old_header, old_rows = all_values[0], all_values[1:]
    migrated = [[dict(zip(old_header, row)).get(col, "") for col in RATE_STORE_HEADER] for row in old_rows]
    ws.clear()
    ws.update("A1", [RATE_STORE_HEADER] + migrated)


def read_rate_store(spreadsheet_id: str) -> pd.DataFrame:
    ws = fetch_rate_store_worksheet(spreadsheet_id, RATE_STORE_WORKSHEET)
    _ensure_header(ws)
    values = ws.get_all_records()
    df = pd.DataFrame(values, columns=RATE_STORE_HEADER)
    if not df.empty:
        df["hourly_rate_eur"] = pd.to_numeric(df["hourly_rate_eur"], errors="coerce")
        df["netto_salary_eur"] = pd.to_numeric(df["netto_salary_eur"], errors="coerce")
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
    payroll_data: PayrollData,
    source_label: str,
    upload_date: date | None = None,
) -> pd.DataFrame:
    """Write parsed payroll data into the rate store, overwriting same (name, month) rows.

    Returns the resulting full rate-store DataFrame.
    """
    upload_date = upload_date or date.today()
    existing = read_rate_store(spreadsheet_id)

    new_records = []
    for r in payroll_data.loonkosten_rows:
        netto = None
        if (
            payroll_data.netto_period
            and (r.year, r.month) == payroll_data.netto_period
            and r.employee_number is not None
        ):
            netto = payroll_data.netto_by_employee_number.get(r.employee_number)
        new_records.append(
            {
                "name": r.name,
                "month": r.month_str,
                "hourly_rate_eur": r.hourly_rate_eur,
                "netto_salary_eur": netto,
                "source": source_label,
                "upload_date": upload_date.isoformat(),
            }
        )
    new_df = pd.DataFrame(new_records)

    if existing.empty:
        merged = new_df
    else:
        key_cols = ["name", "month"]
        existing_keyed = existing.set_index(key_cols)
        new_keyed = new_df.set_index(key_cols)

        # Preserve a previously-stored net salary where this upload has none.
        missing_netto = new_keyed["netto_salary_eur"].isna()
        for idx in new_keyed.index[missing_netto]:
            if idx in existing_keyed.index and pd.notna(existing_keyed.loc[idx, "netto_salary_eur"]):
                new_keyed.loc[idx, "netto_salary_eur"] = existing_keyed.loc[idx, "netto_salary_eur"]

        existing_keyed = existing_keyed[~existing_keyed.index.isin(new_keyed.index)]
        merged = pd.concat([existing_keyed, new_keyed]).reset_index()

    merged = merged.sort_values(["name", "month"]).reset_index(drop=True)

    ws = fetch_rate_store_worksheet(spreadsheet_id, RATE_STORE_WORKSHEET)
    ws.clear()
    ws.update("A1", [RATE_STORE_HEADER] + _rows_for_sheet(merged))

    return merged


def _rows_for_sheet(df: pd.DataFrame) -> list[list[str]]:
    # Plain str(v) per value via itertuples (not Series.astype(str)/.values) -
    # pandas' Arrow-backed string dtype (pandas 3.x) can leave NaN/pd.NA
    # un-stringified, which then fails to JSON-encode for the Sheets API
    # request (the same root cause as the earlier Excel-export width crash).
    rows = []
    for row in df[RATE_STORE_HEADER].itertuples(index=False, name=None):
        rows.append(["" if pd.isna(v) else str(v) for v in row])
    return rows
