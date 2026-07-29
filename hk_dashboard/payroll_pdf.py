"""Parse the payroll PDF export: the 'Overzicht Loonkosten' cost table plus
individual payslip pages (for net salary).

Format confirmed against a real export (company 1780 Hotelonderhoud,
Jan-Jun 2026).

## Overzicht Loonkosten (employer cost per employee per pay period)

Every page belonging to this report repeats the section header "Overzicht
Loonkosten" and a "Verloningsjaar <year>" line; each employee's block has
one row per pay period ("Per." column, e.g. "3,0" = period/month 3),
optionally followed by a subtotal row (numbers only, no name) when the
employee has more than one period in the export. The last number on each
period row ("Lkstn/uur") is the loaded hourly cost we need. Employee names
here are already in the "Initials Surname" format used across the rest of
the dashboard (e.g. "SM Bonsu", "K Filipinska"). Only the *first* row of an
employee's block has a leading employee number - later rows repeat the name
without it, so it's forward-filled.

## Individual payslips (net salary)

Each payslip page has a "Werknemersnummer <N>" line and a "Nettoloon
<amount>" line - both extract in reliable reading order. The rest of a
payslip's demographic fields (Verloningstijdvak, Beroep, etc.) do NOT
extract in reading order with pdfplumber - the values print as one block
followed by their labels as a second block, and the number of fields varies
by contract type (an "Uitdienstdatum" line appears only for fixed-term
contracts), so position-matching a value to "Verloningstijdvak" is fragile.
Instead: a single payroll PDF export covers exactly one pay period (its own
"Collectieve aangifte <month> <year>" cover-page heading), so every payslip
inside it shares that same period - read once, not per payslip page.

The employee number is the reliable join key between the two sections
(rather than re-deriving "Initials Surname" from a payslip's ALL-CAPS
"FIRSTNAME LASTNAME" line, which risks not matching NAME_MAP's existing
convention, e.g. middle initials it includes that the payslip's plain name
doesn't show).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import pandas as pd
import pdfplumber

from hk_dashboard.config import MONTH_NAMES_DUTCH

YEAR_RE = re.compile(r"Verloningsjaar\s+(\d{4})")
DECLARATION_PERIOD_RE = re.compile(r"Collectieve aangifte\s+([A-Za-z]+)\s+(\d{4})", re.IGNORECASE)
WERKNEMERSNUMMER_RE = re.compile(r"Werknemersnummer\s+(\d+)")
NETTOLOON_RE = re.compile(r"Nettoloon\s+([\d.,]+)")

ROW_RE = re.compile(
    r"^(?:(?P<empno>\d+)\s+)?"  # optional leading employee number (only on an employee's first row)
    r"(?P<name>[A-Za-zÀ-ſ][A-Za-zÀ-ſ.'\- ]*?)\s+"
    r"(?P<period>\d{1,2}),0\s+"
    r"(?P<belast>[\d.,]+)\s+"
    r"(?P<onbelast>[\d.,]+)\s+"
    r"(?P<werkg_lasten>[\d.,]+)\s+"
    r"(?P<loon_kosten>[\d.,]+)\s+"
    r"(?P<uren>[\d.,]+)\s+"
    r"(?P<lkstn_uur>[\d.,]+)\s*$"
)


class PayrollPdfError(Exception):
    pass


def _parse_nl_number(text: str) -> float:
    return float(text.replace(".", "").replace(",", "."))


@dataclass
class LoonkostenRow:
    name: str
    year: int
    month: int
    hours: float
    hourly_rate_eur: float
    loon_kosten_eur: float
    employee_number: int | None = None

    @property
    def month_str(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"


@dataclass
class PayrollData:
    loonkosten_rows: list[LoonkostenRow]
    netto_by_employee_number: dict[int, float] = field(default_factory=dict)
    netto_period: tuple[int, int] | None = None  # (year, month) the netto figures apply to


def extract_payroll_data(file) -> PayrollData:
    """Parse an uploaded payroll PDF in a single pass.

    `file` is anything pdfplumber.open() accepts: a path, or a file-like
    object (e.g. Streamlit's UploadedFile).
    """
    loonkosten_rows: list[LoonkostenRow] = []
    year: int | None = None
    last_empno: int | None = None
    declaration_period: tuple[int, int] | None = None
    netto_by_empno: dict[int, float] = {}

    try:
        with pdfplumber.open(file) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                lower = text.lower()

                if declaration_period is None:
                    dm = DECLARATION_PERIOD_RE.search(text)
                    if dm:
                        month_num = MONTH_NAMES_DUTCH.get(dm.group(1).lower())
                        if month_num:
                            declaration_period = (int(dm.group(2)), month_num)

                if "overzicht loonkosten" in lower:
                    if year is None:
                        ym = YEAR_RE.search(text)
                        if ym:
                            year = int(ym.group(1))

                    for line in text.splitlines():
                        m = ROW_RE.match(line.strip())
                        if not m:
                            continue
                        if m.group("empno"):
                            last_empno = int(m.group("empno"))
                        loonkosten_rows.append(
                            LoonkostenRow(
                                name=m.group("name").strip(),
                                employee_number=last_empno,
                                year=year or 0,
                                month=int(m.group("period")),
                                hours=_parse_nl_number(m.group("uren")),
                                hourly_rate_eur=_parse_nl_number(m.group("lkstn_uur")),
                                loon_kosten_eur=_parse_nl_number(m.group("loon_kosten")),
                            )
                        )

                empno_match = WERKNEMERSNUMMER_RE.search(text)
                netto_match = NETTOLOON_RE.search(text)
                if empno_match and netto_match:
                    netto_by_empno[int(empno_match.group(1))] = _parse_nl_number(netto_match.group(1))
    except Exception as e:  # noqa: BLE001
        raise PayrollPdfError(f"Could not parse PDF: {e}") from e

    if year is None:
        raise PayrollPdfError(
            "Couldn't find an 'Overzicht Loonkosten' section with a 'Verloningsjaar' "
            "year in this PDF. Is this the right export from the payroll system?"
        )
    if not loonkosten_rows:
        raise PayrollPdfError(
            "Found an 'Overzicht Loonkosten' section but couldn't parse any rows from it. "
            "The column layout may differ from what this parser expects - "
            "please share this PDF so the parser can be adjusted."
        )

    return PayrollData(
        loonkosten_rows=loonkosten_rows,
        netto_by_employee_number=netto_by_empno,
        netto_period=declaration_period,
    )


def rows_to_preview_df(data: PayrollData) -> pd.DataFrame:
    records = []
    for r in data.loonkosten_rows:
        netto = None
        if (
            data.netto_period
            and (r.year, r.month) == data.netto_period
            and r.employee_number is not None
        ):
            netto = data.netto_by_employee_number.get(r.employee_number)
        records.append(
            {
                "name": r.name,
                "month": r.month_str,
                "hours": r.hours,
                "hourly_rate_eur": r.hourly_rate_eur,
                "loon_kosten_eur": r.loon_kosten_eur,
                "netto_salary_eur": netto,
            }
        )
    df = pd.DataFrame(records)
    return df.sort_values(["name", "month"]).reset_index(drop=True)
