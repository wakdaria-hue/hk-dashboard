"""Static configuration: hotel sheet IDs and the nickname -> payroll-name map."""

HOTEL_SHEETS = {
    "VGH": "1Z114WcbhnoFsLhpDihtwWzkeCi0DeGW4hKo_mWt1D8M",
    "PLH": "1eYndJLyLbKgaRqWNBwjs-cT9k89NPhhptd-J6g-qr9k",
    "KOOYK": "13odazl_p4yAvlALrKRCeig4Q-7HK_jF4gFDswnTTxPY",
    "HAI": "12G_By9prEiGvTB0T0pjcmDEmdcVJ3glthE7Jh4gvitU",
}

# Nickname / first-name (as it appears in the HK schedule sheets) -> payroll
# "Initials Surname" (as it appears in the Overzicht Loonkosten PDF).
# Extend this as new unmapped names get flagged by the app.
NAME_MAP = {
    "scaley": "SM Bonsu",
    "skaley": "SM Bonsu",
    "joshua": "J C Dos Santos",
    "bandra": "B P Delgado Medrano",
    "katarzyna": "K Filipinska",
    "sayora": "S Kosimova",
    "joyce": "J Owusu",
    "mir": "M Shaon",
    "tibi": "T Doaga",
    "nino": "N Mantashashvili",
    "sadia": "S Afrin",
    "sundus": "S Jama",
    "sundos": "S Jama",
    "ivan": "I Zadorozhnyi",
    "kiko": "F Rodrigues Prudencio",
    "lyudmila": "L Usatiuk",
    "diana": "D A Agyemang",
    "marina": "M Zarovniaieva",
    "federico": "F Rodrigues Prudencio",
    "frederico": "F Rodrigues Prudencio",
    "mariia": "M Chechul",
    "raisa": "R Tretiak",
    "raiza": "R Tretiak",
    "sayara": "S Kosimova",
    "vasyliy": "V Mirza",
    "lucila": "L Colombo",
    "nerea": "N Nunez Fernandez",
    "natalie": "N Chyniakina",
    "natalia": "N Chyniakina",
    "ravan": "S Baishnab",
    "anna": "A Grigoriadi",
    # New hires not yet on payroll - will get a real rate_store entry once
    # their first payroll PDF (July 2026) is uploaded.
    "faith": "F Ugbena",
    "leila": "R Nistorova",
}

# First names of external/agency staff who worked shifts but are never on the
# "Overzicht Loonkosten" payroll export - they're paid a flat rate outside
# this payroll system. Their hours count normally everywhere; their cost uses
# this flat rate instead of a rate_store lookup (see aggregations.attach_costs).
EXTERNAL_WORKER_RATES = {
    "olena": 14.50,
    "nelly": 14.50,
    "alexandra": 14.50,
    "dominika": 14.50,
    "ruby": 14.50,
    "veronika": 14.50,
    "yaroslava": 14.50,
}

# Name of the tab (within the rate-history spreadsheet) that stores parsed
# payroll rates. The spreadsheet ID itself is a Streamlit secret
# (see secrets.toml.example) because it's created once per deployment.
RATE_STORE_WORKSHEET = "rates"
RATE_STORE_HEADER = ["name", "month", "hourly_rate_eur", "netto_salary_eur", "source", "upload_date"]

MONTH_NAMES_NL_EN = {
    # English month names as used in the HK sheets (e.g. "01-June-2026")
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}

# Dutch month names as used in the payroll PDF ("Verloningsjaar 2026", "Per." column
# is numeric 1..12, but some PDF sections spell out the month name in Dutch headers).
MONTH_NAMES_DUTCH = {
    "januari": 1, "februari": 2, "maart": 3, "april": 4, "mei": 5, "juni": 6,
    "juli": 7, "augustus": 8, "september": 9, "oktober": 10, "november": 11, "december": 12,
}
