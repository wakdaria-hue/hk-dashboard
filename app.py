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
- **Room Assignments** — log the supervisor's daily WhatsApp room lists; compare each housekeeper's actual time against the golden-time target.
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
same closed-out months. The baseline calibrates on **all available history**
by default and keeps improving as more accumulates. Anything forecasted is
labelled as such and shows the date its Mews export was generated — later
dates keep filling up with new reservations, so a forecast months out is a
floor, not a settled number.
"""
    )

with st.expander("Golden time: the target line"):
    st.markdown(
        """
**Golden time** is what the supervisor is aiming for — by default 30 minutes
for a check-out room, 15 for a stay-over, plus a 30-minute daily bundle per
person for towels, linen and common areas. These are editable on the **Room
Assignments** page, globally or per hotel.

It appears in two ways. Per housekeeper, the Room Assignments page compares
their logged hours against the target for the rooms they were actually
assigned. At hotel and portfolio level, a dashed **Golden** line on the
Trends and Cost Forecast charts shows what a period would cost if every room
hit the target — so you can see how far actual *and* forecast sit from the
goal, not just from each other. It is deliberately styled as a reference
line: it is neither a real actual nor a real forecast.

Room assignment exists only in the supervisor's daily WhatsApp messages —
not in Mews, not in the hours sheets — so the comparison only covers days
whose message has been pasted in. Where a day has rooms assigned but no
hours logged (someone covered rooms without recording time), that gap is
flagged rather than quietly dropped.
"""
    )
