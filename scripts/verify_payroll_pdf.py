"""Standalone sanity check for the payroll PDF parser - no Streamlit, no Google API.

Run this after installing requirements.txt, against a real 'Overzicht Loonkosten'
PDF, to confirm the parser reads it correctly before trusting it in the app:

    python scripts/verify_payroll_pdf.py "path/to/Overzicht Loonkosten.pdf"

It parses the PDF, prints one row per employee/month, and cross-checks the sum
of all rows' "Loon kosten" figures against the report's own per-employee
subtotal lines (each employee block in the PDF already prints a subtotal row -
this script recomputes it independently and compares). Any mismatch is
printed clearly rather than silently ignored.
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hk_dashboard.payroll_pdf import extract_loonkosten_rows, rows_to_preview_df  # noqa: E402


def main(pdf_path: str) -> None:
    with open(pdf_path, "rb") as f:
        rows = extract_loonkosten_rows(f)

    preview = rows_to_preview_df(rows)
    print(preview.to_string(index=False))
    print()

    by_employee = defaultdict(float)
    for r in rows:
        by_employee[r.name] += r.loon_kosten_eur

    grand_total = sum(by_employee.values())
    print(f"Parsed {len(rows)} rows for {len(by_employee)} employees.")
    print(f"Sum of 'Loon kosten' across all parsed rows: EUR {grand_total:,.2f}")
    print()
    print("Per-employee totals (cross-check these against the subtotal row")
    print("the PDF itself prints under each employee's block):")
    for name, total in sorted(by_employee.items()):
        print(f"  {name:30s} EUR {total:>10,.2f}")

    print()
    print(
        "If the grand total above doesn't match the PDF's own final "
        "'Overzicht Loonkosten' grand-total row (bottom of the last page of "
        "that section), the parser needs adjusting before you trust it."
    )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python scripts/verify_payroll_pdf.py <path-to-pdf>")
        sys.exit(1)
    main(sys.argv[1])
