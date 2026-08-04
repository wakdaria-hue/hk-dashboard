"""Admin-only join logic for pages/9_Hours_Submission.py - compares live
reception hours against housekeeper self-reports. Kept out of
aggregations.py, which is payroll-cost-focused, not confirmation-focused.
"""
from __future__ import annotations

import pandas as pd

from hk_dashboard.config import MISMATCH_THRESHOLD_MINUTES
from hk_dashboard.reception_hours import daily_reception_hours

_MATCH_TOLERANCE_HOURS = 1 / 3600  # ~1 second, float-equality slack


def build_comparison_table(
    shifts: pd.DataFrame, self_reports_df: pd.DataFrame, month: str, hotel: str
) -> pd.DataFrame:
    """One row per (date, employee) with reception hours for `hotel` in
    `month` ('YYYY-MM'), joined against any matching self-report.

    "Reception corrects hours after employee already confirmed" is handled
    here, at read time: if the self-report's stored reception_hours_numeric
    snapshot no longer matches the live number, the row is treated as
    effectively Not confirmed regardless of what status is stored - no
    background job needed to go back and edit old rows.
    """
    daily = daily_reception_hours(shifts)
    daily = daily[(daily["hotel"] == hotel) & (daily["date"].astype(str).str.startswith(month))]

    if daily.empty:
        return pd.DataFrame(
            columns=[
                "date", "employee", "reception_hours", "reception_display",
                "status", "self_reported_hours", "difference_minutes", "highlight_reason",
            ]
        )

    reports = pd.DataFrame()
    if not self_reports_df.empty:
        reports = self_reports_df[
            (self_reports_df["hotel"] == hotel) & (self_reports_df["date"].astype(str).str.startswith(month))
        ].copy()
        reports["date"] = pd.to_datetime(reports["date"]).dt.date

    rows = []
    for _, r in daily.iterrows():
        report_row = None
        if not reports.empty:
            match = reports[(reports["date"] == r["date"]) & (reports["name"] == r["employee"])]
            if not match.empty:
                report_row = match.iloc[0]

        status = "Not confirmed"
        self_reported_hours = None
        difference_minutes = None

        if report_row is not None:
            snapshot = report_row["reception_hours_numeric"]
            snapshot_matches = pd.notna(snapshot) and abs(float(snapshot) - r["hours"]) <= _MATCH_TOLERANCE_HOURS
            if snapshot_matches:
                status = report_row["status"]
                if status == "Confirmed":
                    self_reported_hours = r["hours"]
                    difference_minutes = 0.0
                elif status == "Disputed":
                    self_reported_hours = report_row["disputed_hours_numeric"]
                    if pd.notna(self_reported_hours):
                        difference_minutes = abs(r["hours"] - float(self_reported_hours)) * 60
            # else: reception changed after the housekeeper reported - stays "Not confirmed"

        highlight_reason = None
        if status == "Disputed":
            highlight_reason = "disputed"
        elif difference_minutes is not None and difference_minutes > MISMATCH_THRESHOLD_MINUTES:
            highlight_reason = "mismatch"

        rows.append(
            {
                "date": r["date"],
                "employee": r["employee"],
                "reception_hours": r["hours"],
                "reception_display": r["display_range"],
                "status": status,
                "self_reported_hours": self_reported_hours,
                "difference_minutes": difference_minutes,
                "highlight_reason": highlight_reason,
            }
        )

    return pd.DataFrame(rows).sort_values(["date", "employee"]).reset_index(drop=True)


def zero_confirmation_summary(shifts: pd.DataFrame, self_reports_df: pd.DataFrame, hotel: str) -> pd.DataFrame:
    """Per-person, per-month: worked days with zero Confirmed self-reports
    that month - a whole month someone never once tapped "Yes, correct",
    surfaced as its own summary rather than buried in daily rows."""
    daily = daily_reception_hours(shifts)
    daily = daily[daily["hotel"] == hotel]
    if daily.empty:
        return pd.DataFrame(columns=["employee", "month", "worked_days"])

    daily = daily.copy()
    daily["month"] = daily["date"].astype(str).str.slice(0, 7)
    worked = daily.groupby(["employee", "month"], as_index=False).agg(worked_days=("date", "nunique"))

    confirmed_months: set[tuple[str, str]] = set()
    if not self_reports_df.empty:
        reports = self_reports_df[
            (self_reports_df["hotel"] == hotel) & (self_reports_df["status"] == "Confirmed")
        ].copy()
        reports["month"] = reports["date"].astype(str).str.slice(0, 7)
        confirmed_months = set(zip(reports["name"], reports["month"]))

    worked["has_confirmation"] = worked.apply(
        lambda r: (r["employee"], r["month"]) in confirmed_months, axis=1
    )
    zero = worked[~worked["has_confirmation"]].drop(columns=["has_confirmation"])
    return zero.sort_values(["month", "employee"]).reset_index(drop=True)
