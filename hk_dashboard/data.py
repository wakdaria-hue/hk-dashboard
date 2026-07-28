"""Shared, cached data-loading used by every page (so each page rerun doesn't
re-hit the Google Sheets / rate-store APIs)."""
from __future__ import annotations

import streamlit as st

from hk_dashboard.aggregations import LoadResult, attach_costs, load_all_hotel_shifts
from hk_dashboard.rate_store import read_rate_store


@st.cache_data(ttl=600, show_spinner="Loading HK schedule data from Google Sheets...")
def _cached_load_shifts() -> LoadResult:
    return load_all_hotel_shifts()


@st.cache_data(ttl=600, show_spinner="Loading payroll rates...")
def _cached_load_rates(spreadsheet_id: str):
    return read_rate_store(spreadsheet_id)


def get_rate_store_id() -> str:
    if "rate_store_spreadsheet_id" not in st.secrets:
        st.error(
            "Missing secret `rate_store_spreadsheet_id`. Add it in "
            "Streamlit Cloud's Settings -> Secrets (see README)."
        )
        st.stop()
    return st.secrets["rate_store_spreadsheet_id"]


def get_dashboard_data():
    """Returns (LoadResult, rates_df, shifts_with_cost_df)."""
    spreadsheet_id = get_rate_store_id()
    load_result = _cached_load_shifts()
    rates_df = _cached_load_rates(spreadsheet_id)
    shifts_with_cost = attach_costs(load_result.shifts, rates_df)
    return load_result, rates_df, shifts_with_cost


def clear_cache():
    _cached_load_shifts.clear()
    _cached_load_rates.clear()


def render_coverage_sidebar(load_result: LoadResult) -> None:
    st.sidebar.subheader("Data coverage")
    for hotel, info in load_result.coverage.items():
        if info["error"]:
            st.sidebar.error(f"**{hotel}**: unreachable\n\n{info['error']}")
        elif info["max_date"] is None:
            st.sidebar.warning(f"**{hotel}**: no shifts found")
        else:
            st.sidebar.caption(f"**{hotel}**: data through {info['max_date']:%d %b %Y}")

    if load_result.unmapped_names:
        with st.sidebar.expander(f"⚠️ {len(load_result.unmapped_names)} unmapped name(s)", expanded=False):
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
