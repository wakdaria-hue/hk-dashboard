import streamlit as st

from hk_dashboard.aggregations import (
    attach_netto_salary,
    by_housekeeper,
    by_housekeeper_day,
    by_housekeeper_week,
)
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

view_by = st.radio("View by", ["Month", "Week", "Day"], horizontal=True)

RENAME = {
    "employee": "Housekeeper",
    "hotel": "Hotel",
    "month": "Month",
    "date": "Date",
    "week_number": "Week #",
    "week_label": "Week",
    "hours": "Hours",
    "days_worked": "Days worked",
    "avg_hours_per_day": "Avg hrs/day",
    "hourly_rate_eur": "Rate (EUR/hr)",
    "cost_eur": "Cost (EUR)",
    "netto_salary_eur": "Net Salary (EUR)",
    "rate_missing": "No rate on file",
    "is_external_rate": "External (flat rate)",
}
CURRENCY_COLS = ["Rate (EUR/hr)", "Cost (EUR)"]
HOURS_COLS = ["Hours"]

if view_by == "Month":
    col1, col2, col3 = st.columns(3)
    selected_hotels = col1.multiselect("Hotel", hotels, default=hotels)
    selected_months = col2.multiselect("Month", months, default=months)
    selected_employees = col3.multiselect("Housekeeper", employees, default=[])

    filtered = shifts[shifts["hotel"].isin(selected_hotels) & shifts["month"].isin(selected_months)]
    if selected_employees:
        filtered = filtered[filtered["employee"].isin(selected_employees)]

    table = attach_netto_salary(by_housekeeper(filtered), rates_df).rename(columns=RENAME)
    CURRENCY_COLS.append("Net Salary (EUR)")
    HOURS_COLS.append("Avg hrs/day")
    export_name = "hk_cost_per_housekeeper_month.xlsx"

elif view_by == "Week":
    col1, col2, col3 = st.columns(3)
    selected_hotels = col1.multiselect("Hotel", hotels, default=hotels)
    selected_month = col2.selectbox("Month", months, index=len(months) - 1)
    selected_employees = col3.multiselect("Housekeeper", employees, default=[])

    filtered = shifts[shifts["hotel"].isin(selected_hotels)]
    if selected_employees:
        filtered = filtered[filtered["employee"].isin(selected_employees)]

    table = by_housekeeper_week(filtered, selected_month).rename(columns=RENAME)
    export_name = f"hk_cost_per_housekeeper_week_{selected_month}.xlsx"

else:  # Day
    col1, col2, col3 = st.columns(3)
    selected_hotels = col1.multiselect("Hotel", hotels, default=hotels)
    selected_month = col2.selectbox("Month", months, index=len(months) - 1)
    selected_employees = col3.multiselect("Housekeeper", employees, default=[])

    filtered = shifts[shifts["hotel"].isin(selected_hotels)]
    if selected_employees:
        filtered = filtered[filtered["employee"].isin(selected_employees)]

    table = by_housekeeper_day(filtered, selected_month).rename(columns=RENAME)
    export_name = f"hk_cost_per_housekeeper_day_{selected_month}.xlsx"

if table.empty:
    st.info("No data for this selection yet.")
else:
    if "No rate on file" in table.columns:
        no_rate = table[table["No rate on file"]]
        if not no_rate.empty:
            st.warning(
                f"⚠️ {len(no_rate)} row(s) have no matching payroll rate "
                "- their cost shows blank rather than a guessed number."
            )

    if "External (flat rate)" in table.columns:
        external_rows = table[table["External (flat rate)"]]
        if not external_rows.empty:
            st.info(
                f"ℹ️ {len(external_rows)} row(s) belong to external/agency staff paid directly by the "
                "hotel (not through this payroll system) - their cost uses a fixed assumed rate, not a "
                "verified payroll figure. See EXTERNAL_WORKER_RATES in hk_dashboard/config.py."
            )

    fmt = {c: "{:.1f}" for c in HOURS_COLS if c in table.columns}
    fmt.update({c: "€{:.2f}" for c in CURRENCY_COLS if c in table.columns})
    st.dataframe(
        table.style.format(fmt, na_rep="no rate available"),
        use_container_width=True,
        hide_index=True,
    )

    st.download_button(
        "⬇️ Export this view to Excel",
        data=export_workbook(
            {
                "Per Housekeeper": {
                    "df": table,
                    "title": f"HK Hours & Cost per Housekeeper ({view_by})",
                    "currency_cols": tuple(c for c in CURRENCY_COLS if c in table.columns),
                    "hours_cols": tuple(c for c in HOURS_COLS if c in table.columns),
                }
            }
        ),
        file_name=export_name,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
