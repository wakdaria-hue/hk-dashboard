"""Temporary diagnostic page - shows exactly what the real Google Sheets API
returns for a hotel, so parsing issues can be pinpointed. Safe to delete once
the parser is confirmed working correctly against real data."""
import streamlit as st

from hk_dashboard.config import HOTEL_SHEETS
from hk_dashboard.sheets_client import SheetAccessError, fetch_hotel_sheet_raw

st.title("Debug: Raw Sheet Data")
st.caption("Temporary page for verifying the parser against real API output. Delete pages/9_Debug_Raw_Data.py once confirmed.")

hotel = st.selectbox("Hotel", list(HOTEL_SHEETS.keys()))

try:
    tabs = fetch_hotel_sheet_raw(HOTEL_SHEETS[hotel])
except SheetAccessError as e:
    st.error(str(e))
    st.stop()

st.subheader(f"{len(tabs)} tab(s) found")
st.write([{"tab": title, "rows": len(formatted)} for title, formatted, _ in tabs])

tab_titles = [t[0] for t in tabs]
selected_tab = st.selectbox("Inspect tab", tab_titles)
_title, formatted, unformatted = next(t for t in tabs if t[0] == selected_tab)

st.write(f"Rows in '{selected_tab}': **{len(formatted)}**")

st.subheader("First 15 rows (FORMATTED_VALUE)")
st.write(formatted[:15])

st.subheader("Last 15 rows (FORMATTED_VALUE)")
st.write(formatted[-15:])

st.subheader("Rows 1 through 15 (UNFORMATTED_VALUE)")
st.write(unformatted[:15])
