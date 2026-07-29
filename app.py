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
"""
)

st.divider()
with st.expander("Phase 2 (not built): cost forecasting"):
    st.markdown(
        """
A future phase could forecast cleaning cost using predicted HK hours combined
with reservation/occupancy data from Mews (via its Connector API). This isn't
built yet — no Mews API credentials exist for this project. The data model
here (per-hotel, per-day shift records with hours and cost) is intentionally
kept granular so a forecast view could be added later without reshaping
existing data.
"""
    )
