import streamlit as st

from hk_dashboard.aggregations import by_hotel_month, by_housekeeper, by_week
from hk_dashboard.data import get_dashboard_data, render_coverage_sidebar
from hk_dashboard.excel_export import export_workbook

st.title("Export")
st.caption("Download the full dataset (all hotels, all months currently loaded) as one styled Excel workbook.")

load_result, rates_df, shifts = get_dashboard_data()
render_coverage_sidebar(load_result)

if shifts.empty:
    st.info("No data loaded yet.")
    st.stop()

hotel_month = by_hotel_month(shifts).rename(
    columns={"hotel": "Hotel", "month": "Month", "hours": "Hours", "cost_eur": "Cost (EUR)", "hours_without_rate": "Hours w/o rate"}
)
week = by_week(shifts).rename(
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
housekeeper = by_housekeeper(shifts).rename(
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
daily_detail = shifts[
    ["hotel", "date", "employee", "hours", "hourly_rate_eur", "cost_eur", "rate_missing", "name_flagged"]
].rename(
    columns={
        "hotel": "Hotel",
        "date": "Date",
        "employee": "Housekeeper",
        "hours": "Hours",
        "hourly_rate_eur": "Rate (EUR/hr)",
        "cost_eur": "Cost (EUR)",
        "rate_missing": "No rate on file",
        "name_flagged": "Unmapped name",
    }
).sort_values(["Date", "Hotel", "Housekeeper"])

coverage_note = "Data coverage: " + "; ".join(
    f"{h} through {info['max_date']:%d %b %Y}" if info["max_date"] else f"{h}: unavailable"
    for h, info in load_result.coverage.items()
)

st.write(coverage_note)

workbook_bytes = export_workbook(
    {
        "Per Hotel": {
            "df": hotel_month,
            "title": "HK Cost per Hotel per Month",
            "subtitle": coverage_note,
            "currency_cols": ("Cost (EUR)",),
            "hours_cols": ("Hours", "Hours w/o rate"),
        },
        "Per Week": {
            "df": week.drop(columns=["Month"]),
            "title": "HK Cost per Week",
            "subtitle": coverage_note,
            "currency_cols": ("Cost (EUR)",),
            "hours_cols": ("Hours", "Hours w/o rate"),
        },
        "Per Housekeeper": {
            "df": housekeeper,
            "title": "HK Hours & Cost per Housekeeper",
            "subtitle": coverage_note,
            "currency_cols": ("Rate (EUR/hr)", "Cost (EUR)"),
            "hours_cols": ("Hours", "Avg hrs/day"),
        },
        "Daily Detail": {
            "df": daily_detail,
            "title": "Daily HK Shift Detail",
            "subtitle": coverage_note,
            "currency_cols": ("Rate (EUR/hr)", "Cost (EUR)"),
            "hours_cols": ("Hours",),
            "total_row": False,
        },
    }
)

st.download_button(
    "⬇️ Download full dataset (Excel)",
    data=workbook_bytes,
    file_name="hk_cost_dashboard_export.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    type="primary",
)
