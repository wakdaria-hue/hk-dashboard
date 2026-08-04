"""Login-free housekeeper hours confirmation - a SEPARATE, public Streamlit
app from app.py (see README "Confirmation app" section).

The main dashboard is Private on Streamlit Community Cloud, gated by a
Google-account allow-list - housekeepers have no accounts and can't be on
it, so this ships as its own deployment sharing the same hk_dashboard
package and GCP service account. QR codes printed per hotel encode this
app's URL as `?hotel=<code>` (see scripts/generate_qr_codes.py).

Deliberately lives in its own confirm/ subfolder, not the repo root:
Streamlit auto-adds every file under a `pages/` directory that's a SIBLING
of the entrypoint script as a directly-URL-addressable page, sidebar or
not. If this script sat next to the admin app's `pages/` folder, every
admin-only page (Staff Identity's birthdates, Hours Submission's dispute
data - both readable with only the confirmation_spreadsheet_id secret this
app already holds) would be reachable, unauthenticated, on this app's
public URL - hiding the sidebar link wouldn't stop someone typing the URL
directly. Being in a subfolder with no pages/ sibling means those routes
don't exist in this deployment at all.
"""
from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root, for `hk_dashboard`

from hk_dashboard.aggregations import load_all_hotel_shifts
from hk_dashboard.config import HOTEL_SHEETS
from hk_dashboard.lockout import check_lockout, record_failed_attempt, reset_attempts
from hk_dashboard.reception_hours import reception_hours_for
from hk_dashboard.self_report_store import (
    SelfReportWriteError,
    monthly_confirmed_hours,
    read_self_reports,
    upsert_self_report,
)
from hk_dashboard.sheets_client import SheetAccessError
from hk_dashboard.staff_store import active_staff_for_hotel
from hk_dashboard.timeutil import is_last_day_of_month, now_amsterdam, today_amsterdam

st.set_page_config(page_title="Confirm your hours", page_icon="✅", layout="centered")


@st.cache_data(ttl=300, show_spinner="Loading today's hours...")
def _cached_shifts():
    return load_all_hotel_shifts().shifts


@st.cache_data(ttl=30, show_spinner=False)
def _cached_staff(spreadsheet_id: str, hotel: str):
    return active_staff_for_hotel(spreadsheet_id, hotel)


@st.cache_data(ttl=30, show_spinner=False)
def _cached_self_reports(spreadsheet_id: str):
    return read_self_reports(spreadsheet_id)


if "confirmation_spreadsheet_id" not in st.secrets:
    # A plain message, not the admin app's stack-trace-flavored st.error -
    # this is a public, consumer-facing page.
    st.error("This page isn't set up yet. Please contact Daria.")
    st.stop()
spreadsheet_id = st.secrets["confirmation_spreadsheet_id"]

state = st.session_state
state.setdefault("step", "pick_name")
state.setdefault("hotel", None)
state.setdefault("name", None)

# --- Resolve hotel from the QR code's ?hotel= param, once per session ------
if state["hotel"] is None:
    query_hotel = st.query_params.get("hotel", "").upper()
    if query_hotel in HOTEL_SHEETS:
        state["hotel"] = query_hotel

if state["hotel"] is None:
    st.title("Which hotel are you at?")
    cols = st.columns(len(HOTEL_SHEETS))
    for col, hotel_code in zip(cols, HOTEL_SHEETS):
        if col.button(hotel_code, use_container_width=True):
            state["hotel"] = hotel_code
            st.rerun()
    st.stop()

hotel = state["hotel"]
st.title(f"🧹 {hotel}")
st.caption("Confirm your hours")


def _write_report(status: str, record, disputed_start="", disputed_end="", disputed_hours=None) -> bool:
    try:
        upsert_self_report(
            spreadsheet_id,
            date_=record.date,
            hotel=hotel,
            name=name,
            reception_hours_shown=record.display_range,
            reception_hours_numeric=record.hours,
            status=status,
            disputed_start=disputed_start,
            disputed_end=disputed_end,
            disputed_hours_numeric=disputed_hours,
        )
    except SelfReportWriteError:
        st.error("Couldn't save — please try again.")
        return False
    _cached_self_reports.clear()
    return True


# --- Step: pick name ---------------------------------------------------
if state["step"] == "pick_name":
    try:
        staff_df = _cached_staff(spreadsheet_id, hotel)
    except SheetAccessError:
        st.error("Can't load the staff list right now — please try again in a minute.")
        st.stop()
    if staff_df.empty:
        st.warning("No staff set up for this hotel yet. Please contact Daria.")
        st.stop()

    choice = st.selectbox("What's your name?", ["-- select --"] + staff_df["name"].tolist())
    if st.button("I don't see my name"):
        st.info("Not found — please ask Daria to add you.")
    if choice != "-- select --" and st.button("Continue", type="primary"):
        state["name"] = choice
        state["step"] = "birthdate"
        st.rerun()
    st.stop()

name = state["name"]

