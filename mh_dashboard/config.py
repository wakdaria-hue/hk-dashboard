"""Static configuration for the Mobile Host Hours Confirmation app.

Sibling of hk_dashboard, reusing its generic Sheets-auth plumbing
(sheets_client) and Amsterdam-time helpers (timeutil) directly rather than
duplicating them - see mh_dashboard/README note in the repo README.
"""

# The Mobile Host weekly schedule Google Sheet (owned by ariboh@gmail.com,
# shared Viewer with the service account). One tab per month, e.g. "August
# 2026". Read-only - this app never writes to it.
MH_SCHEDULE_SPREADSHEET_ID = "1B_CMU9c_lVuzf5Wb7gU4Bd5XIMPZE7e-6aitfGLM94c"

# The four shift rows in each week block, exactly as they appear in the
# schedule (label text match is case-sensitive on purpose - if the sheet's
# wording ever drifts, we want a loud "week block not found" rather than a
# silently-wrong grid position).
SHIFT_LABELS = ["MORNING 7-15", "MID-SHIFT 13-21", "EVENING 15-23", "NIGHT 23-7"]
SHIFT_HOURS = 8.0
DAYS_PER_WEEK_BLOCK = 7

# Tokens that appear in shift cells but are NOT a person - generic coverage
# placeholders, confirmed with Daria 2026-08-06. Silently skipped: not
# counted as a shift for anyone, and NOT logged to mapping_issues (they're
# expected, not typos). Whoever actually covered that shift can flag the
# missing date themselves via the dispute flow.
PLACEHOLDER_TOKENS = {"ph mobile", "mobile team"}

# Only the LEFT-hand grid in each week block is real Mobile Host data
# (confirmed with Daria 2026-08-06) - a second, unlabeled grid sometimes
# sits to the right of it in the same tab and must be ignored entirely.

# --- Mobile Host Hours Confirmation store -----------------------------------
# Worksheet tabs live in a separate spreadsheet from the schedule above (id
# in the `mh_confirmation_spreadsheet_id` secret) - the schedule sheet isn't
# owned by us and is only ever read, never written to. Tabs are created
# lazily on first access, same as the HK confirmation store.
EMPLOYEE_ACCESS_WORKSHEET = "employee_access"
CONFIRMATIONS_WORKSHEET = "confirmations"
MAPPING_ISSUES_WORKSHEET = "mapping_issues"

# One row per known raw schedule spelling -> payroll full name. Multiple
# rows can share the same full_name (aliases/nicknames), each carrying its
# own copy of the birthdate. A raw schedule name with no matching row here
# is never guessed at - it's logged to mapping_issues instead (see
# mh_dashboard.parser).
EMPLOYEE_ACCESS_HEADER = ["schedule_name", "full_name", "birthdate", "active"]

# One row per (month, full_name) - upserted, last write wins. Many
# independent concurrent writers (different hosts confirming around the same
# few days each month), so this follows self_report_store's find-row-then-
# update-or-append pattern, not rate_store's clear-and-rewrite.
CONFIRMATIONS_HEADER = [
    "month", "full_name", "status",
    "shift_count", "total_hours", "dates_worked",
    "disputed_dates", "comment",
    "confirmed_at",
]

# Append-only. One row per unmapped raw name encountered while parsing a
# given month tab - written quietly in the background so Daria can review
# and fix employee_access without anything blocking the host-facing app.
MAPPING_ISSUES_HEADER = ["date_logged", "month_tab", "raw_name"]

# --- Date gating (Europe/Amsterdam calendar day) ----------------------------
# Day 1-19: too early. Day 20-23: confirm window. Day 24+: read-only,
# hours are already being processed for payroll.
EARLY_WINDOW_LAST_DAY = 19
CONFIRM_WINDOW_FIRST_DAY = 20
CONFIRM_WINDOW_LAST_DAY = 23
LOCKED_WINDOW_FIRST_DAY = 24

# Birthdate check lockout (reuses hk_dashboard.lockout, keyed by a constant
# "scope" in place of HK's per-hotel key - see mobile_hosts/confirm_app.py).
LOCKOUT_SCOPE = "mobile-host"

# Mobile Hosts on a fixed weekly-hours contract rather than paid per logged
# shift - their real schedule entries are too sparse to reflect what they
# actually work, so their monthly total is computed from this instead of
# monthly_summary's shift count (see mobile_hosts/confirm_app.py). Confirmed
# with Daria 2026-08-18: only P Mansouri - M Shukry's schedule data is real
# and already exceeds this baseline, so he stays on real shift-based hours.
FIXED_WEEKLY_HOURS = {
    "P Mansouri": 40.0,
}
