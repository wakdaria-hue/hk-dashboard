"""Google Sheets API access (service account). No Drive export-as-text involved."""
from __future__ import annotations

import gspread
import streamlit as st
from google.oauth2.service_account import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
]


class SheetAccessError(Exception):
    """Raised when a hotel's sheet can't be reached (API error, rate limit, missing share)."""


@st.cache_resource(show_spinner=False)
def _get_client() -> gspread.Client:
    info = dict(st.secrets["gcp_service_account"])
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    return gspread.authorize(creds)


def fetch_hotel_sheet_raw(sheet_id: str) -> tuple[list[list[str]], list[list]]:
    """Fetch a hotel's HK schedule sheet (first worksheet).

    Returns (formatted_rows, unformatted_rows) — same shape, aligned row-by-row
    and cell-by-cell. `formatted` mirrors what a person sees in the sheet
    (e.g. "4:30:00"); `unformatted` gives raw values (numbers as floats, which
    for a duration-formatted cell is an exact day-fraction, not rounded text).

    Raises SheetAccessError on any API failure so callers can show a
    per-hotel error instead of crashing the whole app.
    """
    try:
        client = _get_client()
        sh = client.open_by_key(sheet_id)
        ws = sh.get_worksheet(0)
        formatted = ws.get_all_values(value_render_option="FORMATTED_VALUE")
        unformatted = ws.get_all_values(value_render_option="UNFORMATTED_VALUE")
        return formatted, unformatted
    except gspread.exceptions.APIError as e:
        raise SheetAccessError(f"Google Sheets API error: {e}") from e
    except Exception as e:  # noqa: BLE001 - surface any auth/network failure uniformly
        raise SheetAccessError(f"Could not read sheet: {e}") from e


def fetch_rate_store_worksheet(spreadsheet_id: str, worksheet_name: str) -> gspread.Worksheet:
    """Open (creating if needed) a worksheet used as a persistent data store."""
    client = _get_client()
    sh = client.open_by_key(spreadsheet_id)
    try:
        return sh.worksheet(worksheet_name)
    except gspread.exceptions.WorksheetNotFound:
        return sh.add_worksheet(title=worksheet_name, rows=1000, cols=10)
