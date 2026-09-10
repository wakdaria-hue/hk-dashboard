import streamlit as st

from hk_dashboard.aggregations import by_hotel_month, by_housekeeper, by_week
from hk_dashboard.config import DEFAULT_BASELINE_WINDOW_DAYS
from hk_dashboard.data import get_dashboard_data, get_occupancy, render_coverage_sidebar
from hk_dashboard.excel_export import export_workbook
from hk_dashboard.forecast import baselines_to_df, build_forecast, compute_baselines
from hk_dashboard.sheets_client import SheetAccessError
from hk_dashboard.timeutil import today_amsterdam

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

# Forecasts go on their own sheets, never mixed into the actuals above.
forecast_sheets = {}
try:
    occupancy = get_occupancy()
except SheetAccessError as e:
    occupancy = None
    st.warning(f"⚠️ Forecast sheets left out - couldn't reach the occupancy store: {e}")

if occupancy is not None and not occupancy.empty:
    today = today_amsterdam()
    baselines = compute_baselines(
        shifts, occupancy, today=today, window_days=DEFAULT_BASELINE_WINDOW_DAYS
    )
    forecast = build_forecast(occupancy, baselines, today=today)
    if not forecast.empty:
        forecast_table = forecast.rename(
            columns={
                "hotel": "Hotel",
                "date": "Date",
                "month": "Month",
                "week_label": "Week",
                "rooms_to_clean": "Predicted rooms to clean",
                "predicted_hours": "Predicted hours",
                "predicted_cost_eur": "Predicted cost (EUR)",
                "minutes_per_room": "Min/room used",
                "blended_hourly_rate": "Blended rate used (EUR/hr)",
                "report_created": "Mews export created",
                "basis": "Basis",
            }
        ).drop(columns=["week_number"])
        forecast_sheets = {
            "Forecast (Daily)": {
                "df": forecast_table,
                "title": "FORECAST - predicted cleaning hours & cost per day",
                "subtitle": (
                    "Forecasted figures, not verified actuals. Predicted rooms come from an "
                    "uploaded Mews Availability report; hours and cost apply the historical "
                    f"baseline over the last {DEFAULT_BASELINE_WINDOW_DAYS} days."
                ),
                "currency_cols": ("Predicted cost (EUR)", "Blended rate used (EUR/hr)"),
                "hours_cols": ("Predicted hours",),
                "total_row": False,
            },
            "Forecast Baseline": {
                "df": baselines_to_df(baselines).rename(
                    columns={
                        "hotel": "Hotel",
                        "window": "Window used",
                        "days_matched": "Days matched",
                        "hours_in_window": "Hours (actual)",
                        "rooms_in_window": "Rooms (actual)",
                        "minutes_per_room": "Min/room",
                        "blended_hourly_rate": "Blended rate (EUR/hr)",
                        "hours_without_rate": "Hours w/o rate",
                        "solo_minutes_per_room": "Min/room (solo days)",
                        "solo_days": "Solo days",
                        "typical_shift_hours": "Typical shift (hrs)",
                        "note": "Note",
                    }
                ),
                "title": "Forecast baseline (from historical actuals)",
                "subtitle": (
                    "What produced every forecast figure. Min/room is team-wide; the solo-day "
                    "column is one person's measured throughput, used only for staffing estimates."
                ),
                "currency_cols": ("Blended rate (EUR/hr)",),
                "hours_cols": ("Hours (actual)", "Hours w/o rate", "Typical shift (hrs)"),
                "total_row": False,
            },
        }
        st.caption(
            f"Includes {len(forecast_table)} forecasted day(s) on separate 'Forecast' sheets, "
            "kept out of the historical actuals."
        )

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
        **forecast_sheets,
    }
)

st.download_button(
    "⬇️ Download full dataset (Excel)",
    data=workbook_bytes,
    file_name="hk_cost_dashboard_export.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    type="primary",
)
