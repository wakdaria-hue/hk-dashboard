import pandas as pd
import plotly.express as px
import streamlit as st

from hk_dashboard.assignment_parser import AssignmentParseError, parse_assignment_message
from hk_dashboard.assignment_store import delete_assignments, upsert_assignment
from hk_dashboard.config import (
    GOLDEN_SETTING_KEYS,
    HOTEL_SHEETS,
    MIN_ASSIGNMENT_DAYS_FOR_PACE,
)
from hk_dashboard.data import (
    clear_cache,
    get_assignments,
    get_raw_shifts,
    get_rate_store_id,
    get_settings,
)
from hk_dashboard.excel_export import export_workbook
from hk_dashboard.golden_time import (
    FLAG_NO_ASSIGNMENT,
    FLAG_NO_HOURS,
    assignment_comparison,
    comparison_by_day,
    comparison_by_month,
    comparison_by_week,
    person_pace,
)
from hk_dashboard.settings_store import DEFAULT_SCOPE, delete_scope, golden_settings_for, upsert_settings
from hk_dashboard.sheets_client import SheetAccessError
from hk_dashboard.timeutil import today_amsterdam

st.title("Room Assignments")
st.caption(
    "Log the supervisor's daily WhatsApp assignment messages, and compare each housekeeper's "
    "actual time against the golden-time target. Room-level assignment isn't in Mews or the "
    "hours sheets - these messages are the only record of who was responsible for which rooms."
)

spreadsheet_id = get_rate_store_id()

try:
    assignments = get_assignments()
    settings_df = get_settings()
    shifts = get_raw_shifts()
except SheetAccessError as e:
    st.error(f"Can't reach the store right now: {e}\n\nTry again in a minute or two.")
    st.stop()

hotel_codes = list(HOTEL_SHEETS.keys())

# --- Entry ------------------------------------------------------------------
st.subheader("Log an assignment message")

col1, col2 = st.columns(2)
entry_date = col1.date_input("Date", value=today_amsterdam())
entry_hotel = col2.selectbox("Hotel", hotel_codes)

message = st.text_area(
    "Paste the WhatsApp message",
    height=220,
    placeholder=(
        "Good morning Assigned rooms for HK Kiko\n"
        "Check out\n"
        "G01,G04,102,103\n"
        "Stay over\n"
        "B02,G02,G03,101,104\n"
        "Cleaning stairs and corridors ..."
    ),
)

if message.strip():
    try:
        parsed = parse_assignment_message(message)
    except AssignmentParseError as e:
        st.error(str(e))
        st.stop()

    st.markdown("**Check this before saving:**")
    if parsed.name_flagged:
        st.warning(
            f"⚠️ **{parsed.raw_name or '(no name found)'}** isn't a known housekeeper nickname. "
            "It will be saved exactly as written and won't match any hours until it's added to "
            "`NAME_MAP` in `hk_dashboard/config.py`. Check the spelling first."
        )
    else:
        st.success(f"Housekeeper: **{parsed.raw_name}** → **{parsed.employee}**")

    settings = golden_settings_for(settings_df, entry_hotel)
    golden_minutes = settings.room_minutes(parsed.checkout_count, parsed.stayover_count)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Check-out rooms", parsed.checkout_count)
    m2.metric("Stay-over rooms", parsed.stayover_count)
    m3.metric("Rooms assigned", parsed.rooms_assigned)
    m4.metric("Golden target", f"{golden_minutes / 60:.2f} h")

    st.dataframe(
        pd.DataFrame(
            [
                {"Section": "Check out", "Count": parsed.checkout_count, "Rooms": ", ".join(parsed.checkout_rooms)},
                {"Section": "Stay over", "Count": parsed.stayover_count, "Rooms": ", ".join(parsed.stayover_rooms)},
            ]
        ),
        use_container_width=True,
        hide_index=True,
    )

    if parsed.notes:
        st.caption("**Notes kept with this entry** (not parsed for time):")
        st.text(parsed.notes)
    else:
        st.caption("No free-text notes found in this message.")

    if st.button("✅ Save this assignment", type="primary"):
        with st.spinner("Saving..."):
            upsert_assignment(
                spreadsheet_id,
                entry_date=entry_date,
                hotel=entry_hotel,
                employee=parsed.employee,
                raw_name=parsed.raw_name,
                checkout_rooms=parsed.checkout_rooms,
                stayover_rooms=parsed.stayover_rooms,
                notes=parsed.notes,
            )
            clear_cache()
        st.success(
            f"Saved {parsed.rooms_assigned} room(s) for {parsed.employee} at {entry_hotel} "
            f"on {entry_date:%d %b %Y}."
        )
        st.rerun()

