"""Login-free Mobile Host hours confirmation - a SEPARATE, public Streamlit
app, structured the same way as confirm/confirm_app.py (see README "Mobile
Host Hours Confirmation" section): its own subfolder with no pages/ sibling
(so no admin-only page can ever be reachable on this deployment's URL), its
own spreadsheet for identity/confirmation data, same service account.

Unlike the HK confirm app (daily, per-hotel), this is monthly and hotel-
agnostic - Mobile Hosts float between locations rather than being assigned
to one, so there's a single shared QR code/link and no hotel-selection step
(confirmed with Daria 2026-08-06).
"""
from __future__ import annotations

import calendar
import sys
from datetime import date
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root, for hk_dashboard/mh_dashboard

from hk_dashboard.lockout import check_lockout, record_failed_attempt, reset_attempts
from hk_dashboard.sheets_client import SheetAccessError, fetch_worksheet_values
from hk_dashboard.timeutil import now_amsterdam, today_amsterdam
from mh_dashboard.aggregation import monthly_summary, resolve_shifts, weeks_touching_month
from mh_dashboard.confirmation_store import ConfirmationWriteError, read_confirmations, upsert_confirmation
from mh_dashboard.config import (
    CONFIRM_WINDOW_FIRST_DAY,
    CONFIRM_WINDOW_LAST_DAY,
    EARLY_WINDOW_LAST_DAY,
    FIXED_WEEKLY_HOURS,
    LOCKOUT_SCOPE,
    MH_SCHEDULE_SPREADSHEET_ID,
)
from mh_dashboard.employee_access_store import active_full_names, birthdate_for, read_employee_access
from mh_dashboard.mapping_issues_store import log_unmapped_names
from mh_dashboard.parser import parse_month_tab

st.set_page_config(page_title="Confirm your hours", page_icon="🚐", layout="centered")

# Built from a fixed list rather than strftime("%B") so the tab name never
# depends on the server's locale - it must always match the sheet's English
# month tab names (e.g. "August 2026").
_MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


def _month_tab_for(d: date) -> str:
    return f"{_MONTH_NAMES[d.month - 1]} {d.year}"


def _fmt_date(d: date) -> str:
    return f"{d.day} {_MONTH_NAMES[d.month - 1][:3]}"


def _person_month(name: str, summary: dict, today: date) -> tuple[int, float, list[date]]:
    """(shift_count, total_hours, dates_worked) for this person this month -
    total_hours is overridden for anyone in FIXED_WEEKLY_HOURS, since their
    real schedule entries don't reflect their actual contracted hours."""
    person = summary.get(name)
    shift_count = person.shift_count if person else 0
    total_hours = person.total_hours if person else 0.0
    dates_worked = person.dates_worked if person else []
    fixed_weekly = FIXED_WEEKLY_HOURS.get(name)
    if fixed_weekly is not None:
        total_hours = fixed_weekly * weeks_touching_month(today.year, today.month)
    return shift_count, total_hours, dates_worked


def gating_status(today: date) -> str:
    if today.day <= EARLY_WINDOW_LAST_DAY:
        return "early"
    if CONFIRM_WINDOW_FIRST_DAY <= today.day <= CONFIRM_WINDOW_LAST_DAY:
        return "confirm"
    return "locked"


@st.cache_data(ttl=30, show_spinner=False)
def _cached_employee_access(spreadsheet_id: str):
    return read_employee_access(spreadsheet_id)


@st.cache_data(ttl=300, show_spinner="Loading this month's schedule...")
def _cached_month_summary(schedule_spreadsheet_id: str, confirmation_spreadsheet_id: str, month_tab: str):
    rows = fetch_worksheet_values(schedule_spreadsheet_id, month_tab)
    records = parse_month_tab(month_tab, rows)
    employee_access_df = read_employee_access(confirmation_spreadsheet_id)
    resolved, unmapped = resolve_shifts(records, employee_access_df, month_tab)
    log_unmapped_names(confirmation_spreadsheet_id, unmapped)
    return monthly_summary(resolved)


@st.cache_data(ttl=30, show_spinner=False)
def _cached_confirmations(spreadsheet_id: str):
    return read_confirmations(spreadsheet_id)


if "mh_confirmation_spreadsheet_id" not in st.secrets:
    # A plain message, not the admin app's stack-trace-flavored st.error -
    # this is a public, consumer-facing page.
    st.error("This page isn't set up yet. Please contact Daria.")
    st.stop()
