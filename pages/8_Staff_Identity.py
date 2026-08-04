from datetime import date

import streamlit as st

from hk_dashboard.config import HOTEL_SHEETS
from hk_dashboard.data import clear_cache, get_confirmation_spreadsheet_id, get_raw_shifts, get_staff
from hk_dashboard.sheets_client import SheetAccessError
from hk_dashboard.staff_store import delete_staff_rows, upsert_staff_row

st.title("Staff Identity")
st.caption(
    "The list housekeepers pick themselves from on the login-free confirmation page. "
    "Name must match how reception's sheet identifies them, so it's picked from a dropdown, not typed."
)

spreadsheet_id = get_confirmation_spreadsheet_id()

try:
    current = get_staff()
except SheetAccessError as e:
    st.error(f"Can't reach the confirmation sheet right now: {e}\n\nTry again in a minute or two.")
    st.stop()

shifts = get_raw_shifts()

st.subheader("Add / update a staff member")
with st.form("add_staff", clear_on_submit=True):
    c1, c2 = st.columns(2)
    hotel = c1.selectbox("Hotel", sorted(HOTEL_SHEETS))
    employee_options = sorted(shifts.loc[shifts["hotel"] == hotel, "employee"].unique()) if not shifts.empty else []
    name = c2.selectbox(
        "Name (from reception's sheet)",
        employee_options,
        help="Pulled from real shift data for this hotel, so it's guaranteed to match reception's spelling.",
    )
    c3, c4 = st.columns(2)
    birthdate = c3.date_input("Birthdate", value=None, min_value=date(1940, 1, 1), max_value=date.today())
    active = c4.checkbox("Active", value=True)
    submitted = st.form_submit_button("Save", type="primary")

    if submitted:
        if not employee_options:
            st.warning("No shift data found for this hotel yet - can't confirm a name to add.")
        elif birthdate is None:
            st.warning("Please set a birthdate.")
        else:
            with st.spinner("Saving to the confirmation sheet..."):
                upsert_staff_row(spreadsheet_id, name=name, hotel=hotel, birthdate=birthdate, active=active)
                clear_cache()
            st.success(f"Saved {name} ({hotel}).")
            st.rerun()

st.divider()
st.subheader("Current staff list")
if current.empty:
    st.info("No staff added yet.")
else:
    display = current.sort_values(["hotel", "name"]).reset_index(drop=True)
    st.caption("Click a row (or drag across several) to select it, then delete below if it was added by mistake.")
    event = st.dataframe(
        display,
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="multi-row",
        key="staff_table",
    )

    selected_positions = event.selection.rows
    if selected_positions:
        to_delete = display.iloc[selected_positions]
        st.warning(f"⚠️ {len(to_delete)} row(s) selected for deletion:")
        st.dataframe(to_delete, use_container_width=True, hide_index=True)
        confirm_selected = st.checkbox("Yes, delete these rows")
        if st.button("🗑️ Delete selected rows", type="primary", disabled=not confirm_selected):
            keys = list(zip(to_delete["name"], to_delete["hotel"]))
            with st.spinner("Deleting from the confirmation sheet..."):
                delete_staff_rows(spreadsheet_id, keys)
                clear_cache()
            st.success(f"Deleted {len(keys)} row(s).")
            st.rerun()
