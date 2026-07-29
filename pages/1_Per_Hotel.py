import plotly.express as px
import streamlit as st

from hk_dashboard.aggregations import by_hotel_day, by_hotel_month, by_week
from hk_dashboard.data import get_dashboard_data, render_coverage_sidebar
from hk_dashboard.excel_export import export_workbook

st.title("Per Hotel")

load_result, rates_df, shifts = get_dashboard_data()
render_coverage_sidebar(load_result)

if shifts.empty:
    st.info("No data loaded yet.")
    st.stop()

hotels = sorted(shifts["hotel"].unique())
months = sorted(shifts["month"].unique())

view_by = st.radio("View by", ["Month", "Week", "Day"], horizontal=True)
selected_hotels = st.multiselect("Hotel", hotels, default=hotels)

RENAME = {
    "hotel": "Hotel",
    "month": "Month",
    "date": "Date",
    "week_number": "Week #",
    "week_label": "Week",
    "hours": "Hours",
    "cost_eur": "Cost (EUR)",
    "hours_without_rate": "Hours w/o rate",
}
FMT = {"Hours": "{:.1f}", "Cost (EUR)": "€{:.2f}", "Hours w/o rate": "{:.1f}"}

if view_by == "Month":
    selected_months = st.multiselect("Month", months, default=months)
    filtered = shifts[shifts["hotel"].isin(selected_hotels) & shifts["month"].isin(selected_months)]
    table = by_hotel_month(filtered).rename(columns=RENAME)
    x_axis, chart_title, export_name = "Month", "Cost per hotel per month", "hk_cost_per_hotel_month.xlsx"

elif view_by == "Week":
    selected_month = st.selectbox("Month", months, index=len(months) - 1)
    filtered = shifts[shifts["hotel"].isin(selected_hotels) & (shifts["month"] == selected_month)]
    table = by_week(filtered).rename(columns=RENAME).drop(columns=["Month"])
    x_axis, chart_title, export_name = "Week", f"Cost per hotel per week - {selected_month}", f"hk_cost_per_hotel_week_{selected_month}.xlsx"

else:  # Day
    selected_month = st.selectbox("Month", months, index=len(months) - 1)
    filtered = shifts[shifts["hotel"].isin(selected_hotels)]
    table = by_hotel_day(filtered, selected_month).rename(columns=RENAME)
    x_axis, chart_title, export_name = "Date", f"Cost per hotel per day - {selected_month}", f"hk_cost_per_hotel_day_{selected_month}.xlsx"

if table.empty:
    st.info("No data for this selection yet.")
else:
    if "Hours w/o rate" in table.columns:
        flagged = table[table["Hours w/o rate"] > 0]
        if not flagged.empty:
            st.warning(
                f"⚠️ {len(flagged)} row(s) have hours with no matching payroll rate "
                "(cost shown is incomplete for those). See the 'Hours w/o rate' column."
            )

    st.dataframe(
        table.style.format(FMT, na_rep="no rate available"),
        use_container_width=True,
        hide_index=True,
    )

    chart_df = table.dropna(subset=["Cost (EUR)"])
    if not chart_df.empty:
        fig = px.bar(chart_df, x=x_axis, y="Cost (EUR)", color="Hotel", barmode="group", title=chart_title)
        st.plotly_chart(fig, use_container_width=True)

    st.download_button(
        "⬇️ Export this view to Excel",
        data=export_workbook(
            {
                "Per Hotel": {
                    "df": table,
                    "title": chart_title,
                    "currency_cols": ("Cost (EUR)",),
                    "hours_cols": ("Hours", "Hours w/o rate"),
                }
            }
        ),
        file_name=export_name,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
