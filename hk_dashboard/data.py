"""Shared, cached data-loading used by every page (so each page rerun doesn't
re-hit the Google Sheets / rate-store APIs)."""
from __future__ import annotations

import streamlit as st

from hk_dashboard.aggregations import LoadResult, attach_costs, load_all_hotel_shifts
from hk_dashboard.rate_store import read_rate_store
from hk_dashboard.self_report_store import read_self_reports
from hk_dashboard.staff_store import read_staff


@st.cache_data(ttl=600, show_spinner="Loading HK schedule data from Google Sheets...")
def _cached_load_shifts() -> LoadResult:
    return load_all_hotel_shifts()


@st.cache_data(ttl=600, show_spinner="Loading payroll rates...")
def _cached_load_rates(spreadsheet_id: str):
    return read_rate_store(spreadsheet_id)


@st.cache_data(ttl=600, show_spinner="Loading staff list...")
def _cached_load_staff(spreadsheet_id: str):
    return read_staff(spreadsheet_id)


@st.cache_data(ttl=30, show_spinner="Loading self-reported hours...")
def _cached_load_self_reports(spreadsheet_id: str):
    # Short TTL, unlike the 600s used elsewhere: the admin Hours Submission
    # page explicitly needs fresher data than the rest of the dashboard.
    return read_self_reports(spreadsheet_id)


def get_rate_store_id() -> str:
    if "rate_store_spreadsheet_id" not in st.secrets:
        st.error(
            "Missing secret `rate_store_spreadsheet_id`. Add it in "
            "Streamlit Cloud's Settings -> Secrets (see README)."
        )
        st.stop()
    return st.secrets["rate_store_spreadsheet_id"]


def get_confirmation_spreadsheet_id() -> str:
    if "confirmation_spreadsheet_id" not in st.secrets:
        st.error(
            "Missing secret `confirmation_spreadsheet_id`. Add it in "
            "Streamlit Cloud's Settings -> Secrets (see README)."
        )
        st.stop()
    return st.secrets["confirmation_spreadsheet_id"]


def get_raw_shifts():
    """Cached raw per-shift-row table (hotel, date, employee, start, end,
    hours, ...) - ungated by payroll upload, unlike get_dashboard_data()."""
    return _cached_load_shifts().shifts


def get_staff():
    """Cached staff-list read - see get_rates()'s docstring for why this
    matters (an uncached call fires on every widget rerun)."""
    return _cached_load_staff(get_confirmation_spreadsheet_id())


def get_self_reports():
    """Cached self-reports read (short TTL - see _cached_load_self_reports)."""
    return _cached_load_self_reports(get_confirmation_spreadsheet_id())


def clear_self_reports_cache():
    _cached_load_self_reports.clear()


def get_rates():
    """Cached rate-store read (shares the same cache as get_dashboard_data()).

    Use this instead of calling read_rate_store() directly on any page - an
    uncached call fires on every single widget interaction (a Streamlit
    rerun happens on every click, even just selecting a table row), which
    burns through the Sheets API's per-minute quota fast.
    """
    return _cached_load_rates(get_rate_store_id())


def get_dashboard_data():
    """Returns (LoadResult, rates_df, shifts_with_cost_df).

    shifts_with_cost only includes months that have at least one payroll row
    uploaded to the rate store - a month with no payroll uploaded yet (e.g.
    the current month, before that month's "Overzicht Loonkosten" PDF
    exists) is hidden everywhere rather than shown with blank costs. This is
    a deliberate choice: it's a monthly on/off switch, not per-person -
    external/agency workers (who are never in the payroll PDF) are still
    hidden for an unuploaded month along with everyone else, since the point
    is "this month isn't closed out yet", not "this specific rate is
    missing". load_result.coverage (the sidebar) is unaffected and still
    shows the sheets' true data range, so it's clear when new sheet data
    exists but its month's payroll just hasn't been uploaded yet.
    """
    spreadsheet_id = get_rate_store_id()
    load_result = _cached_load_shifts()
    rates_df = _cached_load_rates(spreadsheet_id)
    shifts_with_cost = attach_costs(load_result.shifts, rates_df)

    uploaded_months = set(rates_df["month"].unique()) if not rates_df.empty else set()
    if not shifts_with_cost.empty:
        shifts_with_cost = shifts_with_cost[shifts_with_cost["month"].isin(uploaded_months)]

    return load_result, rates_df, shifts_with_cost


def clear_cache():
    _cached_load_shifts.clear()
    _cached_load_rates.clear()
    _cached_load_staff.clear()
    _cached_load_self_reports.clear()


def render_coverage_sidebar(load_result: LoadResult) -> None:
    st.sidebar.subheader("Data coverage")
    st.sidebar.caption(
        "Dates below are what's in the schedule sheets. Views only show a "
        "month once that month's payroll PDF has been uploaded."
    )
    for hotel, info in load_result.coverage.items():
        if info["error"]:
            st.sidebar.error(f"**{hotel}**: unreachable\n\n{info['error']}")
        elif info["max_date"] is None:
            st.sidebar.warning(f"**{hotel}**: no shifts found")
        else:
            st.sidebar.caption(f"**{hotel}**: data through {info['max_date']:%d %b %Y}")

    if load_result.unmapped_names:
        unique_count = len({(u.hotel, u.raw_name) for u in load_result.unmapped_names})
        with st.sidebar.expander(
            f"⚠️ {unique_count} unmapped name(s) ({len(load_result.unmapped_names)} shift rows)",
            expanded=False,
        ):
            seen = {}
            for u in load_result.unmapped_names:
                seen.setdefault((u.hotel, u.raw_name), 0)
                seen[(u.hotel, u.raw_name)] += 1
            for (hotel, name), count in sorted(seen.items()):
                st.write(f"- **{name}** ({hotel}) - {count} shift row(s)")
            st.caption(
                "These names aren't in NAME_MAP and don't look like \"Initials Surname\". "
                "Their hours are still counted, but won't match a payroll rate until "
                "someone adds them to NAME_MAP in hk_dashboard/config.py."
            )

    if st.sidebar.button("🔄 Refresh data now"):
        clear_cache()
        st.rerun()
