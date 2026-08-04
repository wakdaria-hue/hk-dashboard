"""Amsterdam-local "today" - never bare date.today()/datetime.now().

Streamlit Community Cloud runs on UTC. The confirmation feature shows
"today's hours" and fires a month-end popup based on calendar-day boundaries
that only make sense in the hotels' actual local time; a bare UTC "today"
would be wrong for part of each day around the CET/CEST transition.
"""
from __future__ import annotations

import calendar
from datetime import date, datetime
from zoneinfo import ZoneInfo

from hk_dashboard.config import APP_TIMEZONE

_TZ = ZoneInfo(APP_TIMEZONE)


def now_amsterdam() -> datetime:
    return datetime.now(_TZ)


def today_amsterdam() -> date:
    return now_amsterdam().date()


def is_last_day_of_month(d: date) -> bool:
    return d.day == calendar.monthrange(d.year, d.month)[1]
