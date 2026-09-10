import pandas as pd
import plotly.express as px
import streamlit as st

from hk_dashboard.config import BASELINE_WINDOW_OPTIONS, DEFAULT_BASELINE_WINDOW_DAYS
from hk_dashboard.data import get_dashboard_data, get_occupancy, render_coverage_sidebar
from hk_dashboard.excel_export import export_workbook
from hk_dashboard.forecast import (
    baselines_to_df,
    build_forecast,
    compute_baselines,
    forecast_by_day,
    forecast_by_month,
    forecast_by_week,
)
from hk_dashboard.sheets_client import SheetAccessError
from hk_dashboard.staffing import estimate_shifts, team_average_shift_count
from hk_dashboard.timeutil import today_amsterdam

st.title("Cost Forecast")
st.caption(
    "Predicted cleaning hours and cost from uploaded Mews occupancy. Every figure here is a "
    "**forecast**, not a verified actual - it combines booked rooms with a historical "
    "minutes-per-room and pay rate."
)

load_result, rates_df, shifts = get_dashboard_data()
render_coverage_sidebar(load_result)

try:
    occupancy = get_occupancy()
except SheetAccessError as e:
    st.error(f"Can't reach the occupancy store right now: {e}\n\nTry again in a minute or two.")
    st.stop()

if occupancy.empty:
    st.info(
        "No occupancy data uploaded yet. Go to **Occupancy Forecast Upload** and add Mews "
        "'Availability report' exports - a past range to calibrate minutes per room, and a "
        "future range to forecast."
    )
    st.stop()

today = today_amsterdam()

window_choice = st.selectbox(
    "Calibrate the baseline on the last",
    [*BASELINE_WINDOW_OPTIONS, "All available history"],
    index=BASELINE_WINDOW_OPTIONS.index(DEFAULT_BASELINE_WINDOW_DAYS),
    format_func=lambda v: f"{v} days" if isinstance(v, int) else v,
    help=(
        "The trailing window of historical actuals used to work out minutes per room and the "
        "blended hourly rate. Longer is steadier; shorter reacts faster to a real change in "
        "how the team works."
    ),
)
window_days = window_choice if isinstance(window_choice, int) else None

baselines = compute_baselines(shifts, occupancy, today=today, window_days=window_days)
forecast = build_forecast(occupancy, baselines, today=today)

st.subheader("Baseline assumptions")
st.caption(
    "From historical actuals only, for months whose payroll PDF has been uploaded. "
    "Check these each time you upload a new occupancy export - every forecast below is these "
    "numbers multiplied by booked rooms."
)
baseline_table = baselines_to_df(baselines).rename(
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
)
st.dataframe(
    baseline_table.style.format(
        {
            "Hours (actual)": "{:.1f}",
            "Rooms (actual)": "{:.0f}",
            "Min/room": "{:.1f}",
            "Blended rate (EUR/hr)": "€{:.2f}",
            "Hours w/o rate": "{:.1f}",
            "Min/room (solo days)": "{:.1f}",
            "Typical shift (hrs)": "{:.1f}",
        },
        na_rep="not enough data",
    ),
    use_container_width=True,
    hide_index=True,
)
st.caption(
    "**Min/room is team-wide on purpose.** On most days several housekeepers work the same "
    "rooms and only a per-person daily hours total is recorded, so there's no reliable way to "
    "say who cleaned which room. **Min/room (solo days)** is the same figure measured only on "
    "days where one person worked alone and therefore did every room - a truer measure of one "
    "person's throughput, used for the staffing estimate but never for the cost forecast."
)

unusable = [b for b in baselines.values() if not b.is_usable]
if unusable:
    st.warning(
        "⚠️ No usable baseline for: "
        + "; ".join(f"**{b.hotel}** ({b.note})" for b in unusable)
        + ". Those hotels' rows below show rooms only, with no predicted hours or cost."
    )

rated_gap = [b for b in baselines.values() if b.is_usable and b.unrated_hours_share > 0.05]
if rated_gap:
    st.warning(
        "⚠️ Part of the calibration window has hours with no payroll rate on file, so the "
        "blended rate is based on the rest: "
        + "; ".join(
            f"**{b.hotel}** ({b.unrated_hours_share:.0%} of hours unrated)" for b in rated_gap
        )
    )

st.divider()

if forecast.empty:
    st.info(
        f"Occupancy data is stored, but none of it is dated {today:%d %b %Y} or later - so "
        "there's nothing to forecast yet. Export a **future** date range from Mews and upload "
        "it on the Occupancy Forecast Upload page."
    )
    st.stop()

st.subheader("Forecast")
hotels = sorted(forecast["hotel"].unique())
months = sorted(forecast["month"].unique())

view_by = st.radio("View by", ["Month", "Week", "Day"], horizontal=True)
selected_hotels = st.multiselect("Hotel", hotels, default=hotels)
scoped = forecast[forecast["hotel"].isin(selected_hotels)]

RENAME = {
    "hotel": "Hotel",
    "month": "Month",
    "date": "Date",
    "week_number": "Week #",
    "week_label": "Week",
    "rooms_to_clean": "Predicted rooms to clean",
    "predicted_hours": "Predicted hours",
    "predicted_cost_eur": "Predicted cost (EUR)",
    "days": "Days",
}
FMT = {
    "Predicted rooms to clean": "{:.0f}",
    "Predicted hours": "{:.1f}",
    "Predicted cost (EUR)": "€{:.2f}",
}

