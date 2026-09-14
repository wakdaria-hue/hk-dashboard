import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from hk_dashboard.config import (
    BASELINE_WINDOW_OPTIONS,
    DEFAULT_BASELINE_WINDOW_DAYS,
    MIN_ASSIGNMENT_DAYS_FOR_PACE,
)
from hk_dashboard.data import (
    get_assignments,
    get_dashboard_data,
    get_occupancy,
    get_raw_shifts,
    get_settings,
    render_coverage_sidebar,
)
from hk_dashboard.excel_export import export_workbook
from hk_dashboard.forecast import (
    baselines_to_df,
    build_forecast,
    compute_baselines,
    forecast_by_day,
    forecast_by_month,
    forecast_by_week,
)
from hk_dashboard.golden_time import assignment_comparison, golden_line, hotel_person_pace
from hk_dashboard.settings_store import golden_settings_for
from hk_dashboard.sheets_client import SheetAccessError
from hk_dashboard.staffing import estimate_shifts, team_average_shift_count
from hk_dashboard.timeutil import today_amsterdam

ALL_HISTORY = "All available history"

# Golden rows are per hotel per day; the chart's x-axis changes with the
# view, so they're bucketed the same way the forecast table already is.
_GOLDEN_BUCKET = {"Month": "month", "Week": "week_label", "Day": "date"}


def _golden_series(golden_df, view_by: str, x_axis: str):
    bucket = _GOLDEN_BUCKET[view_by]
    grouped = golden_df.groupby(["hotel", bucket], as_index=False).agg(
        golden_cost_eur=("golden_cost_eur", lambda s: s.sum(min_count=1))
    )
    return grouped.rename(
        columns={"hotel": "Hotel", bucket: x_axis, "golden_cost_eur": "Golden cost (EUR)"}
    ).dropna(subset=["Golden cost (EUR)"])

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
    assignments = get_assignments()
    settings_df = get_settings()
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

WINDOW_OPTIONS = [ALL_HISTORY, *BASELINE_WINDOW_OPTIONS]
window_choice = st.selectbox(
    "Calibrate the baseline on",
    WINDOW_OPTIONS,
    index=WINDOW_OPTIONS.index(DEFAULT_BASELINE_WINDOW_DAYS or ALL_HISTORY),
    format_func=lambda v: f"the last {v} days" if isinstance(v, int) else v,
    help=(
        "All available history is the default: every historical day with both hours and a "
        "room count feeds the baseline, and it keeps improving as history accumulates. The "
        "shorter windows are for checking whether the team's pace has actually shifted."
    ),
)
window_days = window_choice if isinstance(window_choice, int) else None

# Logged room assignments are the better per-person signal the staffing
# estimate was left swappable for - see hk_dashboard/staffing.py.
comparison = assignment_comparison(assignments, get_raw_shifts(), settings_df)
person_paces = hotel_person_pace(comparison, MIN_ASSIGNMENT_DAYS_FOR_PACE)

baselines = compute_baselines(
    shifts,
    occupancy,
    today=today,
    window_days=window_days,
    assignments=assignments,
    person_paces=person_paces,
)
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
        "assignment_minutes_per_room": "Min/room (measured, assignments)",
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
            "Min/room (measured, assignments)": "{:.1f}",
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
    "person's throughput, used for the staffing estimate but never for the cost forecast. "
    "**Min/room (measured, assignments)** is better still where it exists - the median "
    "measured pace of that hotel's housekeepers from logged assignment messages, with the "
    "daily extras bundle already removed."
)

golden_in_use = pd.DataFrame(
    [
        {
            "Hotel": hotel,
            "Check-out (min)": golden_settings_for(settings_df, hotel).checkout_minutes,
            "Stay-over (min)": golden_settings_for(settings_df, hotel).stayover_minutes,
            "Extra tasks (min/person/day)": golden_settings_for(settings_df, hotel).extra_tasks_minutes,
        }
        for hotel in sorted(occupancy["hotel"].dropna().unique())
    ]
)
if not golden_in_use.empty:
    with st.expander("Golden-time targets used for the dashed target line"):
        st.dataframe(golden_in_use, use_container_width=True, hide_index=True)
        st.caption("Change these on the **Room Assignments** page - they're shared across pages.")

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

