"""Shared birthdate parsing for the HK and MH confirmation stores.

Birthdates reach these sheets two ways: written by the app itself (always
ISO `YYYY-MM-DD`, via `date.isoformat()`), or typed by hand directly into
Google Sheets (staff_store.py / mh_dashboard.employee_access_store.py are
both explicit that Daria maintains rows this way). Google Sheets
auto-detects a hand-typed date and displays it in the sheet's locale format
- Netherlands locale renders that as `DD-MM-YYYY`, e.g. "16-03-1985" - not
ISO. Reading that raw string back and comparing it against
`entered.isoformat()` byte-for-byte then fails for every correct entry.
"""
from __future__ import annotations

from datetime import date, datetime

_FORMATS = ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y")


def parse_birthdate(raw) -> date | None:
    text = str(raw).strip() if raw is not None else ""
    if not text:
        return None
    for fmt in _FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None
