"""Google Sheets API access (service account). No Drive export-as-text involved."""
from __future__ import annotations

import time

import gspread
import streamlit as st
from google.oauth2.service_account import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
]

_RETRY_DELAYS_SECONDS = [5, 15, 30]  # backoff for transient 429 / rate-limit errors


class SheetAccessError(Exception):
    """Raised when a hotel's sheet can't be reached (API error, rate limit, missing share)."""


@st.cache_resource(show_spinner=False)
def _get_client() -> gspread.Client:
    info = dict(st.secrets["gcp_service_account"])
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    return gspread.authorize(creds)


def _batch_get_with_retry(sh: gspread.Spreadsheet, ranges: list[str], value_render_option: str) -> list[list]:
    """One API call for every tab's data (instead of one call per tab), with
    retry-with-backoff on rate-limit errors. Returns a list of row-grids, one
    per requested range, in the same order as `ranges`.
    """
    last_error: Exception | None = None
    for delay in [0, *_RETRY_DELAYS_SECONDS]:
        if delay:
            time.sleep(delay)
        try:
            response = sh.values_batch_get(ranges, params={"valueRenderOption": value_render_option})
            return [vr.get("values", []) for vr in response.get("valueRanges", [])]
        except gspread.exceptions.APIError as e:
            last_error = e
            if "429" not in str(e) and "RESOURCE_EXHAUSTED" not in str(e):
                raise
    raise last_error


def fetch_hotel_sheet_raw(sheet_id: str) -> list[tuple[str, list[list[str]], list[list]]]:
    """Fetch every worksheet (tab) in a hotel's HK schedule spreadsheet.

    These sheets have one tab per month (confirmed against real data - a
    single-tab assumption silently truncated everything to whatever tab
    happened to be first), so every tab has to be read and combined. This
    uses batched requests (one call for all tabs, per value-render-option)
    rather than one call per tab, to stay well under the Sheets API's
    per-minute quota across 4 hotels x a dozen-plus month tabs each.

    Returns a list of (tab_title, formatted_rows, unformatted_rows) - one
    entry per worksheet, in the order Google Sheets lists them. `formatted`
    mirrors what a person sees in the sheet (e.g. "4:30:00"); `unformatted`
    gives raw values (numbers as floats, which for a duration-formatted cell
    is an exact day-fraction, not rounded text).

    Raises SheetAccessError on any API failure (including exhausted retries
    on a persistent rate limit) so callers can show a per-hotel error
    instead of crashing the whole app.
    """
    try:
        client = _get_client()
        sh = client.open_by_key(sheet_id)
        worksheets = sh.worksheets()
        ranges = [f"'{ws.title}'" for ws in worksheets]

        formatted_all = _batch_get_with_retry(sh, ranges, "FORMATTED_VALUE")
        unformatted_all = _batch_get_with_retry(sh, ranges, "UNFORMATTED_VALUE")

        return [
            (ws.title, formatted_all[i] if i < len(formatted_all) else [], unformatted_all[i] if i < len(unformatted_all) else [])
            for i, ws in enumerate(worksheets)
        ]
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
