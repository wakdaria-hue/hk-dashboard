import streamlit as st

from hk_dashboard.comparison import build_comparison_table, zero_confirmation_summary
from hk_dashboard.data import clear_self_reports_cache, get_confirmation_spreadsheet_id, get_raw_shifts, get_self_reports
from hk_dashboard.sheets_client import SheetAccessError

st.title("Hours Submission")
st.caption(
    "Compares reception's logged hours against what each housekeeper self-confirmed. "
    "This is the required check-step before submitting hours to loonstrookgigant."
)

get_confirmation_spreadsheet_id()  # just validates the secret is set; st.stop()s with a message if not

shifts = get_raw_shifts()
if shifts.empty:
    st.info("No reception shift data loaded yet.")
    st.stop()

try:
    self_reports = get_self_reports()
except SheetAccessError as e:
    st.error(f"Can't reach the confirmation sheet right now: {e}\n\nTry again in a minute or two.")
    st.stop()

if st.button("🔄 Refresh self-reported data now"):
    clear_self_reports_cache()
    st.rerun()

hotels = sorted(shifts["hotel"].unique())
months = sorted(shifts["month"].unique())

c1, c2 = st.columns(2)
hotel = c1.selectbox("Hotel", hotels)
month = c2.selectbox("Month", months, index=len(months) - 1)

table = build_comparison_table(shifts, self_reports, month, hotel)

if table.empty:
    st.info("No reception hours for this hotel/month yet.")
else:
    counts = table["status"].value_counts()
    m1, m2, m3 = st.columns(3)
    m1.metric("Confirmed", int(counts.get("Confirmed", 0)))
    m2.metric("Disputed", int(counts.get("Disputed", 0)))
    m3.metric("Not confirmed", int(counts.get("Not confirmed", 0)))

    RENAME = {
        "date": "Date",
        "employee": "Housekeeper",
        "reception_hours": "Reception hours",
        "reception_display": "Reception range",
        "status": "Status",
        "self_reported_hours": "Self-reported hours",
        "difference_minutes": "Difference (min)",
    }
    display = table.rename(columns=RENAME)

    ROW_COLORS = {"disputed": "background-color: #ffd6d6", "mismatch": "background-color: #fff3b0"}

    def _highlight(row):
        style = ROW_COLORS.get(table.loc[row.name, "highlight_reason"], "")
        return [style] * len(row)

    styled = display.style.apply(_highlight, axis=1).format(
        {
            "Reception hours": "{:.1f}",
            "Self-reported hours": "{:.1f}",
            "Difference (min)": "{:.0f}",
        },
        na_rep="-",
    )
    st.dataframe(
        styled,
        column_order=list(RENAME.values()),
        use_container_width=True,
        hide_index=True,
    )
    st.caption("🟨 mismatch beyond the threshold · 🟥 disputed (always highlighted, regardless of size)")

st.divider()
st.subheader("Months with zero confirmations")
st.caption("A housekeeper who worked that month but never once tapped \"Yes, correct\" - across all loaded months.")
zero_df = zero_confirmation_summary(shifts, self_reports, hotel)
if zero_df.empty:
    st.info("None - everyone confirmed at least one day in every month they worked.")
else:
    st.dataframe(
        zero_df.rename(columns={"employee": "Housekeeper", "month": "Month", "worked_days": "Days worked"}),
        use_container_width=True,
        hide_index=True,
    )