# --- Step: birthdate check ----------------------------------------------
if state["step"] == "birthdate":
    locked_until = check_lockout(hotel, name)
    if locked_until:
        minutes_left = max(1, int((locked_until - now_amsterdam()).total_seconds() // 60) + 1)
        st.error(
            f"Too many wrong attempts. Please check with Daria, "
            f"or try again in about {minutes_left} minute(s)."
        )
        st.stop()

    st.subheader(f"Hi {name} — confirm your birthdate")
    c1, c2, c3 = st.columns(3)
    day = c1.number_input("Day", min_value=1, max_value=31, step=1, value=None, placeholder="DD")
    month = c2.number_input("Month", min_value=1, max_value=12, step=1, value=None, placeholder="MM")
    year = c3.number_input(
        "Year", min_value=1940, max_value=today_amsterdam().year, step=1, value=None, placeholder="YYYY"
    )

    if st.button("Continue", type="primary"):
        if day is None or month is None or year is None:
            st.warning("Please fill in all three fields.")
        else:
            try:
                entered = date(int(year), int(month), int(day))
            except ValueError:
                entered = None
            try:
                staff_df = _cached_staff(spreadsheet_id, hotel)
            except SheetAccessError:
                st.error("Can't verify your birthdate right now — please try again in a minute.")
                st.stop()
            row = staff_df[staff_df["name"] == name]
            stored = row.iloc[0]["birthdate"] if not row.empty else None
            if entered is not None and stored and entered.isoformat() == str(stored):
                reset_attempts(hotel, name)
                state["step"] = "show_hours"
                st.rerun()
            else:
                record_failed_attempt(hotel, name)
                st.error("Birthdate doesn't match. Please try again.")
    st.stop()

# --- Step: show today's hours --------------------------------------------
if state["step"] == "show_hours":
    st.subheader(f"Hi {name}")
    try:
        shifts = _cached_shifts()
    except SheetAccessError:
        st.error("Can't load today's hours right now — please try again in a minute.")
        st.stop()
    record = reception_hours_for(shifts, hotel, name, today_amsterdam())

    if record is None:
        st.info(
            "No hours logged for you today yet. If you've already worked, "
            "check back after your shift — or if today's a day off, no action needed."
        )
        st.stop()

    st.metric("Today's hours", f"{record.hours:.1f}h")
    st.caption(record.display_range)

    c1, c2 = st.columns(2)
    if c1.button("✅ Yes, correct", type="primary", use_container_width=True):
        if _write_report("Confirmed", record):
            state["last_status"] = "Confirmed"
            state["last_hours"] = record.hours
            state["last_date"] = record.date
            state["step"] = "done"
            st.rerun()
    if c2.button("❌ No, wrong", use_container_width=True):
        state["step"] = "dispute"
        st.rerun()
    st.stop()

# --- Step: dispute (claimed start/end instead of typing free text) --------
if state["step"] == "dispute":
    try:
        shifts = _cached_shifts()
    except SheetAccessError:
        st.error("Can't load today's hours right now — please try again in a minute.")
        st.stop()
    record = reception_hours_for(shifts, hotel, name, today_amsterdam())
    if record is None:
        st.error("Couldn't find today's hours anymore — please start over.")
        if st.button("Start over"):
            state["step"] = "show_hours"
            st.rerun()
        st.stop()

    st.subheader("What should your hours have been?")
    c1, c2 = st.columns(2)
    start_t = c1.time_input("Start", value=None)
    end_t = c2.time_input("End", value=None)

    if st.button("Submit", type="primary"):
        if start_t is None or end_t is None:
            st.warning("Please fill in both times.")
        else:
            claimed_hours = (datetime.combine(date.min, end_t) - datetime.combine(date.min, start_t)).total_seconds() / 3600
            if claimed_hours < 0:  # shift crossing midnight
                claimed_hours += 24
            if _write_report(
                "Disputed",
                record,
                disputed_start=start_t.strftime("%H:%M"),
                disputed_end=end_t.strftime("%H:%M"),
                disputed_hours=claimed_hours,
            ):
                state["last_status"] = "Disputed"
                state["last_hours"] = claimed_hours
                state["last_date"] = record.date
                state["step"] = "done"
                st.rerun()
    st.stop()

# --- Step: done, + month-end popup ---------------------------------------
if state["step"] == "done":
    if state["last_status"] == "Confirmed":
        st.success(f"Thanks! Confirmed {state['last_hours']:.1f}h for today.")
    else:
        st.success(f"Got it — recorded your correction ({state['last_hours']:.1f}h). Daria will review it.")

    if is_last_day_of_month(state["last_date"]):
        month = f"{state['last_date'].year:04d}-{state['last_date'].month:02d}"
        total = monthly_confirmed_hours(_cached_self_reports(spreadsheet_id), hotel, name, month)
        st.info(
            f"📅 Your self-reported total for {month}: **{total:.1f}h** "
            "(this is your own count, not an official payroll figure)."
        )

    if st.button("Done"):
        for key in ("step", "hotel", "name", "last_status", "last_hours", "last_date"):
            state.pop(key, None)
        st.query_params.clear()
        st.rerun()
