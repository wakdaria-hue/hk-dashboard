"""Parse the 'Overzicht Loonkosten' section of the monthly payroll PDF export.

Format confirmed against a real export (company 1780 Hotelonderhoud,
Jan-Jun 2026). Every page belonging to this report repeats the section
header "Overzicht Loonkosten" and a "Verloningsjaar <year>" line; each
employee's block has one row per pay period ("Per." column, e.g. "3,0" =
period/month 3), optionally followed by a subtotal row (numbers only, no
name) when the employee has more than one period in the export. The last
number on each period row ("Lkstn/uur") is the loaded hourly cost we need.

Employee names in this report are already in the "Initials Surname" format
used across the rest of the dashboard (e.g. "SM Bonsu", "K Filipinska").
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass

import pandas as pd
import pdfplumber

YEAR_RE = re.compile(r"Verloningsjaar\s+(\d{4})")

ROW_RE = re.compile(
    r"^(?:\d+\s+)?"  # optional leading employee number (only on an employee's first row)
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

    @property
    def month_str(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"


def extract_loonkosten_rows(file) -> list[LoonkostenRow]:
    """Parse an uploaded 'Overzicht Loonkosten' PDF.

    `file` is anything pdfplumber.open() accepts: a path, or a file-like
    object (e.g. Streamlit's UploadedFile, which is already a BytesIO-like
    object).
    """
    rows: list[LoonkostenRow] = []
    year: int | None = None

    try:
        with pdfplumber.open(file) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                if "overzicht loonkosten" not in text.lower():
                    continue

                if year is None:
                    ym = YEAR_RE.search(text)
                    if ym:
                        year = int(ym.group(1))

                for line in text.splitlines():
                    m = ROW_RE.match(line.strip())
                    if not m:
                        continue
                    rows.append(
                        LoonkostenRow(
                            name=m.group("name").strip(),
                            year=year or 0,
                            month=int(m.group("period")),
                            hours=_parse_nl_number(m.group("uren")),
                            hourly_rate_eur=_parse_nl_number(m.group("lkstn_uur")),
                            loon_kosten_eur=_parse_nl_number(m.group("loon_kosten")),
                        )
                    )
    except Exception as e:  # noqa: BLE001
        raise PayrollPdfError(f"Could not parse PDF: {e}") from e

    if year is None:
        raise PayrollPdfError(
            "Couldn't find an 'Overzicht Loonkosten' section with a 'Verloningsjaar' "
            "year in this PDF. Is this the right export from the payroll system?"
        )
    if not rows:
        raise PayrollPdfError(
            "Found an 'Overzicht Loonkosten' section but couldn't parse any rows from it. "
            "The column layout may differ from what this parser expects - "
            "please share this PDF so the parser can be adjusted."
        )
    return rows


def rows_to_preview_df(rows: list[LoonkostenRow]) -> pd.DataFrame:
    df = pd.DataFrame(
        [
            {
                "name": r.name,
                "month": r.month_str,
                "hours": r.hours,
                "hourly_rate_eur": r.hourly_rate_eur,
                "loon_kosten_eur": r.loon_kosten_eur,
            }
            for r in rows
        ]
    )
    return df.sort_values(["name", "month"]).reset_index(drop=True)