spreadsheet_id = st.secrets["mh_confirmation_spreadsheet_id"]

state = st.session_state
state.setdefault("step", "pick_name")
state.setdefault("name", None)

st.title("🚐 Mobile Host")
st.caption("Confirm your hours")

# --- Step: pick name ------------------------------------------------------
if state["step"] == "pick_name":
    try:
        access_df = _cached_employee_access(spreadsheet_id)
    except SheetAccessError:
        st.error("Can't load the staff list right now — please try again in a minute.")
        st.stop()
    names = active_full_names(access_df)
    if not names:
        st.warning("No Mobile Hosts set up yet. Please contact Daria.")
        st.stop()

    choice = st.selectbox("What's your name?", ["-- select --"] + names)
    if st.button("I don't see my name"):
        st.info("Not found — please ask Daria to add you.")
    if choice != "-- select --" and st.button("Continue", type="primary"):
        state["name"] = choice
        state["step"] = "birthdate"
        st.rerun()
    st.stop()

name = state["name"]

# --- Step: birthdate check -------------------------------------------------
if state["step"] == "birthdate":
    locked_until = check_lockout(LOCKOUT_SCOPE, name)
    if locked_until:
        minutes_left = max(1, int((locked_until - now_amsterdam()).total_seconds() // 60) + 1)
        st.error(
            f"Too many wrong attempts. Please check with Daria, "
            f"or try again in about {minutes_left} minute(s)."
        )
        st.stop()

    st.subheader(f"Hi {name} — confirm your birthdate")
    c1, c2, c3 = st.columns(3)
    day_in = c1.number_input("Day", min_value=1, max_value=31, step=1, value=None, placeholder="DD")
    month_in = c2.number_input("Month", min_value=1, max_value=12, step=1, value=None, placeholder="MM")
    year_in = c3.number_input(
        "Year", min_value=1940, max_value=today_amsterdam().year, step=1, value=None, placeholder="YYYY"
    )

    if st.button("Continue", type="primary"):
        if day_in is None or month_in is None or year_in is None:
            st.warning("Please fill in all three fields.")
        else:
            try:
                entered = date(int(year_in), int(month_in), int(day_in))
            except ValueError:
                entered = None
            try:
                access_df = _cached_employee_access(spreadsheet_id)
            except SheetAccessError:
                st.error("Can't verify your birthdate right now — please try again in a minute.")
                st.stop()
            stored = birthdate_for(access_df, name)
            if entered is not None and stored and entered.isoformat() == stored:
                reset_attempts(LOCKOUT_SCOPE, name)
                state["step"] = "hours"
                st.rerun()
            else:
                record_failed_attempt(LOCKOUT_SCOPE, name)
                st.error("Birthdate doesn't match. Please try again.")
    st.stop()

today = today_amsterdam()
month_tab = _month_tab_for(today)
month_key = today.strftime("%Y-%m")
status = gating_status(today)

# --- Step: hours (gated by day of month) -----------------------------------
if state["step"] == "hours":
    st.subheader(f"Hi {name}")

    if status == "early":
        st.info("It's a bit too early. Come back between the 20th and the 23rd to confirm your hours.")
        st.stop()

    try:
        summary = _cached_month_summary(MH_SCHEDULE_SPREADSHEET_ID, spreadsheet_id, month_tab)
    except SheetAccessError:
        st.error("Can't load this month's schedule right now — please try again in a minute.")
        st.stop()
    shift_count, total_hours, dates_worked = _person_month(name, summary, today)
    is_fixed_hours = name in FIXED_WEEKLY_HOURS

    if status == "confirm":
        if shift_count == 0 and not is_fixed_hours:
            st.info("0 shifts, nothing to confirm. If this is not true, contact Chiara.")
            st.stop()

        if is_fixed_hours:
            st.metric("Total hours", f"{total_hours:.0f}h")
            st.caption("You're on a fixed 40h/week schedule.")
        else:
            st.metric("Shifts this month", shift_count)
            st.metric("Total hours", f"{total_hours:.0f}h")
            st.write("**Dates you worked:**")
            st.write(", ".join(_fmt_date(d) for d in dates_worked))

        c1, c2 = st.columns(2)
        if c1.button("✅ Yes, this is correct", type="primary", use_container_width=True):
            try:
                upsert_confirmation(
                    spreadsheet_id, month_key, name, "Confirmed",
                    shift_count, total_hours, dates_worked,
                )
            except ConfirmationWriteError:
                st.error("Couldn't save — please try again.")
                st.stop()
            _cached_confirmations.clear()
            state["last_status"] = "Confirmed"
            state["step"] = "done"
            st.rerun()
        if c2.button("❌ No, something is wrong", use_container_width=True):
            state["step"] = "dispute"
            st.rerun()
        st.stop()

    if status == "locked":
        st.warning("Your hours are already being processed for payroll. Your payslip is coming — hold tight.")
        if shift_count == 0 and not is_fixed_hours:
            st.info("0 shifts, nothing on file. If this is not true, contact Chiara.")
            st.stop()

        record = None
        try:
            confirmations_df = _cached_confirmations(spreadsheet_id)
        except SheetAccessError:
            confirmations_df = None
        if confirmations_df is not None and not confirmations_df.empty:
            match = confirmations_df[
                (confirmations_df["month"] == month_key) & (confirmations_df["full_name"] == name)
            ]
            if not match.empty:
                record = match.iloc[0]

        if record is not None:
            if not is_fixed_hours:
                st.metric("Shifts submitted", int(record["shift_count"]))
            st.metric("Total hours submitted", f"{float(record['total_hours']):.0f}h")
            st.caption(f"Status: {record['status']}")
            submitted_dates = str(record["dates_worked"] or "")
            if submitted_dates and not is_fixed_hours:
                parsed = [date.fromisoformat(s.strip()) for s in submitted_dates.split(",") if s.strip()]
                st.write("**Dates submitted:**")
                st.write(", ".join(_fmt_date(d) for d in parsed))
            if record["status"] == "Disputed" and record["comment"]:
                st.caption(f"Your note: {record['comment']}")
        else:
            if is_fixed_hours:
                st.metric("Total hours", f"{total_hours:.0f}h")
                st.caption("You're on a fixed 40h/week schedule.")
            else:
                st.metric("Shifts this month", shift_count)
                st.metric("Total hours", f"{total_hours:.0f}h")
                st.write("**Dates worked:**")
                st.write(", ".join(_fmt_date(d) for d in dates_worked))
            st.caption("You didn't confirm these during the window — contact Daria if this doesn't look right.")
        st.stop()

# --- Step: dispute (pick date(s) + comment) --------------------------------
if state["step"] == "dispute":
    try:
        summary = _cached_month_summary(MH_SCHEDULE_SPREADSHEET_ID, spreadsheet_id, month_tab)
    except SheetAccessError:
        st.error("Can't load this month's schedule right now — please try again in a minute.")
        st.stop()
    shift_count, total_hours, dates_worked = _person_month(name, summary, today)

    st.subheader("Which date(s) are wrong?")
    st.caption("Uncheck any date that's wrong, or add one that's missing, then tell us what happened.")

    days_in_month = calendar.monthrange(today.year, today.month)[1]
    all_dates = [date(today.year, today.month, d) for d in range(1, days_in_month + 1)]
    worked_set = set(dates_worked)

    picked = st.multiselect(
        "Dates",
        options=all_dates,
        default=dates_worked,
        format_func=lambda d: _fmt_date(d) + (" (on file)" if d in worked_set else ""),
    )
    comment = st.text_area("What's wrong? (optional but helpful)")

    if st.button("Submit", type="primary"):
        try:
            upsert_confirmation(
                spreadsheet_id, month_key, name, "Disputed",
                shift_count, total_hours, dates_worked,
                disputed_dates=picked, comment=comment,
            )
        except ConfirmationWriteError:
            st.error("Couldn't save — please try again.")
            st.stop()
        _cached_confirmations.clear()
        state["last_status"] = "Disputed"
        state["step"] = "done"
        st.rerun()
    if st.button("Back"):
        state["step"] = "hours"
        st.rerun()
    st.stop()

# --- Step: done -------------------------------------------------------
if state["step"] == "done":
    if state.get("last_status") == "Confirmed":
        st.success("Thanks! Your hours for this month are confirmed.")
    else:
        st.success("Got it — recorded your correction. Daria will review it.")
    if st.button("Done"):
        for key in ("step", "name", "last_status"):
            state.pop(key, None)
        st.rerun()