# Computed before the chart because the golden line's per-person extras
# bundle needs a headcount, and for a future date the staffing estimate is
# the only headcount there is.
staffing_records = []
estimated_headcount: dict[tuple[str, object], int] = {}
for row in displayed.itertuples(index=False):
    baseline = baselines.get(row.hotel)
    if baseline is None or not baseline.is_usable:
        continue
    suggested = estimate_shifts(
        row.rooms_to_clean, row.predicted_hours, row.hotel, row.date, baseline
    )
    if not suggested:
        continue
    estimated_headcount[(row.hotel, row.date)] = len(suggested)
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

blended_rates = {
    hotel: b.blended_hourly_rate for hotel, b in baselines.items() if b.blended_hourly_rate
}
golden_df = golden_line(
    comparison[comparison["date"] >= today] if not comparison.empty else comparison,
    occupancy[occupancy["date"] >= today],
    settings_df,
    blended_rates,
    headcount_by_hotel_day=estimated_headcount,
)
golden_scoped = (
    golden_df[golden_df["hotel"].isin(selected_hotels)] if not golden_df.empty else golden_df
)
if view_by != "Month" and not golden_scoped.empty:
    golden_scoped = golden_scoped[golden_scoped["month"] == selected_month]

total_rooms = displayed["rooms_to_clean"].sum(min_count=1)
total_hours = displayed["predicted_hours"].sum(min_count=1)
total_cost = displayed["predicted_cost_eur"].sum(min_count=1)

golden_cost_total = (
    golden_scoped["golden_cost_eur"].sum(min_count=1) if not golden_scoped.empty else None
)

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Forecasted rooms to clean", f"{total_rooms:,.0f}" if pd.notna(total_rooms) else "-")
c2.metric("Forecasted hours", f"{total_hours:,.1f}" if pd.notna(total_hours) else "-")
c3.metric("Forecasted cost", f"€{total_cost:,.2f}" if pd.notna(total_cost) else "-")
c4.metric(
    "Golden-time cost",
    f"€{golden_cost_total:,.2f}" if golden_cost_total is not None and pd.notna(golden_cost_total) else "-",
    delta=(
        f"€{total_cost - golden_cost_total:,.2f} vs target"
        if (golden_cost_total is not None and pd.notna(golden_cost_total) and pd.notna(total_cost))
        else None
    ),
    delta_color="inverse",
    help="What this period would cost if every room hit the golden-time target.",
)
c5.metric("Days covered", displayed["date"].nunique())

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
    # Golden target as a dashed overlay, never a bar - it's neither an actual
    # nor a forecast, and shouldn't be able to read as one.
    if not golden_scoped.empty:
        golden_chart = _golden_series(golden_scoped, view_by, x_axis)
        for hotel in sorted(golden_chart["Hotel"].unique()):
            series = golden_chart[golden_chart["Hotel"] == hotel].sort_values(x_axis)
            fig.add_trace(
                go.Scatter(
                    x=series[x_axis],
                    y=series["Golden cost (EUR)"],
                    mode="lines+markers",
                    name=f"{hotel} · Golden",
                    line=dict(dash="dash", width=2),
                    marker=dict(symbol="diamond", size=7),
                )
            )
    st.plotly_chart(fig, use_container_width=True)
    if not golden_scoped.empty:
        bases = sorted(golden_scoped["extras_basis"].unique())
        st.caption(
            "The dashed **Golden** line is the target - what this would cost if every room hit "
            "golden time. It's not an actual and not a forecast. Room counts come from "
            + ", ".join(sorted(golden_scoped["rooms_source"].unique()))
            + f"; the per-person extras bundle is counted on a headcount basis of: {', '.join(bases)}."
        )

st.divider()
st.subheader("Staffing estimate")
st.caption(
    "A rough first pass: how many shifts each day's forecasted work implies, not who should "
    "work them. Best available basis per hotel, in order: measured pace from logged room "
    "assignments, then solo-day throughput, then the team-wide average."
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
