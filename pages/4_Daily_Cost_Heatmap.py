import plotly.express as px
import streamlit as st

from hk_dashboard.aggregations import daily_person_matrix
from hk_dashboard.data import get_dashboard_data, render_coverage_sidebar
from hk_dashboard.excel_export import export_workbook

st.title("Daily Cost by Person")

load_result, rates_df, shifts = get_dashboard_data()
render_coverage_sidebar(load_result)

if shifts.empty:
    st.info("No data loaded yet.")
    st.stop()

months = sorted(shifts["month"].unique())
col1, col2 = st.columns(2)
selected_month = col1.selectbox("Month", months, index=len(months) - 1)
value_choice = col2.radio("Show", ["Cost (EUR)", "Hours"], horizontal=True)
value_col = "cost_eur" if value_choice == "Cost (EUR)" else "hours"

matrix = daily_person_matrix(shifts, selected_month, value=value_col)

if matrix.empty:
    st.info("No data for this month.")
else:
    if value_col == "cost_eur":
        month_rows = shifts[shifts["month"] == selected_month]
        missing_by_person = month_rows.loc[month_rows["rate_missing"], "employee"].unique()
        if len(missing_by_person):
            st.warning(
                f"⚠️ No payroll rate on file for: {', '.join(sorted(missing_by_person))} "
                f"in {selected_month}. Their cost cells show as €0.00 here rather than a guess "
                "- check the Per Housekeeper page for the full flag."
            )

    fig = px.imshow(
        matrix,
        aspect="auto",
        color_continuous_scale="YlOrRd",
        labels=dict(x="Date", y="Housekeeper", color=value_choice),
        title=f"{value_choice} per person per day - {selected_month}",
    )
    st.plotly_chart(fig, use_container_width=True)

    display_df = matrix.reset_index()
    fmt = {c: ("€{:.2f}" if value_col == "cost_eur" else "{:.1f}") for c in matrix.columns}
    st.dataframe(display_df.style.format(fmt), use_container_width=True, hide_index=True)

    st.download_button(
        "⬇️ Export this view to Excel",
        data=export_workbook(
            {
                "Daily Cost by Person": {
                    "df": display_df,
                    "title": f"Daily {value_choice} by Person - {selected_month}",
                    "currency_cols": tuple(matrix.columns) if value_col == "cost_eur" else (),
                    "hours_cols": tuple(matrix.columns) if value_col == "hours" else (),
                    "total_row": False,
                }
            }
        ),
        file_name=f"hk_daily_{value_col}_{selected_month}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
