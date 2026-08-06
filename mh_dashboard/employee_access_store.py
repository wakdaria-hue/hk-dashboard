"""employee_access: the strict schedule_name -> full_name -> birthdate table
for Mobile Hosts (see config.EMPLOYEE_ACCESS_HEADER).

Read-only from this app - Daria maintains it by hand in the sheet, the same
way she populates birthdates for HK staff (see hk_dashboard.staff_store). A
raw schedule name with no row here is never guessed at - see
mh_dashboard.aggregation.resolve_shifts.
"""
from __future__ import annotations

import pandas as pd

from hk_dashboard.sheets_client import fetch_rate_store_worksheet
from mh_dashboard.config import EMPLOYEE_ACCESS_HEADER, EMPLOYEE_ACCESS_WORKSHEET


def _ensure_header(ws) -> None:
    first_row = ws.row_values(1)
    if first_row != EMPLOYEE_ACCESS_HEADER:
        ws.update("A1", [EMPLOYEE_ACCESS_HEADER])


def read_employee_access(spreadsheet_id: str) -> pd.DataFrame:
    ws = fetch_rate_store_worksheet(spreadsheet_id, EMPLOYEE_ACCESS_WORKSHEET)
    _ensure_header(ws)
    values = ws.get_all_records()
    df = pd.DataFrame(values, columns=EMPLOYEE_ACCESS_HEADER)
    if not df.empty:
        df["active"] = df["active"].astype(str).str.lower().isin(["true", "1", "yes"])
    return df


def active_full_names(df: pd.DataFrame) -> list[str]:
    """Distinct, active full names for the confirm app's name picker - one
    person can have several alias rows (different schedule spellings)."""
    if df.empty:
        return []
    active = df[df["active"]] if "active" in df.columns else df
    return sorted(active["full_name"].dropna().astype(str).str.strip().unique().tolist())


def birthdate_for(df: pd.DataFrame, full_name: str) -> str | None:
    match = df[df["full_name"].astype(str).str.strip() == full_name]
    if match.empty:
        return None
    value = str(match.iloc[0]["birthdate"]).strip()
    return value or None
