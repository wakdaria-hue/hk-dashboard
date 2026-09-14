import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from hk_dashboard.aggregations import trend_by_month
from hk_dashboard.data import (
    get_assignments,
    get_dashboard_data,
    get_occupancy,
    get_raw_shifts,
    get_settings,
    render_coverage_sidebar,
)
from hk_dashboard.excel_export import export_workbook
from hk_dashboard.golden_time import assignment_comparison, golden_by_month, golden_line
from hk_dashboard.sheets_client import SheetAccessError

st.title("Trends")
st.caption("Cost and hours over time (month over month), against the golden-time target.")

load_result, rates_df, shifts = get_dashboard_data()
render_coverage_sidebar(load_result)

if shifts.empty:
    st.info("No data loaded yet.")
    st.stop()

hotels = ["All hotels"] + sorted(shifts["hotel"].unique())
employees = ["All housekeepers"] + sorted(shifts["employee"].unique())

col1, col2 = st.columns(2)
selected_hotel = col1.selectbox("Hotel", hotels)
selected_employee = col2.selectbox("Housekeeper", employees)

hotel_filter = None if selected_hotel == "All hotels" else selected_hotel
employee_filter = None if selected_employee == "All housekeepers" else selected_employee

table = trend_by_month(shifts, hotel=hotel_filter, employee=employee_filter)
table = table.rename(columns={"month": "Month", "hours": "Hours", "cost_eur": "Cost (EUR)"})

if table.empty:
    st.info("No data for this selection.")
else:
    # The golden target line: what these months would have cost if every room
    # hit golden time. Only meaningful for a hotel-level (or portfolio) view -
    # a single housekeeper's share of a hotel's target isn't defined, so it's
    # left off rather than approximated when one person is selected.
    golden_months = pd.DataFrame()
    uncovered_hotels: set[str] = set()
    if employee_filter is None:
        try:
            occupancy = get_occupancy()
            assignments = get_assignments()
            settings_df = get_settings()
        except SheetAccessError:
            occupancy = assignments = settings_df = pd.DataFrame()

        if not occupancy.empty or not assignments.empty:
            comparison = assignment_comparison(assignments, get_raw_shifts(), settings_df)
            headcount = (
                shifts.groupby(["hotel", "date"])["employee"].nunique().to_dict()
                if not shifts.empty
                else {}
            )
            blended = {}
            for hotel_code, group in shifts.groupby("hotel"):
                rated = group[~group["rate_missing"]]
                if not rated.empty and rated["hours"].sum() > 0:
                    blended[hotel_code] = rated["cost_eur"].sum() / rated["hours"].sum()
            golden_df = golden_line(
                comparison, occupancy, settings_df, blended, headcount_by_hotel_day=headcount
            )
            golden_months = golden_by_month(golden_df, hotel=hotel_filter)
            # A target is only comparable to an actual if it covers the same
            # hotels. The actual line here is every hotel in scope, so a month
            # where only some of them have room data would draw a target far
            # below actual for no reason other than missing data - worse than
            # showing nothing. Keep only months where every in-scope hotel is
            # covered, and say which ones aren't.
            scope_hotels = (
                {hotel_filter} if hotel_filter else set(shifts["hotel"].dropna().unique())
            )
            covered_by_month = (
                golden_df.groupby("month")["hotel"].apply(set) if not golden_df.empty else {}
            )
            complete_months = {
                month for month, hotels_covered in dict(covered_by_month).items()
                if scope_hotels <= hotels_covered
            }
            uncovered_hotels = scope_hotels - set(golden_df["hotel"].unique() if not golden_df.empty else [])
            if not golden_months.empty:
                golden_months = golden_months[
                    golden_months["month"].isin(set(table["Month"]) & complete_months)
                ]

    tab1, tab2 = st.tabs(["Cost over time", "Hours over time"])
    with tab1:
        fig = px.line(table, x="Month", y="Cost (EUR)", markers=True, title="Cost by month")
        fig.data[0].name = "Actual"
        fig.data[0].showlegend = True
        if not golden_months.empty:
            fig.add_trace(
                go.Scatter(
                    x=golden_months["month"],
                    y=golden_months["golden_cost_eur"],
                    mode="lines+markers",
                    name="Golden target",
                    line=dict(dash="dash", width=2),
                    marker=dict(symbol="diamond", size=7),
                )
            )
        st.plotly_chart(fig, use_container_width=True)
    with tab2:
        fig2 = px.line(table, x="Month", y="Hours", markers=True, title="Hours by month")
        fig2.data[0].name = "Actual"
        fig2.data[0].showlegend = True
        if not golden_months.empty:
            fig2.add_trace(
                go.Scatter(
                    x=golden_months["month"],
                    y=golden_months["golden_hours"],
                    mode="lines+markers",
                    name="Golden target",
                    line=dict(dash="dash", width=2),
                    marker=dict(symbol="diamond", size=7),
                )
            )
        st.plotly_chart(fig2, use_container_width=True)

    if not golden_months.empty:
        st.caption(
            "The dashed **Golden target** is neither an actual nor a forecast - it's what "
            "these months would have cost if every room hit golden time, using logged room "
            "assignments where they exist and Mews rooms-to-clean otherwise. Change the "
            "targets on the **Room Assignments** page."
        )
    elif employee_filter is not None:
        st.caption(
            "The golden target line is shown for hotel and portfolio views only - one "
            "housekeeper's share of a hotel-level target isn't defined."
        )
    elif uncovered_hotels:
        missing = ", ".join(sorted(uncovered_hotels))
        st.caption(
            f"**No golden target line shown.** {missing} have no room data yet (no Mews "
            "occupancy uploaded and no logged assignments), so a target covering only the "
            "remaining hotel(s) would sit far below this actual purely because of missing "
            "data, not performance. Pick a single hotel that does have data, or upload the "
            "rest on **Occupancy Forecast Upload**."
        )

    st.dataframe(
        table.style.format({"Hours": "{:.1f}", "Cost (EUR)": "€{:.2f}"}, na_rep="no rate available"),
        use_container_width=True,
        hide_index=True,
    )

    st.download_button(
        "⬇️ Export this view to Excel",
        data=export_workbook(
            {
                "Trends": {
                    "df": table,
                    "title": f"HK Trend - {selected_hotel} / {selected_employee}",
                    "currency_cols": ("Cost (EUR)",),
                    "hours_cols": ("Hours",),
                }
            }
        ),
        file_name="hk_trends.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
