import pandas as pd
import streamlit as st

from hk_dashboard.availability_xlsx import (
    AvailabilityReportError,
    parse_availability_workbook,
    report_to_rows,
    rows_to_preview_df,
)
from hk_dashboard.config import HOTEL_SHEETS
from hk_dashboard.data import clear_cache, get_occupancy, get_rate_store_id
from hk_dashboard.occupancy_store import (
    clear_occupancy_store,
    delete_occupancy_rows,
    upsert_occupancy,
)
from hk_dashboard.sheets_client import SheetAccessError
from hk_dashboard.timeutil import today_amsterdam

st.title("Occupancy Forecast Upload")
st.caption(
    "Upload Mews 'Availability report' exports (.xlsx), one per hotel. "
    "Future date ranges drive the cost forecast; past date ranges calibrate it "
    "(the forecast needs historical occupancy to work out minutes per room). "
    "Preview the parsed rows before saving - nothing is written until you confirm."
)

spreadsheet_id = get_rate_store_id()

try:
    current = get_occupancy()
except SheetAccessError as e:
    st.error(f"Can't reach the occupancy store right now: {e}\n\nTry again in a minute or two.")
    st.stop()

uploaded_files = st.file_uploader(
    "Mews Availability report(s)", type=["xlsx"], accept_multiple_files=True
)

if uploaded_files:
    parsed, failed = [], []
    for uploaded in uploaded_files:
        try:
            parsed.append(parse_availability_workbook(uploaded, uploaded.name))
        except AvailabilityReportError as e:
            failed.append((uploaded.name, str(e)))

    for name, message in failed:
        st.error(f"**{name}** couldn't be read: {message}")

    hotel_codes = list(HOTEL_SHEETS.keys())
    rows_to_save = []

    for i, report in enumerate(parsed):
        st.divider()
        st.markdown(f"**{report.filename}**")

        if report.hotel:
            hotel = report.hotel
            st.success(
                f"Mews enterprise **{report.enterprise}** → hotel **{hotel}**. "
                f"Range {report.start:%d %b %Y} - {report.end:%d %b %Y}, "
                f"{len(report.days)} day(s)."
            )
        else:
            st.warning(
                f"⚠️ Mews enterprise **{report.enterprise or '(blank)'}** isn't in the known "
                "hotel list, so it can't be matched automatically. Pick the right hotel below, "
                "and ask for `MEWS_ENTERPRISE_TO_HOTEL` in `hk_dashboard/config.py` to be "
                "updated with this exact name so next time it's detected on its own."
            )
            hotel = st.selectbox(
                "Which hotel is this export for?",
                hotel_codes,
                key=f"hotel_pick_{i}",
            )

        if report.created:
            st.caption(
                f"Mews generated this export on {report.created:%d %b %Y %H:%M}. Forecast "
                "figures for future dates reflect the bookings on the books at that moment - "
                "a date far out will keep filling up, so re-upload closer to the time."
            )

        preview = rows_to_preview_df(report, hotel)
        st.dataframe(
            preview.style.format(
                {
                    "departures": "{:.0f}",
                    "stayovers": "{:.0f}",
                    "rooms_to_clean": "{:.0f}",
                    "occupied": "{:.0f}",
                    "rooms_total": "{:.0f}",
                },
                na_rep="-",
            ),
            use_container_width=True,
            hide_index=True,
        )
        st.caption(
            f"Total rooms to clean over this range: "
            f"**{preview['rooms_to_clean'].sum():.0f}** "
            f"(departures {preview['departures'].sum():.0f} + stayovers "
            f"{preview['stayovers'].sum():.0f}). Occupied rooms aren't used for this - "
            "they undercount a day where a room checks out and a new guest checks in."
        )

        if not current.empty:
            overlap = current[
                (current["hotel"] == hotel) & (current["date"].isin(set(preview["date"])))
            ]
            if not overlap.empty:
                st.info(
                    f"{len(overlap)} day(s) already stored for {hotel} in this range will be "
                    "**overwritten** with these figures (upsert on hotel + date, not summed)."
                )

        rows_to_save.append(report_to_rows(report, hotel))

    if rows_to_save:
        st.divider()
        source_label = st.text_input(
            "Source label (for the audit trail)",
            value=", ".join(r.filename for r in parsed),
        )
        if st.button("✅ Save this occupancy data", type="primary"):
            with st.spinner("Writing to the occupancy store..."):
                upsert_occupancy(
                    spreadsheet_id,
                    pd.concat(rows_to_save, ignore_index=True),
                    source_label=source_label,
                    upload_date=today_amsterdam(),
                )
                clear_cache()
            st.success("Saved. The Cost Forecast page will use these figures now.")
            st.rerun()

st.divider()
st.subheader("Stored occupancy data")
if current.empty:
    st.info(
        "Nothing uploaded yet. The Cost Forecast page needs both a past range "
        "(to calibrate minutes per room) and a future range (to forecast)."
    )
else:
    today = today_amsterdam()
    past = current[current["date"] < today]
    future = current[current["date"] >= today]

    c1, c2, c3 = st.columns(3)
    c1.metric("Hotels with data", current["hotel"].nunique())
    c2.metric("Past days (calibration)", len(past))
    c3.metric("Future days (forecast)", len(future))

    summary = (
        current.groupby("hotel", as_index=False)
        .agg(
            days=("date", "nunique"),
            first_day=("date", "min"),
            last_day=("date", "max"),
            rooms_to_clean=("rooms_to_clean", "sum"),
        )
        .sort_values("hotel")
    )
    st.dataframe(summary, use_container_width=True, hide_index=True)

    with st.expander("All stored rows (select to delete)"):
        display = current.drop(columns=["month"], errors="ignore").reset_index(drop=True)
        st.caption(
            "Click a row (or drag across several) to select it, then delete below if it was "
            "uploaded by mistake."
        )
        event = st.dataframe(
            display,
            use_container_width=True,
            hide_index=True,
            on_select="rerun",
            selection_mode="multi-row",
            key="occupancy_table",
        )
        selected_positions = event.selection.rows
        if selected_positions:
            to_delete = display.iloc[selected_positions]
            st.warning(f"⚠️ {len(to_delete)} row(s) selected for deletion:")
            st.dataframe(
                to_delete[["hotel", "date", "rooms_to_clean", "source"]],
                use_container_width=True,
                hide_index=True,
            )
            confirm_selected = st.checkbox("Yes, delete these rows")
            if st.button("🗑️ Delete selected rows", type="primary", disabled=not confirm_selected):
                keys = list(zip(to_delete["hotel"], to_delete["date"]))
                with st.spinner("Deleting from the occupancy store..."):
                    delete_occupancy_rows(spreadsheet_id, keys)
                    clear_cache()
                st.success(f"Deleted {len(keys)} row(s).")
                st.rerun()

    with st.expander("⚠️ Danger zone: clear all stored occupancy data"):
        st.write(
            "Removes every uploaded occupancy row for every hotel and date. The forecast "
            "stops working until you re-upload. Payroll rates and shift data aren't touched."
        )
        confirm_all = st.text_input("Type CLEAR to confirm", value="", key="confirm_clear_occupancy")
        if st.button("🗑️ Clear all occupancy data", disabled=(confirm_all != "CLEAR")):
            with st.spinner("Clearing the occupancy store..."):
                clear_occupancy_store(spreadsheet_id)
                clear_cache()
            st.success("Occupancy store cleared.")
            st.rerun()
