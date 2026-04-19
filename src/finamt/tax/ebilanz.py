"""
finamt.tax.ebilanz
~~~~~~~~~~~~~~~~~~
E-Bilanz XBRL instance document builder for German annual accounts.

Supports:
  § 267a HGB  Kleinstkapitalgesellschaft  →  MicroBilG schema
  Taxonomy:   HGB-Taxonomie v6 (de-gaap-ci-2025-04-01 + de-gcd-2025-04-01)
              from german-gaap-taxonomy-v6/ bundled with finamt.

Pipeline overview:
  1.  Taxonomy XSD            →  shipped at german-gaap-taxonomy-v6/
  2.  XBRL instance builder   →  this module (lxml)
  3.  ERiC validation + send  →  finamt.tax.elster (ctypes bridge to ERiC shared lib)
  4.  Confirmation            →  Transferticket returned by Finanzamt

Namespace conventions (HGB XBRL v6):
  xbrli       http://www.xbrl.org/2003/instance
  de-gaap-ci  http://www.xbrl.de/taxonomies/de-gaap-ci-2025-04-01
  de-gcd      http://www.xbrl.de/taxonomies/de-gcd-2025-04-01
  iso4217     http://www.xbrl.org/2003/iso4217
  xsi         http://www.w3.org/2001/XMLSchema-instance

Key concept paths for Kleinstkapitalgesellschaft (MicroBilG):
  Balance sheet — Aktiva:
    de-gaap-ci:bs.ass                         total assets
    de-gaap-ci:bs.ass.fixAss                  fixed assets
    de-gaap-ci:bs.ass.currAss.cashEquiv       cash / Kassenbestand
    de-gaap-ci:bs.ass.notCalledUpCapital      ausstehende Einlagen (Bruttomethode)

  Balance sheet — Passiva (Eigenkapital):
    de-gaap-ci:bs.eqLiab                      total equity + liabilities
    de-gaap-ci:bs.eqLiab.equity               Eigenkapital
    de-gaap-ci:bs.eqLiab.equity.subscribed    Stammkapital
    de-gaap-ci:bs.eqLiab.equity.revenueReserves.other   Gewinnvortrag
    de-gaap-ci:bs.eqLiab.equity.netIncome     Jahresergebnis
    de-gaap-ci:bs.eqLiab.liabilities          Verbindlichkeiten (total)

  Income statement — MicroBilG (Gesamtkostenverfahren):
    de-gaap-ci:ismi.netIncome                 Jahresergebnis (GuV Summe)
    de-gaap-ci:ismi.netIncome.netSales        Umsatzerlöse
    de-gaap-ci:ismi.netIncome.otherOpRevenue  Sonstige betriebliche Erträge
    de-gaap-ci:ismi.netIncome.materialServices Materialaufwand (negativ!)
    de-gaap-ci:ismi.netIncome.staff           Personalaufwand (negativ!)
    de-gaap-ci:ismi.netIncome.deprAmort       Abschreibungen (negativ!)
    de-gaap-ci:ismi.netIncome.otherOpExpense  Sonstige betriebliche Aufwendungen (negativ!)

  GCD master data:
    de-gcd:genInfo.company.id.name            Firmenname
    de-gcd:genInfo.company.id.legalStatus     Rechtsform ("GmbH")
    de-gcd:genInfo.doc.period.fiscalYear.start  Beginn Wirtschaftsjahr
    de-gcd:genInfo.doc.period.fiscalYear.end    Ende Wirtschaftsjahr
    de-gcd:genInfo.report.id.statTaxID        Steuernummer

Usage::

    from finamt.tax.bilanz import generate_jahresabschluss
    from finamt.tax.ebilanz import build_xbrl, EBilanzConfig

    cfg = EBilanzConfig(
        steuernummer="21/815/08150",
        company_name="Muster GmbH",
        legal_form="GmbH",
        fiscal_year_start="2025-01-01",
        fiscal_year_end="2025-12-31",
    )
    jab = generate_jahresabschluss(receipts, year=2025, ...)
    xml_bytes = build_xbrl(jab, cfg)
    Path("ebilanz_2025.xbrl").write_bytes(xml_bytes)

    # then transmit via ERiC (finamt.tax.elster.ElsterClient.submit_ebilanz)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Optional

try:
    from lxml import etree as _ET
    _LXML_AVAILABLE = True
except ImportError:
    _LXML_AVAILABLE = False
    _ET = None  # type: ignore

from .bilanz import Jahresabschluss

# ---------------------------------------------------------------------------
# Namespace URIs
# ---------------------------------------------------------------------------

NS_XBRLI    = "http://www.xbrl.org/2003/instance"
NS_GAAP     = "http://www.xbrl.de/taxonomies/de-gaap-ci-2025-04-01"
NS_GCD      = "http://www.xbrl.de/taxonomies/de-gcd-2025-04-01"
NS_ISO4217  = "http://www.xbrl.org/2003/iso4217"
NS_XBRLDI   = "http://xbrl.org/2006/xbrldi"
NS_XSI      = "http://www.w3.org/2001/XMLSchema-instance"
NS_LINK     = "http://www.xbrl.org/2003/linkbase"
NS_XLINK    = "http://www.w3.org/1999/xlink"

NSMAP = {
    None:       NS_XBRLI,
    "xbrli":    NS_XBRLI,
    "de-gaap-ci": NS_GAAP,
    "de-gcd":   NS_GCD,
    "iso4217":  NS_ISO4217,
    "xbrldi":   NS_XBRLDI,
    "xsi":      NS_XSI,
    "link":     NS_LINK,
    "xlink":    NS_XLINK,
}

# Schema location for MicroBilG (§ 267a HGB Kleinstkapitalgesellschaft)
# Relative to the transmitted document; ERiC resolves it from the installed taxonomy.
SCHEMA_LOCATION = (
    f"{NS_GAAP} de-gaap-ci-2025-04-01-shell-fiscal-microbilg.xsd "
    f"{NS_GCD} de-gcd-2025-04-01-shell.xsd"
)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class EBilanzConfig:
    """
    Company master data required for an E-Bilanz submission.

    All fields map directly to the GCD module of the HGB XBRL taxonomy.
    """
    steuernummer:       str               # e.g. "21/815/08150" — from Finanzamt notice
    company_name:       str               # registered company name
    legal_form:         str = "GmbH"      # "GmbH" | "UG (haftungsbeschränkt)" | ...
    fiscal_year_start:  str = ""          # ISO date "YYYY-MM-DD"
    fiscal_year_end:    str = ""          # ISO date "YYYY-MM-DD"
    # Optional: filing metadata
    preparer:           str = ""          # name of the person preparing the filing
    comment:            str = ""          # free-text comment embedded in the instance


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _eur(value: Decimal) -> str:
    """Format a Decimal as a plain decimal string with exactly 2 fractional digits."""
    return f"{value:.2f}"


def _tag(ns: str, local: str) -> str:
    return f"{{{ns}}}{local}"


def _sub(parent, ns: str, local: str, text: str | None = None, **attribs) -> "_ET.Element":
    el = _ET.SubElement(parent, _tag(ns, local), **attribs)
    if text is not None:
        el.text = text
    return el


def _fact(
    root,
    ns: str,
    concept: str,
    value: Decimal,
    context_ref: str,
    unit_ref: str = "EUR",
    decimals: str = "2",
) -> "_ET.Element":
    """Append a numeric XBRL fact to *root*."""
    el = _ET.SubElement(root, _tag(ns, concept))
    el.set("contextRef", context_ref)
    el.set("unitRef", unit_ref)
    el.set("decimals", decimals)
    el.text = _eur(value)
    return el


def _str_fact(
    root,
    ns: str,
    concept: str,
    value: str,
    context_ref: str,
) -> "_ET.Element":
    """Append a string XBRL fact (no unitRef / decimals)."""
    el = _ET.SubElement(root, _tag(ns, concept))
    el.set("contextRef", context_ref)
    el.text = value
    return el


# ---------------------------------------------------------------------------
# Context / unit builders
# ---------------------------------------------------------------------------

def _add_context(root, ctx_id: str, start: str, end: str, steuernummer: str) -> None:
    """
    Add a duration context (Berichtszeitraum) to the XBRL instance.

    The entity identifier scheme follows the ELSTER convention:
      http://www.rzf.fin-nrw.de/  — used for Steuernummer-based identification.
    """
    ctx = _ET.SubElement(root, _tag(NS_XBRLI, "context"), id=ctx_id)
    entity = _ET.SubElement(ctx, _tag(NS_XBRLI, "entity"))
    ident  = _ET.SubElement(
        entity, _tag(NS_XBRLI, "identifier"),
        scheme="http://www.rzf.fin-nrw.de/",
    )
    ident.text = steuernummer
    period = _ET.SubElement(ctx, _tag(NS_XBRLI, "period"))
    _ET.SubElement(period, _tag(NS_XBRLI, "startDate")).text = start
    _ET.SubElement(period, _tag(NS_XBRLI, "endDate")).text   = end


def _add_instant_context(root, ctx_id: str, instant: str, steuernummer: str) -> None:
    """Add a point-in-time context (balance sheet date) to the XBRL instance."""
    ctx = _ET.SubElement(root, _tag(NS_XBRLI, "context"), id=ctx_id)
    entity = _ET.SubElement(ctx, _tag(NS_XBRLI, "entity"))
    ident  = _ET.SubElement(
        entity, _tag(NS_XBRLI, "identifier"),
        scheme="http://www.rzf.fin-nrw.de/",
    )
    ident.text = steuernummer
    period = _ET.SubElement(ctx, _tag(NS_XBRLI, "period"))
    _ET.SubElement(period, _tag(NS_XBRLI, "instant")).text = instant


def _add_unit_eur(root) -> None:
    unit = _ET.SubElement(root, _tag(NS_XBRLI, "unit"), id="EUR")
    _ET.SubElement(unit, _tag(NS_XBRLI, "measure")).text = "iso4217:EUR"


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

def build_xbrl(jab: Jahresabschluss, cfg: EBilanzConfig) -> bytes:
    """
    Build a valid HGB XBRL instance document for a Kleinstkapitalgesellschaft
    (§ 267a HGB, MicroBilG) from a *Jahresabschluss* object.

    Returns
    -------
    bytes
        UTF-8 encoded XML with XML declaration.  Write to a .xbrl file and
        pass to ERiC for validation + transmission (see finamt.tax.elster).

    Raises
    ------
    ImportError
        If lxml is not installed.
    ValueError
        If mandatory config fields are missing.
    """
    if not _LXML_AVAILABLE:
        raise ImportError(
            "lxml is required for E-Bilanz generation.  "
            "Install it with: pip install lxml"
        )

    b = jab.bilanz
    g = jab.guv
    year = b.year

    # Derive dates from config or fall back to calendar year
    fy_start = cfg.fiscal_year_start or f"{year}-01-01"
    fy_end   = cfg.fiscal_year_end   or f"{year}-12-31"

    # Context IDs
    CTX_DURATION = f"D-{year}"          # GuV (from / to)
    CTX_END      = f"I-{year}-12-31"    # Bilanz (instant = balance sheet date)
    CTX_GCD      = f"GCD-{year}"        # GCD master data (same duration)

    # ----------------------------------------------------------------
    # Root element
    # ----------------------------------------------------------------
    root = _ET.Element(_tag(NS_XBRLI, "xbrl"), nsmap=NSMAP)
    root.set(
        _tag(NS_XSI, "schemaLocation"),
        SCHEMA_LOCATION,
    )

    # ----------------------------------------------------------------
    # Schema reference (link to MicroBilG shell)
    # ----------------------------------------------------------------
    lr = _ET.SubElement(root, _tag(NS_LINK, "linkbaseRef"))
    lr.set(_tag(NS_XLINK, "type"), "simple")
    lr.set(
        _tag(NS_XLINK, "href"),
        "de-gaap-ci-2025-04-01-shell-fiscal-microbilg.xsd",
    )

    # ----------------------------------------------------------------
    # Contexts
    # ----------------------------------------------------------------
    _add_context(root, CTX_DURATION, fy_start, fy_end, cfg.steuernummer)
    _add_instant_context(root, CTX_END, fy_end, cfg.steuernummer)
    _add_context(root, CTX_GCD, fy_start, fy_end, cfg.steuernummer)

    # ----------------------------------------------------------------
    # Unit
    # ----------------------------------------------------------------
    _add_unit_eur(root)

    # ----------------------------------------------------------------
    # GCD module — company master data
    # ----------------------------------------------------------------
    _str_fact(root, NS_GCD, "genInfo.company.id.name",        cfg.company_name,   CTX_GCD)
    _str_fact(root, NS_GCD, "genInfo.company.id.legalStatus", cfg.legal_form,      CTX_GCD)
    _str_fact(root, NS_GCD, "genInfo.report.id.statTaxID",    cfg.steuernummer,    CTX_GCD)
    _str_fact(root, NS_GCD, "genInfo.doc.period.fiscalYear.start", fy_start,       CTX_GCD)
    _str_fact(root, NS_GCD, "genInfo.doc.period.fiscalYear.end",   fy_end,         CTX_GCD)
    if cfg.preparer:
        _str_fact(root, NS_GCD, "genInfo.report.id.preparer", cfg.preparer, CTX_GCD)
    if cfg.comment:
        _str_fact(root, NS_GCD, "genInfo.report.id.comment",  cfg.comment,  CTX_GCD)

    # ----------------------------------------------------------------
    # GAAP module — Bilanz (Aktiva) — instant context
    # ----------------------------------------------------------------
    # Total assets
    _fact(root, NS_GAAP, "bs.ass", b.summe_aktiva, CTX_END)

    # A. Anlagevermögen
    if b.anlagevermögen:
        _fact(root, NS_GAAP, "bs.ass.fixAss", b.anlagevermögen, CTX_END)

    # B. Umlaufvermögen — Kassenbestand / Bankguthaben
    # For a Kleinstkapitalgesellschaft with no inventory / receivables tracked,
    # we report the full current assets as cash equivalent.
    ca = b.kassenbestand + b.vorräte + b.forderungen
    _fact(root, NS_GAAP, "bs.ass.currAss",          ca,              CTX_END)
    _fact(root, NS_GAAP, "bs.ass.currAss.cashEquiv", b.kassenbestand, CTX_END)

    # C. Ausstehende Einlagen (Bruttomethode only — if nettomethode=True this is 0)
    if b.ausstehende_einlagen:
        _fact(root, NS_GAAP, "bs.ass.notCalledUpCapital", b.ausstehende_einlagen, CTX_END)

    # ----------------------------------------------------------------
    # GAAP module — Bilanz (Passiva / Eigenkapital) — instant context
    # ----------------------------------------------------------------
    _fact(root, NS_GAAP, "bs.eqLiab",          b.summe_passiva,    CTX_END)
    _fact(root, NS_GAAP, "bs.eqLiab.equity",   b.summe_eigenkapital, CTX_END)

    # I.  Gezeichnetes Kapital (Stammkapital)
    _fact(root, NS_GAAP, "bs.eqLiab.equity.subscribed", b.stammkapital, CTX_END)

    # Nicht eingeforderte ausstehende Einlagen (Nettomethode deduction)
    if b.nicht_eingeforderte_einlagen:
        # Convention: reported as a *positive* value — the calculation linkbase
        # has weight="-1" for unpaidCap, so it is deducted automatically.
        _fact(
            root, NS_GAAP,
            "bs.eqLiab.equity.subscribed.unpaidCap",
            b.nicht_eingeforderte_einlagen,
            CTX_END,
        )

    # II. Kapitalrücklage
    if b.kapitalrücklage:
        _fact(root, NS_GAAP, "bs.eqLiab.equity.capitalReserve", b.kapitalrücklage, CTX_END)

    # III. Gewinn-/Verlustvortrag
    if b.gewinnvortrag:
        _fact(
            root, NS_GAAP,
            "bs.eqLiab.equity.profitLoss",
            b.gewinnvortrag,
            CTX_END,
        )

    # IV. Jahresergebnis
    _fact(root, NS_GAAP, "bs.eqLiab.equity.netIncome", b.jahresergebnis, CTX_END)

    # B. Rückstellungen
    if b.rückstellungen:
        _fact(root, NS_GAAP, "bs.eqLiab.provisions", b.rückstellungen, CTX_END)

    # C. Verbindlichkeiten
    if b.verbindlichkeiten:
        _fact(root, NS_GAAP, "bs.eqLiab.liabilities", b.verbindlichkeiten, CTX_END)

    # ----------------------------------------------------------------
    # GAAP module — GuV / Income Statement (MicroBilG, duration context)
    # ----------------------------------------------------------------
    # Net income (Jahresergebnis)
    _fact(root, NS_GAAP, "ismi.netIncome", g.jahresergebnis, CTX_DURATION)

    # Revenue lines
    _fact(root, NS_GAAP, "ismi.netIncome.netSales",      g.umsatzerlöse,            CTX_DURATION)
    _fact(root, NS_GAAP, "ismi.netIncome.otherOpRevenue", g.sonstige_betriebserlöse, CTX_DURATION)

    # Expense lines — XBRL convention for MicroBilG: reported as *positive* values.
    # The calculation linkbase has weight="-1" for each expense concept, so validators
    # subtract them from net income automatically.  Storing negative values here would
    # cause a double-negation and fail calculation validation.
    if g.materialaufwand:
        _fact(root, NS_GAAP, "ismi.netIncome.materialServices", g.materialaufwand,          CTX_DURATION)
    if g.personalaufwand:
        _fact(root, NS_GAAP, "ismi.netIncome.staff",             g.personalaufwand,          CTX_DURATION)
    if g.abschreibungen:
        _fact(root, NS_GAAP, "ismi.netIncome.deprAmort",         g.abschreibungen,           CTX_DURATION)
    if g.sonstige_betriebsausgaben:
        _fact(root, NS_GAAP, "ismi.netIncome.otherCost",         g.sonstige_betriebsausgaben, CTX_DURATION)
    if g.zinsaufwendungen:
        _fact(root, NS_GAAP, "ismi.netIncome.interestExpense",   g.zinsaufwendungen,         CTX_DURATION)

    # ----------------------------------------------------------------
    # Serialise
    # ----------------------------------------------------------------
    tree = _ET.ElementTree(root)
    return _ET.tostring(
        root,
        pretty_print=True,
        xml_declaration=True,
        encoding="UTF-8",
    )


# ---------------------------------------------------------------------------
# Convenience: write to file
# ---------------------------------------------------------------------------

def write_xbrl(
    jab: Jahresabschluss,
    cfg: EBilanzConfig,
    path: str | Path,
) -> Path:
    """Build the XBRL instance and write it to *path*.  Returns the resolved path."""
    out = Path(path)
    out.write_bytes(build_xbrl(jab, cfg))
    return out
