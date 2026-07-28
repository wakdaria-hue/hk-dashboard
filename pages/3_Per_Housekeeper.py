import streamlit as st

from hk_dashboard.aggregations import by_housekeeper
from hk_dashboard.data import get_dashboard_data, render_coverage_sidebar
from hk_dashboard.excel_export import export_workbook

st.title("Per Housekeeper")

load_result, rates_df, shifts = get_dashboard_data()
render_coverage_sidebar(load_result)

if shifts.empty:
    st.info("No data loaded yet.")
    st.stop()

hotels = sorted(shifts["hotel"].unique())
months = sorted(shifts["month"].unique())
employees = sorted(shifts["employee"].unique())

col1, col2, col3 = st.columns(3)
selected_hotels = col1.multiselect("Hotel", hotels, default=hotels)
selected_months = col2.multiselect("Month", months, default=months)
selected_employees = col3.multiselect("Housekeeper", employees, default=[])

filtered = shifts[shifts["hotel"].isin(selected_hotels) & shifts["month"].isin(selected_months)]
if selected_employees:
    filtered = filtered[filtered["employee"].isin(selected_employees)]

table = by_housekeeper(filtered)
table = table.rename(
    columns={
        "employee": "Housekeeper",
        "hotel": "Hotel",
        "month": "Month",
        "hours": "Hours",
        "days_worked": "Days worked",
        "avg_hours_per_day": "Avg hrs/day",
        "hourly_rate_eur": "Rate (EUR/hr)",
        "cost_eur": "Cost (EUR)",
        "rate_missing": "No rate on file",
    }
)

if table.empty:
    st.info("No data for this selection.")
else:
    no_rate = table[table["No rate on file"]]
    if not no_rate.empty:
        st.warning(
            f"⚠️ {len(no_rate)} housekeeper/hotel/month row(s) have no matching payroll rate "
            "- their cost shows blank rather than a guessed number."
        )

    st.dataframe(
        table.style.format(
            {
                "Hours": "{:.1f}",
                "Avg hrs/day": "{:.2f}",
                "Rate (EUR/hr)": "€{:.2f}",
                "Cost (EUR)": "€{:.2f}",
            },
            na_rep="no rate available",
        ),
        use_container_width=True,
        hide_index=True,
    )

    st.download_button(
        "⬇️ Export this view to Excel",
        data=export_workbook(
            {
                "Per Housekeeper": {
                    "df": table,
                    "title": "HK Hours & Cost per Housekeeper",
                    "currency_cols": ("Rate (EUR/hr)", "Cost (EUR)"),
                    "hours_cols": ("Hours", "Avg hrs/day"),
                }
            }
        ),
        file_name="hk_cost_per_housekeeper.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
