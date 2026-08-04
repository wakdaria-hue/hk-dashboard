"""In-memory birthdate-attempt lockout for confirm_app.py.

Deliberately not persisted to a sheet - this is low-stakes and transient (a
wrong-birthdate cooldown, not a security boundary), so a Streamlit
redeploy/sleep wiping it is an acceptable tradeoff for not needing an extra
Sheets read/write on every single attempt.

st.cache_resource returns the SAME dict across every user/session hitting
this process (unlike st.session_state, which is per-browser-tab) - that's
what we want here: the cooldown must apply per (hotel, name) regardless of
who's holding the phone, not just the current tab.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import streamlit as st

from hk_dashboard.config import LOCKOUT_MAX_ATTEMPTS, LOCKOUT_MINUTES
from hk_dashboard.timeutil import now_amsterdam


@dataclass
class LockoutEntry:
    fail_count: int = 0
    locked_until: datetime | None = None


@st.cache_resource
def _lockout_store() -> dict[tuple[str, str], LockoutEntry]:
    return {}


def check_lockout(hotel: str, name: str) -> datetime | None:
    """Returns locked_until if currently locked, else None."""
    entry = _lockout_store().get((hotel, name))
    if entry and entry.locked_until and now_amsterdam() < entry.locked_until:
        return entry.locked_until
    return None


def record_failed_attempt(hotel: str, name: str) -> None:
    store = _lockout_store()
    entry = store.setdefault((hotel, name), LockoutEntry())
    entry.fail_count += 1
    if entry.fail_count >= LOCKOUT_MAX_ATTEMPTS:
        entry.locked_until = now_amsterdam() + timedelta(minutes=LOCKOUT_MINUTES)


def reset_attempts(hotel: str, name: str) -> None:
    _lockout_store().pop((hotel, name), None)