if view_by == "Month":
    displayed = scoped
    table = forecast_by_month(scoped)
    x_axis = "Month"
    scope_label = "by month"
    file_scope = "month"
elif view_by == "Week":
    selected_month = st.selectbox("Month", months)
    displayed = scoped[scoped["month"] == selected_month]
    table = forecast_by_week(scoped, selected_month).drop(columns=["week_number"], errors="ignore")
    x_axis = "Week"
    scope_label = f"by week - {selected_month}"
    file_scope = f"week_{selected_month}"
else:
    selected_month = st.selectbox("Month", months)
    displayed = scoped[scoped["month"] == selected_month]
    table = forecast_by_day(scoped, selected_month)
    x_axis = "Date"
    scope_label = f"by day - {selected_month}"
    file_scope = f"day_{selected_month}"

table = table.rename(columns=RENAME)
chart_title = f"Forecasted cleaning cost {scope_label}"

if table.empty:
    st.info("No forecast rows for this selection.")
    st.stop()

total_rooms = displayed["rooms_to_clean"].sum(min_count=1)
total_hours = displayed["predicted_hours"].sum(min_count=1)
total_cost = displayed["predicted_cost_eur"].sum(min_count=1)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Forecasted rooms to clean", f"{total_rooms:,.0f}" if pd.notna(total_rooms) else "-")
c2.metric("Forecasted hours", f"{total_hours:,.1f}" if pd.notna(total_hours) else "-")
c3.metric("Forecasted cost", f"€{total_cost:,.2f}" if pd.notna(total_cost) else "-")
c4.metric("Days covered", displayed["date"].nunique())

as_of = sorted({str(v) for v in displayed["report_created"] if str(v).strip()})
if as_of:
    st.caption(
        "🔮 **Forecasted** - based on bookings as at "
        + ", ".join(a.replace("T", " ") for a in as_of)
        + ". Later dates will keep filling up as new reservations come in, so re-upload a "
        "fresher Mews export closer to the time."
    )

st.dataframe(
    table.style.format(FMT, na_rep="no baseline yet"),
    use_container_width=True,
    hide_index=True,
)

chart_df = table.dropna(subset=["Predicted cost (EUR)"])
if not chart_df.empty:
    fig = px.bar(
        chart_df,
        x=x_axis,
        y="Predicted cost (EUR)",
        color="Hotel",
        barmode="group",
        title=chart_title,
    )
    st.plotly_chart(fig, use_container_width=True)

st.divider()
st.subheader("Staffing estimate")
st.caption(
    "A rough first pass: how many shifts each day's forecasted work implies, not who should "
    "work them. Uses solo-day throughput where a hotel has any (see the baseline table), "
    "otherwise the team-wide average."
)

staffing_records = []
for row in displayed.itertuples(index=False):
    baseline = baselines.get(row.hotel)
    if baseline is None or not baseline.is_usable:
        continue
    suggested = estimate_shifts(
        row.rooms_to_clean, row.predicted_hours, row.hotel, row.date, baseline
    )
    if not suggested:
        continue
    staffing_records.append(
        {
            "Hotel": row.hotel,
            "Date": row.date,
            "Predicted rooms to clean": row.rooms_to_clean,
            "Predicted hours": row.predicted_hours,
            "Suggested shifts": len(suggested),
            "Hours each": suggested[0].hours,
            "Basis": suggested[0].basis,
            "Shifts on team-average basis": team_average_shift_count(row.predicted_hours, baseline),
        }
    )

if not staffing_records:
    st.info("No staffing estimate available - no hotel in this selection has a usable baseline.")
else:
    staffing_df = pd.DataFrame(staffing_records).sort_values(["Date", "Hotel"])
    st.dataframe(
        staffing_df.style.format(
            {
                "Predicted rooms to clean": "{:.0f}",
                "Predicted hours": "{:.1f}",
                "Hours each": "{:.1f}",
            },
            na_rep="-",
        ),
        use_container_width=True,
        hide_index=True,
    )

st.divider()
export_sheets = {
    "Forecast": {
        "df": table,
        "title": f"FORECAST - {chart_title}",
        "subtitle": "Forecasted figures, not verified actuals - see the Baseline sheet for the assumptions used.",
        "currency_cols": ("Predicted cost (EUR)",),
        "hours_cols": ("Predicted hours",),
    },
    "Baseline": {
        "df": baseline_table,
        "title": "Forecast baseline (from historical actuals)",
        "subtitle": f"Trailing window: {window_choice if isinstance(window_choice, str) else f'{window_choice} days'}, payroll-gated months only.",
        "currency_cols": ("Blended rate (EUR/hr)",),
        "hours_cols": ("Hours (actual)", "Hours w/o rate", "Typical shift (hrs)"),
        "total_row": False,
    },
}
if staffing_records:
    export_sheets["Staffing estimate"] = {
        "df": staffing_df,
        "title": f"FORECAST - staffing estimate {scope_label}",
        "subtitle": "Suggested shift counts, not named individuals.",
        "hours_cols": ("Predicted hours", "Hours each"),
        "total_row": False,
    }

st.download_button(
    "⬇️ Export this forecast to Excel",
    data=export_workbook(export_sheets),
    file_name=f"hk_cost_forecast_{file_scope}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)