st.divider()

# --- Golden time settings ---------------------------------------------------
with st.expander("⚙️ Golden time settings"):
    st.caption(
        "The target the supervisor is aiming for - not a measurement. Set globally, and "
        "override per hotel where a building genuinely differs. The Cost Forecast and Trends "
        "pages use these same numbers."
    )
    scope_choice = st.selectbox(
        "Applies to", ["All hotels (default)"] + hotel_codes, key="settings_scope"
    )
    scope = DEFAULT_SCOPE if scope_choice == "All hotels (default)" else scope_choice
    current = golden_settings_for(settings_df, scope if scope != DEFAULT_SCOPE else "")

    s1, s2, s3 = st.columns(3)
    checkout_min = s1.number_input(
        "Minutes per check-out room", min_value=1.0, max_value=180.0,
        value=float(current.checkout_minutes), step=1.0,
    )
    stayover_min = s2.number_input(
        "Minutes per stay-over room", min_value=1.0, max_value=180.0,
        value=float(current.stayover_minutes), step=1.0,
    )
    extras_min = s3.number_input(
        "Extra tasks, minutes per person per day", min_value=0.0, max_value=180.0,
        value=float(current.extra_tasks_minutes), step=5.0,
        help="Towels, dirty linen, corridors and common areas. Supervisor's estimate is 25-35.",
    )

    if st.button("Save settings"):
        with st.spinner("Saving settings..."):
            upsert_settings(
                spreadsheet_id,
                scope,
                {
                    "golden_checkout_min": checkout_min,
                    "golden_stayover_min": stayover_min,
                    "extra_tasks_min": extras_min,
                },
            )
            clear_cache()
        st.success(f"Saved for {scope_choice}.")
        st.rerun()

    if scope != DEFAULT_SCOPE and not settings_df.empty and (settings_df["scope"] == scope).any():
        if st.button(f"↩️ Remove {scope}'s override (fall back to the default)"):
            with st.spinner("Removing override..."):
                delete_scope(spreadsheet_id, scope)
                clear_cache()
            st.success(f"{scope} now follows the global default.")
            st.rerun()

    st.caption("Currently in effect:")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Hotel": hotel,
                    "Check-out (min)": golden_settings_for(settings_df, hotel).checkout_minutes,
                    "Stay-over (min)": golden_settings_for(settings_df, hotel).stayover_minutes,
                    "Extra tasks (min/person/day)": golden_settings_for(settings_df, hotel).extra_tasks_minutes,
                    "Source": "hotel override"
                    if golden_settings_for(settings_df, hotel).is_hotel_specific
                    else "default",
                }
                for hotel in hotel_codes
            ]
        ),
        use_container_width=True,
        hide_index=True,
    )
    st.caption(
        "Seed values if nothing is set: "
        + ", ".join(f"{k} = {v:g}" for k, v in GOLDEN_SETTING_KEYS.items())
    )

st.divider()

# --- Comparison -------------------------------------------------------------
st.subheader("Actual vs golden time")

if assignments.empty:
    st.info("No assignments logged yet. Paste a message above to get started.")
    st.stop()

comparison = assignment_comparison(assignments, shifts, settings_df)
if comparison.empty:
    st.info("Nothing to compare yet.")
    st.stop()

f1, f2 = st.columns(2)
hotels_present = sorted(comparison["hotel"].dropna().unique())
selected_hotels = f1.multiselect("Hotel", hotels_present, default=hotels_present)
date_min, date_max = comparison["date"].min(), comparison["date"].max()
date_range = f2.date_input(
    "Date range", value=(date_min, date_max), min_value=date_min, max_value=date_max
)
if isinstance(date_range, tuple) and len(date_range) == 2:
    start, end = date_range
else:
    start = end = date_range if not isinstance(date_range, tuple) else date_min

scoped = comparison[
    comparison["hotel"].isin(selected_hotels)
    & (comparison["date"] >= start)
    & (comparison["date"] <= end)
]

if scoped.empty:
    st.info("No entries in this selection.")
    st.stop()

