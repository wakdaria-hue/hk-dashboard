import plotly.express as px
import streamlit as st

from hk_dashboard.aggregations import by_week
from hk_dashboard.data import get_dashboard_data, render_coverage_sidebar
from hk_dashboard.excel_export import export_workbook

st.title("Per Week")
st.caption("Monday-start weeks, numbered 1-5 and restarting each month. First/last weeks of a month can be partial - the date range is always shown.")

load_result, rates_df, shifts = get_dashboard_data()
render_coverage_sidebar(load_result)

if shifts.empty:
    st.info("No data loaded yet.")
    st.stop()

hotels = sorted(shifts["hotel"].unique())
months = sorted(shifts["month"].unique())

col1, col2 = st.columns(2)
selected_hotels = col1.multiselect("Hotel", hotels, default=hotels)
selected_month = col2.selectbox("Month", months, index=len(months) - 1)

filtered = shifts[shifts["hotel"].isin(selected_hotels) & (shifts["month"] == selected_month)]

table = by_week(filtered)
table = table.rename(
    columns={
        "hotel": "Hotel",
        "month": "Month",
        "week_number": "Week #",
        "week_label": "Week",
        "hours": "Hours",
        "cost_eur": "Cost (EUR)",
        "hours_without_rate": "Hours w/o rate",
    }
)

if table.empty:
    st.info("No data for this selection.")
else:
    st.dataframe(
        table.drop(columns=["Month"]).style.format(
            {"Hours": "{:.1f}", "Cost (EUR)": "€{:.2f}", "Hours w/o rate": "{:.1f}"},
            na_rep="no rate available",
        ),
        use_container_width=True,
        hide_index=True,
    )

    chart_df = table.dropna(subset=["Cost (EUR)"])
    if not chart_df.empty:
        fig = px.bar(chart_df, x="Week", y="Cost (EUR)", color="Hotel", barmode="group", title=f"Cost per week - {selected_month}")
        st.plotly_chart(fig, use_container_width=True)

    st.download_button(
        "⬇️ Export this view to Excel",
        data=export_workbook(
            {
                "Per Week": {
                    "df": table,
                    "title": f"HK Cost per Week - {selected_month}",
                    "currency_cols": ("Cost (EUR)",),
                    "hours_cols": ("Hours", "Hours w/o rate"),
                }
            }
        ),
        file_name=f"hk_cost_per_week_{selected_month}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
