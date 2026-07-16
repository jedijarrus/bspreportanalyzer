"""Liest XRechnung/UBL-Rechnungen (XML) in normalisierte Positionen.

Kernpunkte (siehe Spec / Echtdaten-Analyse):
- Nur Ladungen tragen Rufnummer/Kostenstelle; Rabatte und Info-Zeilen nicht.
  Daher **Carry-Forward** in Dokumentreihenfolge: eine Zeile ohne Rufnummer erbt
  die zuletzt gesehene (rufnummer, kostenstelle, kostenstellennutzer).
- Kategorisierung der Leistungsart: grundpreis / option / rabatt / verbrauch / info.
- Datenvolumen (vereinbart/verbraucht) wird nach GB normiert.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_KK_RE = re.compile(r"_Rechnung_(\d+)_")


@dataclass
class InvoiceData:
    filename: str
    invoice_number: str | None
    kundenkonto: str | None
    issue_date: str | None
    due_date: str | None
    period_start: str | None
    period_end: str | None
    total_net: float
    total_tax: float
    total_gross: float
    lines: list[dict[str, Any]] = field(default_factory=list)


def _ln(tag: str) -> str:
    return tag.split("}")[-1]


def _classify(item_name: str, amount: float) -> str:
    name = (item_name or "").lower()
    if amount == 0:
        return "info"
    if amount < 0 or "auf grundpreis" in name:
        return "rabatt"
    if "verbindung" in name or "versand" in name:
        return "verbrauch"
    if name.startswith("business mobil") or name.startswith("businessflex") or name.startswith("flat s"):
        return "grundpreis"
    return "option"


# UN/ECE-Einheitencodes (Rec. 20) und Klartext -> Faktor auf GB
_UNIT_TO_GB = {
    "2P": 1 / 1024 / 1024, "KB": 1 / 1024 / 1024,   # Kilobyte
    "4L": 1 / 1024, "MB": 1 / 1024,                  # Megabyte
    "E34": 1.0, "GB": 1.0,                           # Gigabyte
    "E35": 1024.0, "TB": 1024.0,                     # Terabyte
    "AD": 1 / 1024 / 1024 / 1024, "BYTE": 1 / 1024 / 1024 / 1024,
}


def _to_gb(value: Any, unit: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        x = float(str(value).replace(",", "."))
    except ValueError:
        return None
    factor = _UNIT_TO_GB.get((unit or "").strip().upper())
    return x * factor if factor is not None else x  # unbekannt -> unverändert


def _first_child_text(elem, local: str) -> str | None:
    for c in elem:
        if _ln(c.tag) == local:
            return c.text
    return None


def _line_props(line) -> dict[str, str]:
    props: dict[str, str] = {}
    for p in line.iter():
        if _ln(p.tag) == "AdditionalItemProperty":
            nm = val = None
            for c in p:
                if _ln(c.tag) == "Name":
                    nm = c.text
                elif _ln(c.tag) == "Value":
                    val = c.text
            if nm is not None:
                props[nm] = val
    return props


def parse_invoice(path: str | Path) -> InvoiceData:
    path = Path(path)
    root = ET.parse(path).getroot()

    # Kopf
    header = {}
    for c in root:
        header[_ln(c.tag)] = c.text
    total_net = total_tax = total_gross = 0.0
    for e in root.iter():
        if _ln(e.tag) == "LegalMonetaryTotal":
            total_net = float(_first_child_text(e, "LineExtensionAmount") or 0)
            total_gross = float(_first_child_text(e, "TaxInclusiveAmount") or 0)
        elif _ln(e.tag) == "TaxTotal":
            v = _first_child_text(e, "TaxAmount")
            if v is not None:
                total_tax = float(v)

    m = _KK_RE.search(path.name)
    kundenkonto = m.group(1) if m else None

    # Erste Runde: Zeilen einsammeln + docref-Kontext bilden. Nur Ladungen tragen
    # Rufnummer/Kostenstelle; Rabatte/Info nicht — aber alle Zeilen eines Blocks
    # teilen die DocumentReference/ID (= Karten-/Profilnummer). Darüber gruppieren.
    raw: list[dict[str, Any]] = []
    doc_ctx: dict[str, dict[str, Any]] = {}
    periods_start, periods_end = [], []

    for L in root.iter():
        if _ln(L.tag) != "InvoiceLine":
            continue
        amount = float(_first_child_text(L, "LineExtensionAmount") or 0)
        qty = _first_child_text(L, "InvoicedQuantity")
        item_name = price = None
        for c in L:
            if _ln(c.tag) == "Item":
                item_name = _first_child_text(c, "Name")
            elif _ln(c.tag) == "Price":
                price = _first_child_text(c, "PriceAmount")
        p_start = p_end = docref = None
        for e in L.iter():
            if _ln(e.tag) == "InvoicePeriod" and p_start is None:
                p_start = _first_child_text(e, "StartDate")
                p_end = _first_child_text(e, "EndDate")
            elif _ln(e.tag) == "DocumentReference" and docref is None:
                docref = _first_child_text(e, "ID")
        if p_start:
            periods_start.append(p_start)
        if p_end:
            periods_end.append(p_end)

        props = _line_props(L)
        if docref and props.get("Rufnummer") and docref not in doc_ctx:
            doc_ctx[docref] = {
                "rufnummer": props.get("Rufnummer"),
                "kostenstelle": props.get("Kostenstelle"),
                "kostenstellennutzer": props.get("Kostenstellennutzer"),
            }
        raw.append({
            "docref": docref, "props": props, "item_name": item_name,
            "amount": amount, "qty": qty, "price": price,
            "p_start": p_start, "p_end": p_end,
        })

    # Zweite Runde: Rufnummer/Kostenstelle je Zeile über docref-Kontext auflösen
    lines: list[dict[str, Any]] = []
    for r in raw:
        props = r["props"]
        ctx = doc_ctx.get(r["docref"], {})
        lines.append({
            "rufnummer": props.get("Rufnummer") or ctx.get("rufnummer"),
            "kostenstelle": props.get("Kostenstelle") or ctx.get("kostenstelle"),
            "kostenstellennutzer": props.get("Kostenstellennutzer") or ctx.get("kostenstellennutzer"),
            "item_name": r["item_name"],
            "category": _classify(r["item_name"] or "", r["amount"]),
            "amount": r["amount"],
            "quantity": float(r["qty"]) if r["qty"] else None,
            "price": float(r["price"]) if r["price"] else None,
            "period_start": r["p_start"],
            "period_end": r["p_end"],
            "data_contracted_gb": _to_gb(props.get("Vertraglich vereinbartes Datenvolumen"),
                                         props.get("Vertraglich vereinbartes Dateneinheit")),
            "data_used_gb": _to_gb(props.get("Verbrauchtes Datenvolumen"),
                                   props.get("Verbrauchtes Dateneinheit")),
            "vertragsbeginn": props.get("Vertragsbeginn"),
            "mindestlaufzeit_ende": props.get("Aktuelles Ende der Mindestvertragslaufzeit"),
        })

    return InvoiceData(
        filename=path.name,
        invoice_number=header.get("ID"),
        kundenkonto=kundenkonto,
        issue_date=header.get("IssueDate"),
        due_date=header.get("DueDate"),
        period_start=min(periods_start) if periods_start else None,
        period_end=max(periods_end) if periods_end else None,
        total_net=total_net,
        total_tax=total_tax,
        total_gross=total_gross,
        lines=lines,
    )
