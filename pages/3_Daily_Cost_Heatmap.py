import plotly.express as px
import streamlit as st

from hk_dashboard.aggregations import daily_person_matrix, monthly_person_matrix, weekly_person_matrix
from hk_dashboard.data import get_dashboard_data, render_coverage_sidebar
from hk_dashboard.excel_export import export_workbook

st.title("Cost Heatmap by Person")

load_result, rates_df, shifts = get_dashboard_data()
render_coverage_sidebar(load_result)

if shifts.empty:
    st.info("No data loaded yet.")
    st.stop()

months = sorted(shifts["month"].unique())

col1, col2 = st.columns(2)
granularity = col1.radio("Columns", ["Month", "Week", "Day"], horizontal=True)
value_choice = col2.radio("Show", ["Cost (EUR)", "Hours"], horizontal=True)
value_col = "cost_eur" if value_choice == "Cost (EUR)" else "hours"

if granularity == "Month":
    matrix = monthly_person_matrix(shifts, value=value_col)
    x_label, title_suffix = "Month", "per month (all loaded months)"
    month_scope = None
else:
    selected_month = st.selectbox("Month", months, index=len(months) - 1)
    month_scope = selected_month
    if granularity == "Week":
        matrix = weekly_person_matrix(shifts, selected_month, value=value_col)
        x_label, title_suffix = "Week", f"per week - {selected_month}"
    else:
        matrix = daily_person_matrix(shifts, selected_month, value=value_col)
        x_label, title_suffix = "Date", f"per day - {selected_month}"

if matrix.empty:
    st.info("No data for this selection yet.")
else:
    if value_col == "cost_eur":
        scoped_rows = shifts if month_scope is None else shifts[shifts["month"] == month_scope]
        missing_by_person = scoped_rows.loc[scoped_rows["rate_missing"], "employee"].unique()
        if len(missing_by_person):
            st.warning(
                f"⚠️ No payroll rate on file for: {', '.join(sorted(missing_by_person))}"
                f"{f' in {month_scope}' if month_scope else ''}. Their cost cells show as €0.00 "
                "here rather than a guess - check the Per Housekeeper page for the full flag."
            )

    fig = px.imshow(
        matrix,
        aspect="auto",
        color_continuous_scale="YlOrRd",
        labels=dict(x=x_label, y="Housekeeper", color=value_choice),
        title=f"{value_choice} {title_suffix}",
    )
    st.plotly_chart(fig, use_container_width=True)

    display_df = matrix.reset_index()
    fmt = {c: ("€{:.2f}" if value_col == "cost_eur" else "{:.1f}") for c in matrix.columns}
    st.dataframe(display_df.style.format(fmt), use_container_width=True, hide_index=True)

    file_scope = month_scope or "all_months"
    st.download_button(
        "⬇️ Export this view to Excel",
        data=export_workbook(
            {
                "Cost Heatmap": {
                    "df": display_df,
                    "title": f"{value_choice} {title_suffix}",
                    "currency_cols": tuple(matrix.columns) if value_col == "cost_eur" else (),
                    "hours_cols": tuple(matrix.columns) if value_col == "hours" else (),
                    "total_row": False,
                }
            }
        ),
        file_name=f"hk_heatmap_{value_col}_{granularity.lower()}_{file_scope}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
