"""
finanzamt.tax
~~~~~~~~~~~~~
Tax return computation modules.

Currently implemented:
  - ``ustva``  — Umsatzsteuer-Voranmeldung (VAT pre-return)

Planned:
  - ``eür``    — Einnahmen-Überschuss-Rechnung (EÜR / income-surplus statement)
  - ``anlage_n`` — Anlage N (employment income)
"""

from .ustva import USTVAReport, USTVALineItem, generate_ustva

__all__ = ["USTVAReport", "USTVALineItem", "generate_ustva"]
