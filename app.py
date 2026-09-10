import pandas as pd
import streamlit as st

from hk_dashboard.data import get_dashboard_data, render_coverage_sidebar

st.set_page_config(page_title="HK Cost Dashboard", page_icon="🧹", layout="wide")

st.title("🧹 HK Cleaning Hours & Cost Dashboard")
st.caption("Housekeeping hours and cost per hotel — live from Google Sheets, plus uploaded payroll rates.")

load_result, rates_df, shifts = get_dashboard_data()
render_coverage_sidebar(load_result)

if shifts.empty:
    st.warning("No shift data could be loaded yet. Check the data coverage panel in the sidebar for per-hotel errors.")
else:
    total_hours = shifts["hours"].sum()
    total_cost = shifts["cost_eur"].sum(min_count=1)
    hours_no_rate = shifts.loc[shifts["rate_missing"], "hours"].sum()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total HK hours (all data loaded)", f"{total_hours:,.1f}")
    c2.metric(
        "Total cost (all data loaded)",
        f"€{total_cost:,.2f}" if pd.notna(total_cost) else "no rate available",
    )
    c3.metric("Hotels reporting", shifts["hotel"].nunique())
    c4.metric("Hours without a matching rate", f"{hours_no_rate:,.1f}", delta=None)

    if hours_no_rate > 0:
        st.warning(
            f"⚠️ {hours_no_rate:,.1f} hours have no matching payroll rate for their month "
            "and are excluded from cost totals above. Upload the relevant month's payroll PDF "
            "on the **Payroll Upload** page to fill this in."
        )

st.divider()
st.subheader("Views")
st.markdown(
    """
- **Per Hotel** — hours + cost per hotel, toggle between Month / Week (Monday-start, numbered 1-5, restarting each month) / Day.
- **Per Housekeeper** — hours, hourly rate, cost, and (Month view only) net salary from payslip, per person, toggle between Month / Week / Day.
- **Cost Heatmap by Person** — a per-person matrix, toggle between Month / Week / Day columns.
- **Trends** — cost and hours over time, filterable by hotel and housekeeper.
- **Payroll Upload** — upload a monthly "Overzicht Loonkosten" PDF; preview before saving to the rate store.
- **Export** — download the current view, or the full dataset, as a styled Excel workbook.
- **Staff Identity** — the list housekeepers pick themselves from on the login-free confirmation page.
- **Hours Submission** — compares reception's hours against what housekeepers self-confirmed; the check-step before payroll submission.
- **Occupancy Forecast Upload** — upload Mews "Availability report" exports; preview before saving.
- **Cost Forecast** — predicted rooms, hours, cost and staffing for future dates, with the historical baseline that produced them.
"""
)

st.divider()
with st.expander("How the cost forecast works (Phase 2)"):
    st.markdown(
        """
Forecasting is **manual-upload based**, not a live Mews connection — there are
still no Mews API credentials for this project, so you export an "Availability
report" from Mews and upload it, the same way payroll comes in as a PDF.

1. Rooms to clean for a day = **departures + stayovers** (checkouts needing a
   full clean, plus occupied rooms needing a refresh). Not "occupied", which
   undercounts a room that checks out and checks in again the same day.
2. Predicted hours = those rooms × that hotel's historical **minutes per
   room**, measured over a trailing window of actuals.
3. Predicted cost = those hours × that hotel's **blended hourly rate**
   (weighted by hours actually worked, not an average of listed rates).

Both historical figures come only from months whose payroll PDF has been
uploaded, so the hours and the rate they're paired with always come from the
same closed-out months. Anything forecasted is labelled as such and shows the
date its Mews export was generated — later dates keep filling up with new
reservations, so a forecast months out is a floor, not a settled number.
"""
    )
