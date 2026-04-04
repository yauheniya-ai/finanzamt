"""
finamt.tax.bilanz
~~~~~~~~~~~~~~~~~
Simplified Jahresabschluss (Bilanz + GuV) for GmbH / UG.

⚠  IMPORTANT LIMITATION:
   A real Jahresabschluss requires double-entry bookkeeping (doppelte Buchführung)
   with a full chart of accounts (Kontenrahmen SKR03 / SKR04).
   This module derives *approximated* figures directly from receipt data —
   it does NOT replace a proper accounting system.

   For Kleinstkapitalgesellschaften (§ 267a HGB) — the typical early-stage GmbH —
   this simplified output is usually sufficient for:
     - Internal management reporting
     - Preparation of the Bundesanzeiger filing
     - Briefing a tax advisor

   For full E-Bilanz submission (mandatory for GmbH via ELSTER), the figures
   produced here must be mapped to the HGB taxonomy before transmission.

   There is no statutory obligation to involve a Steuerberater for a
   Kleinstkapitalgesellschaft (§ 267a HGB).  The Geschäftsführer may prepare and
   submit the annual accounts, E-Bilanz (ELSTER) and Bundesanzeiger filing directly,
   provided they meet the factual requirements.  An ELSTER organisation certificate
   for the GmbH is required for electronic submission.

Legal basis:
  - §§ 242–256a HGB (Bilanz + GuV)
  - § 267a HGB (Kleinstkapitalgesellschaft — simplified presentation)
  - ELSTER E-Bilanz: Taxonomie-Version from www.esteuer.de

GmbH-specific minimum equity structure (at incorporation):
  Stammkapital (gezeichnetes Kapital): 25,000 EUR minimum
  Of which, at least 50% (12,500 EUR) must be paid in at registration.
  The unpaid portion appears as "Ausstehende Einlagen" on the assets side (§ 272 Abs. 1 HGB).

Usage::

    from finamt.storage import get_repository
    from finamt.tax.bilanz import generate_jahresabschluss

    with get_repository() as repo:
        receipts = repo.find_by_period(date(2024, 1, 1), date(2024, 12, 31))

    jab = generate_jahresabschluss(
        receipts,
        year=2024,
        stammkapital=Decimal("25000"),
        eingezahltes_kapital=Decimal("12500"),
        vortrag_gewinnverlust=Decimal("0"),   # from prior year
    )
    print(jab.summary())
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Iterable

from ..models import ReceiptData

_TWO = Decimal("0.01")
_ZERO = Decimal("0")


def _r(d: Decimal) -> Decimal:
    return d.quantize(_TWO, rounding=ROUND_HALF_UP)


def _to_date(dt: date | datetime) -> date:
    return dt.date() if isinstance(dt, datetime) else dt


# ---------------------------------------------------------------------------
# Bilanz
# ---------------------------------------------------------------------------

@dataclass
class Bilanz:
    """
    Vereinfachte Bilanz (§ 266 HGB, vereinfacht nach § 267a HGB).

    Aktiva (Assets):
      A. Anlagevermögen          — long-lived assets (equipment, software licences > 1y)
      B. Umlaufvermögen
         I.   Vorräte            — inventory / materials
         II.  Forderungen        — outstanding receivables (not tracked from receipts alone)
         III. Kassenbestand      — approximated as: paid-in capital + revenue − expenses
      C. Ausstehende Einlagen    — unpaid portion of Stammkapital (§ 272 Abs. 1 HGB)
      D. Aktive RAP              — prepayments (not derived here)

    Passiva (Liabilities + Equity):
      A. Eigenkapital
         I.  Gezeichnetes Kapital (Stammkapital)
         II. Kapitalrücklage
         III. Jahresüberschuss / -fehlbetrag
         IV. Gewinnvortrag / Verlustvortrag
      B. Rückstellungen          — provisions (not derived from receipts)
      C. Verbindlichkeiten       — outstanding liabilities (approx. from unpaid purchases)
    """

    year: int

    # --- Aktiva ---
    anlagevermögen:         Decimal = _ZERO   # Konto 0xxx (SKR04)
    vorräte:                Decimal = _ZERO   # Konto 1xxx
    forderungen:            Decimal = _ZERO   # Konto 1200 (not auto-derived)
    kassenbestand:          Decimal = _ZERO   # Konto 1600/1800
    ausstehende_einlagen:   Decimal = _ZERO   # Konto 0200 (§ 272 I HGB)
    aktive_rap:             Decimal = _ZERO   # Konto 0980

    # --- Passiva ---
    stammkapital:               Decimal = _ZERO   # Konto 2900
    kapitalrücklage:            Decimal = _ZERO   # Konto 2910
    jahresergebnis:             Decimal = _ZERO   # computed
    gewinnvortrag:              Decimal = _ZERO   # from prior year
    # § 272 Abs. 1 S. 2 HGB — Nettomethode: non-called-up outstanding contributions
    # deducted from equity on the Passiva side (leaves Aktiva = Kassenbestand only).
    # With Bruttomethode (nettomethode=False) this stays _ZERO; instead
    # ausstehende_einlagen appears on the Aktiva side.
    nicht_eingeforderte_einlagen: Decimal = _ZERO  # Konto 2901 deduction
    rückstellungen:             Decimal = _ZERO   # not auto-derived
    verbindlichkeiten:          Decimal = _ZERO   # approx. from outstanding purchases

    @property
    def summe_aktiva(self) -> Decimal:
        return _r(
            self.anlagevermögen
            + self.vorräte
            + self.forderungen
            + self.kassenbestand
            + self.ausstehende_einlagen
            + self.aktive_rap
        )

    @property
    def summe_eigenkapital(self) -> Decimal:
        return _r(
            self.stammkapital
            - self.nicht_eingeforderte_einlagen   # § 272 I S.2 HGB deduction
            + self.kapitalrücklage
            + self.jahresergebnis
            + self.gewinnvortrag
        )

    @property
    def summe_passiva(self) -> Decimal:
        return _r(
            self.summe_eigenkapital
            + self.rückstellungen
            + self.verbindlichkeiten
        )

    @property
    def bilanz_ausgeglichen(self) -> bool:
        return self.summe_aktiva == self.summe_passiva

    def to_dict(self) -> dict:
        return {
            "year":                  self.year,
            "aktiva": {
                "anlagevermögen":        str(self.anlagevermögen),
                "vorräte":               str(self.vorräte),
                "forderungen":           str(self.forderungen),
                "kassenbestand":         str(self.kassenbestand),
                "ausstehende_einlagen":  str(self.ausstehende_einlagen),
                "aktive_rap":            str(self.aktive_rap),
                "summe_aktiva":          str(self.summe_aktiva),
            },
            "passiva": {
                "stammkapital":                  str(self.stammkapital),
                "kapitalrücklage":               str(self.kapitalrücklage),
                "nicht_eingeforderte_einlagen":  str(self.nicht_eingeforderte_einlagen),
                "jahresergebnis":                str(self.jahresergebnis),
                "gewinnvortrag":                 str(self.gewinnvortrag),
                "summe_eigenkapital":            str(self.summe_eigenkapital),
                "rückstellungen":                str(self.rückstellungen),
                "verbindlichkeiten":             str(self.verbindlichkeiten),
                "summe_passiva":                 str(self.summe_passiva),
            },
            "bilanz_ausgeglichen": self.bilanz_ausgeglichen,
        }


# ---------------------------------------------------------------------------
# Gewinn- und Verlustrechnung (GuV)
# ---------------------------------------------------------------------------

@dataclass
class GuV:
    """
    Vereinfachte GuV nach § 275 Abs. 2 HGB (Gesamtkostenverfahren).

    Only positions derivable from receipt data are populated automatically.
    A complete GuV would also include depreciation schedules, accruals, etc.
    """

    year: int

    # Erträge (revenue)
    umsatzerlöse:               Decimal = _ZERO   # Kz: sale invoices, net
    sonstige_betriebserlöse:    Decimal = _ZERO   # other income not in sales

    # Aufwendungen (expenses)
    materialaufwand:            Decimal = _ZERO   # material + equipment purchases
    personalaufwand:            Decimal = _ZERO   # salaries (not in receipts)
    abschreibungen:             Decimal = _ZERO   # not auto-derived (requires AfA table)
    sonstige_betriebsausgaben:  Decimal = _ZERO   # all other expense categories
    zinsaufwendungen:           Decimal = _ZERO   # interest (not in receipts)

    @property
    def gesamtleistung(self) -> Decimal:
        return _r(self.umsatzerlöse + self.sonstige_betriebserlöse)

    @property
    def gesamtaufwand(self) -> Decimal:
        return _r(
            self.materialaufwand
            + self.personalaufwand
            + self.abschreibungen
            + self.sonstige_betriebsausgaben
            + self.zinsaufwendungen
        )

    @property
    def jahresergebnis(self) -> Decimal:
        """Jahresüberschuss (> 0) or Jahresfehlbetrag (< 0)."""
        return _r(self.gesamtleistung - self.gesamtaufwand)

    def to_dict(self) -> dict:
        return {
            "year":                     self.year,
            "umsatzerlöse":             str(self.umsatzerlöse),
            "sonstige_betriebserlöse":  str(self.sonstige_betriebserlöse),
            "gesamtleistung":           str(self.gesamtleistung),
            "materialaufwand":          str(self.materialaufwand),
            "personalaufwand":          str(self.personalaufwand),
            "abschreibungen":           str(self.abschreibungen),
            "sonstige_betriebsausgaben": str(self.sonstige_betriebsausgaben),
            "zinsaufwendungen":         str(self.zinsaufwendungen),
            "gesamtaufwand":            str(self.gesamtaufwand),
            "jahresergebnis":           str(self.jahresergebnis),
        }


# ---------------------------------------------------------------------------
# Jahresabschluss
# ---------------------------------------------------------------------------

@dataclass
class Jahresabschluss:
    """Combined Bilanz + GuV for one fiscal year."""

    bilanz:         Bilanz
    guv:            GuV
    skipped_count:  int = 0

    def to_dict(self) -> dict:
        return {
            "bilanz":        self.bilanz.to_dict(),
            "guv":           self.guv.to_dict(),
            "skipped_count": self.skipped_count,
        }

    def to_json(self, path: str | Path | None = None) -> str:
        raw = json.dumps(self.to_dict(), indent=2, ensure_ascii=False)
        if path:
            Path(path).write_text(raw, encoding="utf-8")
        return raw

    def summary(self) -> str:
        W = 64
        b = self.bilanz
        g = self.guv

        def row(label: str, amount: Decimal, indent: int = 2) -> str:
            return f"{'  ' * indent}{label:<44} {amount:>10.2f} EUR"

        lines = [
            "=" * W,
            f"  JAHRESABSCHLUSS {b.year}  (vereinfacht, § 267a HGB)",
            "=" * W,
            "",
            "  ── GEWINN- UND VERLUSTRECHNUNG ──────────────────────",
            row("Umsatzerlöse",                    g.umsatzerlöse),
            row("Sonstige Betriebserlöse",         g.sonstige_betriebserlöse),
            row("= Gesamtleistung",                g.gesamtleistung),
            row("- Materialaufwand",               g.materialaufwand),
            row("- Personalaufwand",               g.personalaufwand),
            row("- Abschreibungen",                g.abschreibungen),
            row("- Sonstige Betriebsausgaben",     g.sonstige_betriebsausgaben),
            row("- Zinsaufwendungen",              g.zinsaufwendungen),
            "  " + "─" * (W - 2),
            row("= JAHRESERGEBNIS", g.jahresergebnis),
            "",
            "  ── BILANZ (AKTIVA) ──────────────────────────────────",
            row("A. Anlagevermögen",               b.anlagevermögen),
            row("B. Umlaufvermögen", _ZERO),
            row("   I.   Vorräte",                 b.vorräte, indent=3),
            row("   II.  Forderungen",             b.forderungen, indent=3),
            row("   III. Kassenbestand (approx.)", b.kassenbestand, indent=3),
            row("C. Ausstehende Einlagen",         b.ausstehende_einlagen),
            "  " + "─" * (W - 2),
            row("SUMME AKTIVA",                    b.summe_aktiva),
            "",
            "  ── BILANZ (PASSIVA) ─────────────────────────────────",
            row("A. Eigenkapital", _ZERO),
            row("   I.  Gezeichnetes Kapital",             b.stammkapital, indent=3),
        ] + ([row("   ./. nicht eingeforderte Einlagen",   -b.nicht_eingeforderte_einlagen, indent=3)]
              if b.nicht_eingeforderte_einlagen else []) + [
            row("   II. Kapitalrücklage",                  b.kapitalrücklage, indent=3),
            row("   III.Jahresergebnis",                   b.jahresergebnis, indent=3),
            row("   IV. Gewinn-/Verlustvortrag",           b.gewinnvortrag, indent=3),
            row("   = Summe Eigenkapital",                 b.summe_eigenkapital, indent=3),
            row("B. Rückstellungen",               b.rückstellungen),
            row("C. Verbindlichkeiten",            b.verbindlichkeiten),
            "  " + "─" * (W - 2),
            row("SUMME PASSIVA",                   b.summe_passiva),
            "",
        ]
        if b.bilanz_ausgeglichen:
            lines.append("  ✓  Bilanz ausgeglichen")
        else:
            diff = _r(b.summe_aktiva - b.summe_passiva)
            lines.append(f"  ✗  Differenz Aktiva − Passiva: {diff:.2f} EUR")
            lines.append("     → manuelle Buchungen oder Rückstellungen erforderlich")
        lines += [
            "",
            "  ℹ  Kleinstkapitalgesellschaft (§ 267a HGB): Es besteht keine gesetzliche Pflicht,",
            "     einen Steuerberater einzuschalten. E-Bilanz (ELSTER), Jahresabschluss und",
            "     Bundesanzeiger-Einreichung können von der Geschäftsführung selbst erledigt",
            "     werden. Voraussetzung: fachliche Kenntnisse und ein ELSTER-Zertifikat.",
            "=" * W,
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------

_MATERIAL_CATS  = {"material", "equipment"}
_INCOME_CATS    = {"services", "consulting", "products", "licensing"}


def generate_jahresabschluss(
    receipts: Iterable[ReceiptData],
    year: int,
    stammkapital: Decimal,
    eingezahltes_kapital: Decimal,
    vortrag_gewinnverlust: Decimal = _ZERO,
    rückstellungen: Decimal = _ZERO,
    nettomethode: bool = True,
    kassen_eröffnungsbestand: Decimal | None = None,
) -> Jahresabschluss:
    """
    Derive an approximate Jahresabschluss from receipt data.

    Parameters
    ----------
    receipts:
        All receipts for the fiscal year.
    year:
        Fiscal year (calendar year).
    stammkapital:
        Registered share capital (e.g. Decimal("25000") for a standard GmbH).
    eingezahltes_kapital:
        Amount actually paid in at balance-sheet date (≥ 50% of Stammkapital).
        For Gründungsjahr: the initial payment (e.g. Decimal("12500")).
    vortrag_gewinnverlust:
        Cumulative profit/loss carried forward from prior years (equity only —
        NOT added to the cash calculation).
    rückstellungen:
        Manually entered provisions (e.g. tax provisions) — not derivable from receipts.
    nettomethode:
        If True (default): apply § 272 Abs. 1 S. 2 HGB — non-called-up outstanding
        contributions are deducted from equity on the Passiva side.  The Aktiva side
        shows only the actual cash balance → Bilanzsumme equals eingezahltes Kapital.
        If False (Bruttomethode): outstanding contributions appear as an asset on the
        Aktiva side and the full Stammkapital is shown on the Passiva side.
    kassen_eröffnungsbestand:
        Opening cash balance at the start of the year.  Leave as None for the
        Gründungsjahr (year 1) — the function then uses *eingezahltes_kapital* as the
        opening cash.  For subsequent years, pass the prior year's closing cash so the
        calculation does not double-count the initial capital injection.

    Returns
    -------
    Jahresabschluss
    """
    guv   = GuV(year=year)
    skipped = 0

    period_start = date(year, 1, 1)
    period_end   = date(year, 12, 31)

    for r in receipts:
        if r.receipt_date is None:
            skipped += 1
            continue
        d = _to_date(r.receipt_date)
        if not (period_start <= d <= period_end):
            skipped += 1
            continue
        if not r.net_amount:
            skipped += 1
            continue

        cat = str(r.category) if r.category else "other"
        net = _r(r.business_net if r.business_net is not None else r.net_amount)

        if r.is_purchase:
            if cat in _MATERIAL_CATS:
                guv.materialaufwand        += net
            else:
                guv.sonstige_betriebsausgaben += net
        else:
            if cat in _INCOME_CATS:
                guv.umsatzerlöse           += net
            else:
                guv.sonstige_betriebserlöse += net

    # Final rounding
    for attr in (
        "umsatzerlöse", "sonstige_betriebserlöse",
        "materialaufwand", "sonstige_betriebsausgaben",
    ):
        setattr(guv, attr, _r(getattr(guv, attr)))

    # -------------------------------------------------------------------
    # Derive Bilanz
    # -------------------------------------------------------------------
    ausstehende = _r(stammkapital - eingezahltes_kapital)

    # Opening cash:
    #   • Gründungsjahr (kassen_eröffnungsbestand is None): the paid-in capital IS
    #     the opening cash (the Gesellschafter wired the money at incorporation).
    #   • Subsequent years: caller supplies the prior year's closing cash; the initial
    #     Einlage is already embedded in that figure and must NOT be added again.
    opening = eingezahltes_kapital if kassen_eröffnungsbestand is None else kassen_eröffnungsbestand

    # Cash approximation (cash-basis):
    #   opening + revenues received − expenses paid
    # Note: vortrag_gewinnverlust is an equity position, not a cash movement — it
    # must NOT be added to the cash balance here.
    kassenbestand = _r(
        opening
        + guv.umsatzerlöse
        + guv.sonstige_betriebserlöse
        - guv.materialaufwand
        - guv.sonstige_betriebsausgaben
    )

    # § 272 Abs. 1 HGB — outstanding contributions (Ausstehende Einlagen):
    #   Nettomethode (default, § 272 I S. 2):  deducted from equity on Passiva.
    #   Bruttomethode              (§ 272 I S. 1):  shown as asset on Aktiva.
    aktiva_ausstehend  = _ZERO     if nettomethode else ausstehende
    nicht_eingefordert = ausstehende if nettomethode else _ZERO

    bilanz = Bilanz(
        year=year,
        kassenbestand                = max(kassenbestand, _ZERO),
        ausstehende_einlagen         = aktiva_ausstehend,
        stammkapital                 = stammkapital,
        nicht_eingeforderte_einlagen = nicht_eingefordert,
        jahresergebnis               = guv.jahresergebnis,
        gewinnvortrag                = vortrag_gewinnverlust,
        rückstellungen               = rückstellungen,
    )

    return Jahresabschluss(bilanz=bilanz, guv=guv, skipped_count=skipped)