# Data-quality gaps come first: they're the reason this page exists.
no_hours = scoped[scoped["flag"] == FLAG_NO_HOURS]
no_assignment = scoped[scoped["flag"] == FLAG_NO_ASSIGNMENT]

if not no_hours.empty:
    st.error(
        f"🚩 **{len(no_hours)} day(s) with rooms assigned but no hours logged.** Someone was "
        "responsible for rooms without any time being recorded - the hours sheet is incomplete "
        "for those days, and their cost is missing everywhere in this dashboard."
    )
    st.dataframe(
        no_hours[["date", "hotel", "employee", "rooms_assigned", "checkout_count", "stayover_count"]]
        .rename(columns={
            "date": "Date", "hotel": "Hotel", "employee": "Housekeeper",
            "rooms_assigned": "Rooms assigned", "checkout_count": "Check-out",
            "stayover_count": "Stay-over",
        }),
        use_container_width=True,
        hide_index=True,
    )

if not no_assignment.empty:
    with st.expander(f"⚠️ {len(no_assignment)} day(s) with hours logged but no assignment entered"):
        st.caption(
            "Not necessarily a problem - it usually just means that day's message hasn't been "
            "pasted in yet. These days are excluded from every variance average below."
        )
        st.dataframe(
            no_assignment[["date", "hotel", "employee", "hours_logged"]].rename(
                columns={"date": "Date", "hotel": "Hotel", "employee": "Housekeeper",
                         "hours_logged": "Hours logged"}
            ),
            use_container_width=True,
            hide_index=True,
        )

st.markdown("**Average variance against target**")
st.caption(
    "A single day is noisy - a hard day, an unusual room mix, a standard still settling in. "
    "Week and month averages are the meaningful view; per-day detail is below. "
    "Negative = faster than target, positive = slower."
)

view_by = st.radio("Roll up by", ["Month", "Week", "Day"], horizontal=True, index=0)
if view_by == "Month":
    rollup = comparison_by_month(scoped)
    period_cols = {"month": "Month"}
elif view_by == "Week":
    rollup = comparison_by_week(scoped).drop(columns=["week_number"], errors="ignore")
    period_cols = {"week_label": "Week", "month": "Month"}
else:
    rollup = comparison_by_day(scoped)
    period_cols = {"date": "Date"}

if rollup.empty:
    st.info(
        "No day in this selection has both an assignment and logged hours, so there's no "
        "variance to average yet."
    )
else:
    RENAME = {
        "employee": "Housekeeper",
        "hotel": "Hotel",
        "days": "Days",
        "rooms_assigned": "Rooms",
        "avg_variance_minutes": "Avg variance (min)",
        "avg_variance_pct": "Avg variance %",
        "golden_avg_min_per_room": "Golden avg min/room",
        "actual_avg_min_per_room": "Actual avg min/room",
        **period_cols,
    }
    table = rollup.rename(columns=RENAME)[
        [c for c in [
            "Housekeeper", "Hotel", *period_cols.values(), "Days", "Rooms",
            "Golden avg min/room", "Actual avg min/room",
            "Avg variance (min)", "Avg variance %",
        ] if c in rollup.rename(columns=RENAME).columns]
    ]
    st.dataframe(
        table.style.format(
            {
                "Rooms": "{:.0f}",
                "Golden avg min/room": "{:.1f}",
                "Actual avg min/room": "{:.1f}",
                "Avg variance (min)": "{:+.1f}",
                "Avg variance %": "{:+.1%}",
            },
            na_rep="-",
        ),
        use_container_width=True,
        hide_index=True,
    )
    st.caption(
        "**Golden avg min/room moves with the room mix** - a day of mostly check-outs allows "
        "more time per room than a day of stay-overs. That's why two people with the same "
        "actual min/room can sit at very different distances from target, and why the variance "
        "column is the comparable number rather than the flat average."
    )

    chart_df = table.dropna(subset=["Avg variance %"])
    if not chart_df.empty:
        fig = px.bar(
            chart_df,
            x="Housekeeper",
            y="Avg variance %",
            color="Hotel",
            barmode="group",
            title=f"Average variance against golden time ({view_by.lower()} average)",
        )
        fig.add_hline(y=0, line_dash="dash", line_color="#6B6459", annotation_text="Golden target")
        st.plotly_chart(fig, use_container_width=True)

