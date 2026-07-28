import plotly.express as px
import streamlit as st

from hk_dashboard.aggregations import by_hotel_month
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

col1, col2 = st.columns(2)
selected_hotels = col1.multiselect("Hotel", hotels, default=hotels)
selected_months = col2.multiselect("Month", months, default=months)

filtered = shifts[shifts["hotel"].isin(selected_hotels) & shifts["month"].isin(selected_months)]

table = by_hotel_month(filtered)
table = table.rename(
    columns={
        "hotel": "Hotel",
        "month": "Month",
        "hours": "Hours",
        "cost_eur": "Cost (EUR)",
        "hours_without_rate": "Hours w/o rate",
    }
)

if table.empty:
    st.info("No data for this selection.")
else:
    flagged = table[table["Hours w/o rate"] > 0]
    if not flagged.empty:
        st.warning(
            f"⚠️ {len(flagged)} hotel/month row(s) have hours with no matching payroll rate "
            "(cost shown is incomplete for those). See the 'Hours w/o rate' column."
        )

    st.dataframe(
        table.style.format(
            {"Hours": "{:.1f}", "Cost (EUR)": "€{:.2f}", "Hours w/o rate": "{:.1f}"},
            na_rep="no rate available",
        ),
        use_container_width=True,
        hide_index=True,
    )

    chart_df = table.dropna(subset=["Cost (EUR)"])
    if not chart_df.empty:
        fig = px.bar(chart_df, x="Month", y="Cost (EUR)", color="Hotel", barmode="group", title="Cost per hotel per month")
        st.plotly_chart(fig, use_container_width=True)

    st.download_button(
        "⬇️ Export this view to Excel",
        data=export_workbook(
            {
                "Per Hotel": {
                    "df": table,
                    "title": "HK Cost per Hotel per Month",
                    "currency_cols": ("Cost (EUR)",),
                    "hours_cols": ("Hours", "Hours w/o rate"),
                }
            }
        ),
        file_name="hk_cost_per_hotel.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
