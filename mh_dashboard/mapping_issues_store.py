"""Append-only log of raw schedule names that don't resolve via
employee_access (see mh_dashboard.aggregation.resolve_shifts). Written
quietly in the background on every parse so Daria can review and fix
employee_access without anything blocking the host-facing app.

Dedupes against what's already logged (by month_tab + raw_name), not just
within one run, so a cached re-parse every few minutes doesn't pile up
duplicate rows for the same unresolved name.
"""
from __future__ import annotations

from hk_dashboard.sheets_client import fetch_rate_store_worksheet
from hk_dashboard.timeutil import now_amsterdam
from mh_dashboard.config import MAPPING_ISSUES_HEADER, MAPPING_ISSUES_WORKSHEET
from mh_dashboard.parser import UnmappedName


def _ensure_header(ws) -> None:
    first_row = ws.row_values(1)
    if first_row != MAPPING_ISSUES_HEADER:
        ws.update("A1", [MAPPING_ISSUES_HEADER])


def log_unmapped_names(spreadsheet_id: str, unmapped: list[UnmappedName]) -> None:
    if not unmapped:
        return
    ws = fetch_rate_store_worksheet(spreadsheet_id, MAPPING_ISSUES_WORKSHEET)
    _ensure_header(ws)
    already_logged = {(row.get("month_tab"), row.get("raw_name")) for row in ws.get_all_records()}
    logged_at = now_amsterdam().isoformat(timespec="seconds")
    new_rows = [
        [logged_at, u.month_tab, u.raw_name]
        for u in unmapped
        if (u.month_tab, u.raw_name) not in already_logged
    ]
    if new_rows:
        ws.append_rows(new_rows)
