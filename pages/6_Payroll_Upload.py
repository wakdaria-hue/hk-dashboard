import streamlit as st

from hk_dashboard.data import clear_cache, get_rate_store_id
from hk_dashboard.payroll_pdf import PayrollPdfError, extract_loonkosten_rows, rows_to_preview_df
from hk_dashboard.rate_store import read_rate_store, upsert_rates

st.title("Payroll Upload")
st.caption(
    "Upload this month's 'Overzicht Loonkosten' PDF export (company 1780 Hotelonderhoud). "
    "Preview the parsed rows before saving - nothing is written to the rate store until you confirm."
)

spreadsheet_id = get_rate_store_id()

uploaded = st.file_uploader("Overzicht Loonkosten PDF", type=["pdf"])

if uploaded is not None:
    try:
        rows = extract_loonkosten_rows(uploaded)
    except PayrollPdfError as e:
        st.error(str(e))
        st.stop()

    preview_df = rows_to_preview_df(rows)
    months_found = sorted(preview_df["month"].unique())
    st.success(f"Parsed {len(preview_df)} row(s) covering {len(months_found)} month(s): {', '.join(months_found)}.")

    st.markdown("**Preview - check this before saving:**")
    st.dataframe(
        preview_df.style.format({"hours": "{:.1f}", "hourly_rate_eur": "€{:.2f}", "loon_kosten_eur": "€{:.2f}"}),
        use_container_width=True,
        hide_index=True,
    )

    existing = read_rate_store(spreadsheet_id)
    if not existing.empty:
        overlap = existing[existing["month"].isin(months_found)]
        if not overlap.empty:
            st.info(
                f"{len(overlap)} existing rate-store row(s) for these months will be **overwritten** "
                "with the values parsed from this PDF (upsert on name + month, not summed or duplicated)."
            )

    st.divider()
    source_label = st.text_input("Source label (for the audit trail)", value=uploaded.name)
    if st.button("✅ Save these rates to the rate store", type="primary"):
        with st.spinner("Writing to the rate-history Google Sheet..."):
            upsert_rates(spreadsheet_id, rows, source_label=source_label)
            clear_cache()
        st.success("Saved. The dashboard will use these rates from now on.")
        st.rerun()

st.divider()
st.subheader("Current rate store")
current = read_rate_store(spreadsheet_id)
if current.empty:
    st.info("No payroll rates saved yet.")
else:
    st.dataframe(
        current.sort_values(["month", "name"]).style.format({"hourly_rate_eur": "€{:.2f}"}),
        use_container_width=True,
        hide_index=True,
    )