with st.expander("Per-day detail"):
    detail = scoped[[
        "date", "hotel", "employee", "checkout_count", "stayover_count", "rooms_assigned",
        "checkout_rooms", "stayover_rooms", "golden_minutes", "golden_avg_min_per_room",
        "hours_logged", "actual_room_minutes", "actual_avg_min_per_room",
        "variance_minutes", "variance_pct", "flag", "notes",
    ]].rename(columns={
        "date": "Date", "hotel": "Hotel", "employee": "Housekeeper",
        "checkout_count": "Check-out", "stayover_count": "Stay-over",
        "rooms_assigned": "Rooms", "checkout_rooms": "Check-out rooms",
        "stayover_rooms": "Stay-over rooms", "golden_minutes": "Golden (min)",
        "golden_avg_min_per_room": "Golden avg min/room", "hours_logged": "Hours logged",
        "actual_room_minutes": "Actual room time (min)",
        "actual_avg_min_per_room": "Actual avg min/room",
        "variance_minutes": "Variance (min)", "variance_pct": "Variance %",
        "flag": "Flag", "notes": "Notes",
    })
    st.dataframe(
        detail.style.format(
            {
                "Check-out": "{:.0f}", "Stay-over": "{:.0f}", "Rooms": "{:.0f}",
                "Golden (min)": "{:.0f}", "Golden avg min/room": "{:.1f}",
                "Hours logged": "{:.2f}", "Actual room time (min)": "{:.0f}",
                "Actual avg min/room": "{:.1f}", "Variance (min)": "{:+.0f}",
                "Variance %": "{:+.1%}",
            },
            na_rep="-",
        ),
        use_container_width=True,
        hide_index=True,
    )

    st.caption("Select rows above? Delete a mis-parsed entry here:")
    deletable = assignments[
        assignments["hotel"].isin(selected_hotels)
        & (assignments["date"] >= start)
        & (assignments["date"] <= end)
    ].reset_index(drop=True)
    if not deletable.empty:
        event = st.dataframe(
            deletable[["date", "hotel", "employee", "checkout_count", "stayover_count", "entered_at"]],
            use_container_width=True,
            hide_index=True,
            on_select="rerun",
            selection_mode="multi-row",
            key="assignment_delete_table",
        )
        if event.selection.rows:
            to_delete = deletable.iloc[event.selection.rows]
            st.warning(f"⚠️ {len(to_delete)} entr(ies) selected for deletion.")
            if st.checkbox("Yes, delete these entries") and st.button("🗑️ Delete", type="primary"):
                keys = list(zip(to_delete["date"], to_delete["hotel"], to_delete["employee"]))
                with st.spinner("Deleting..."):
                    delete_assignments(spreadsheet_id, keys)
                    clear_cache()
                st.success(f"Deleted {len(keys)} entr(ies).")
                st.rerun()

paces = person_pace(scoped, MIN_ASSIGNMENT_DAYS_FOR_PACE)
with st.expander("Measured pace per housekeeper (feeds the forecast)"):
    st.caption(
        f"Actual room minutes ÷ rooms, extras already removed. A housekeeper needs at least "
        f"{MIN_ASSIGNMENT_DAYS_FOR_PACE} logged day(s) to appear here. Once a hotel has "
        "measured people, the Cost Forecast page's staffing estimate uses the median of these "
        "instead of the hotel-wide average."
    )
    if paces.empty:
        st.info(
            f"No housekeeper has {MIN_ASSIGNMENT_DAYS_FOR_PACE}+ logged days in this selection yet."
        )
    else:
        st.dataframe(
            paces.rename(columns={
                "hotel": "Hotel", "employee": "Housekeeper", "days": "Days logged",
                "minutes_per_room": "Measured min/room",
            }).style.format({"Measured min/room": "{:.1f}"}),
            use_container_width=True,
            hide_index=True,
        )

st.download_button(
    "⬇️ Export this view to Excel",
    data=export_workbook(
        {
            "Variance rollup": {
                "df": rollup.rename(columns={"employee": "Housekeeper", "hotel": "Hotel"}),
                "title": f"Variance against golden time ({view_by.lower()})",
                "subtitle": "Negative = faster than target. Days without both an assignment and logged hours are excluded.",
                "total_row": False,
            },
            "Per-day detail": {
                "df": scoped.drop(columns=["week_number"], errors="ignore"),
                "title": "Room assignments vs actual time, per day",
                "total_row": False,
            },
        }
    ),
    file_name="hk_room_assignments_golden_time.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)
