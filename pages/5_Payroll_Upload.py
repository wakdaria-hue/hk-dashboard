import streamlit as st

from hk_dashboard.data import clear_cache, get_rate_store_id, get_rates
from hk_dashboard.payroll_pdf import PayrollPdfError, extract_payroll_data, rows_to_preview_df
from hk_dashboard.rate_store import clear_rate_store, delete_rate_rows, upsert_rates
from hk_dashboard.sheets_client import SheetAccessError

st.title("Payroll Upload")
st.caption(
    "Upload this month's 'Overzicht Loonkosten' PDF export (company 1780 Hotelonderhoud). "
    "Preview the parsed rows before saving - nothing is written to the rate store until you confirm."
)

spreadsheet_id = get_rate_store_id()

try:
    current = get_rates()
except SheetAccessError as e:
    st.error(f"Can't reach the rate-history sheet right now: {e}\n\nTry again in a minute or two.")
    st.stop()

uploaded = st.file_uploader("Overzicht Loonkosten PDF", type=["pdf"])

if uploaded is not None:
    try:
        payroll_data = extract_payroll_data(uploaded)
    except PayrollPdfError as e:
        st.error(str(e))
        st.stop()

    preview_df = rows_to_preview_df(payroll_data)
    months_found = sorted(preview_df["month"].unique())
    st.success(f"Parsed {len(preview_df)} row(s) covering {len(months_found)} month(s): {', '.join(months_found)}.")

    if payroll_data.netto_period:
        netto_month = f"{payroll_data.netto_period[0]:04d}-{payroll_data.netto_period[1]:02d}"
        netto_count = len(payroll_data.netto_by_employee_number)
        st.info(
            f"ℹ️ Found net salary (payslip) data for {netto_count} employee(s), all for {netto_month} "
            "- individual payslips only cover this PDF's own pay period, not the full cumulative history "
            "shown in the hourly-rate table above."
        )
    else:
        st.warning(
            "⚠️ No individual payslip pages (net salary) found in this PDF - only the employer-cost "
            "table will be saved. Net salary for these months will show as unavailable until a PDF "
            "with payslips for them is uploaded."
        )

    st.markdown("**Preview - check this before saving:**")
    st.dataframe(
        preview_df.style.format(
            {
                "hours": "{:.1f}",
                "hourly_rate_eur": "€{:.2f}",
                "loon_kosten_eur": "€{:.2f}",
                "netto_salary_eur": "€{:.2f}",
            },
            na_rep="-",
        ),
        use_container_width=True,
        hide_index=True,
    )

    if not current.empty:
        overlap = current[current["month"].isin(months_found)]
        if not overlap.empty:
            st.info(
                f"{len(overlap)} existing rate-store row(s) for these months will be **overwritten** "
                "with the values parsed from this PDF (upsert on name + month, not summed or duplicated). "
                "Net salary is only overwritten for months this PDF actually has payslips for - other "
                "months' previously-saved net salary is left untouched."
            )

    st.divider()
    source_label = st.text_input("Source label (for the audit trail)", value=uploaded.name)
    if st.button("✅ Save these rates to the rate store", type="primary"):
        with st.spinner("Writing to the rate-history Google Sheet..."):
            upsert_rates(spreadsheet_id, payroll_data, source_label=source_label)
            clear_cache()
        st.success("Saved. The dashboard will use these rates from now on.")
        st.rerun()

st.divider()
st.subheader("Current rate store")
if current.empty:
    st.info("No payroll rates saved yet.")
else:
    display = current.sort_values(["month", "name"]).reset_index(drop=True)
    st.caption("Click a row (or drag across several) to select it, then delete below if it was added by mistake.")
    event = st.dataframe(
        display,
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="multi-row",
        column_config={
            "hourly_rate_eur": st.column_config.NumberColumn("hourly_rate_eur", format="€%.2f"),
            "netto_salary_eur": st.column_config.NumberColumn("netto_salary_eur", format="€%.2f"),
        },
        key="rate_store_table",
    )

    selected_positions = event.selection.rows
    if selected_positions:
        to_delete = display.iloc[selected_positions]
        st.warning(f"⚠️ {len(to_delete)} row(s) selected for deletion:")
        st.dataframe(
            to_delete[["name", "month", "hourly_rate_eur", "netto_salary_eur", "source"]],
            use_container_width=True,
            hide_index=True,
        )
        confirm_selected = st.checkbox("Yes, delete these rows")
        if st.button("🗑️ Delete selected rows", type="primary", disabled=not confirm_selected):
            keys = list(zip(to_delete["name"], to_delete["month"]))
            with st.spinner("Deleting from the rate-history Google Sheet..."):
                delete_rate_rows(spreadsheet_id, keys)
                clear_cache()
            st.success(f"Deleted {len(keys)} row(s).")
            st.rerun()

    with st.expander("⚠️ Danger zone: clear the entire rate store"):
        st.write(
            "Removes every saved payroll rate and net salary for every month. "
            "You'll need to re-upload payroll PDFs afterward to rebuild it."
        )
        confirm_all = st.text_input("Type CLEAR to confirm", value="", key="confirm_clear_all")
        if st.button("🗑️ Clear entire rate store", disabled=(confirm_all != "CLEAR")):
            with st.spinner("Clearing the rate-history Google Sheet..."):
                clear_rate_store(spreadsheet_id)
                clear_cache()
            st.success("Rate store cleared.")
            st.rerun()
