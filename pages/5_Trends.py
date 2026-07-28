import plotly.express as px
import streamlit as st

from hk_dashboard.aggregations import trend_by_month
from hk_dashboard.data import get_dashboard_data, render_coverage_sidebar
from hk_dashboard.excel_export import export_workbook

st.title("Trends")
st.caption("Cost and hours over time (month over month).")

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
    tab1, tab2 = st.tabs(["Cost over time", "Hours over time"])
    with tab1:
        fig = px.line(table, x="Month", y="Cost (EUR)", markers=True, title="Cost by month")
        st.plotly_chart(fig, use_container_width=True)
    with tab2:
        fig2 = px.line(table, x="Month", y="Hours", markers=True, title="Hours by month")
        st.plotly_chart(fig2, use_container_width=True)

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
