"""Liest Telekom-Mobilfunk-Rechnungen (Positions-CSV) in normalisierte Positionen.

Format: positionelles CSV (cp1252, ';') — eine Kopfzeile (>=34 Spalten,
rechnungsweit) plus Detailzeilen (>=22 Spalten) je Rufnummer. In diesem Format
tragen **alle** Zeilen — auch der Datenverbrauch — die Rufnummer (Spalte 5),
daher ist Datenauslastung pro Vertrag möglich.

Kernpunkte:
- Kategorisierung der Leistungsart: grundpreis / option / rabatt / verbrauch / info.
- Datenvolumen (vereinbart/verbraucht) wird nach GB normiert.
- Deutsche Zahlformate mit Tausenderpunkten (_de_num).
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


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


def parse_invoice(path: str | Path) -> InvoiceData:
    """Liest eine Telekom-Rechnung im Positions-CSV-Format (cp1252, ';')."""
    path = Path(path)
    if path.suffix.lower() != ".csv":
        raise ValueError(f"Nur .csv-Rechnungen werden unterstützt (nicht {path.suffix!r}).")
    return _parse_csv(path)


def _iso(d: str | None) -> str | None:
    """'01.06.2026' -> '2026-06-01'."""
    if not d:
        return None
    m = re.match(r"(\d{2})\.(\d{2})\.(\d{4})", d.strip())
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else d


def _de_num(s: str | None) -> float | None:
    """Deutsches Zahlformat: '1.234,56' / '83.886.080' / '-17,43' -> float."""
    if s is None or s.strip() == "":
        return None
    try:
        return float(s.strip().replace(".", "").replace(",", "."))
    except ValueError:
        return None


def _parse_csv(path: Path) -> InvoiceData:
    with open(path, encoding="cp1252", newline="") as f:
        rows = list(csv.reader(f, delimiter=";"))

    header = next((r for r in rows if len(r) >= 34), [""] * 34)
    invoice_number = header[0] or None
    issue_date = _iso(header[1])
    kundenkonto = header[5] or None
    period_start, period_end = _iso(header[6]), _iso(header[7])
    due_date = _iso(header[11]) if len(header) > 11 else None

    lines: list[dict[str, Any]] = []
    data_by_ruf: dict[str, dict[str, Any]] = {}

    for r in rows:
        if len(r) < 18 or len(r) >= 34:
            continue  # Zwischensummen (<18) und die Kopfzeile (>=34 Spalten) überspringen
        rufnummer = (r[5] or "").strip() or None
        kostenstelle = (r[3] or "").strip() or None
        nutzer = (r[4] or "").strip() or None
        label = (r[10] or "").strip()
        amount = _de_num(r[17]) if len(r) > 17 else None

        if amount is not None:  # Kostenzeile
            lines.append({
                "rufnummer": rufnummer, "kostenstelle": kostenstelle,
                "kostenstellennutzer": nutzer, "item_name": label,
                "category": _classify(label, amount), "amount": amount,
                "quantity": None, "price": None,
                "period_start": _iso(r[14]) if len(r) > 14 else None,
                "period_end": _iso(r[15]) if len(r) > 15 else None,
                "data_contracted_gb": None, "data_used_gb": None,
                "vertragsbeginn": None, "mindestlaufzeit_ende": None,
            })
        elif rufnummer and len(r) > 13 and r[12].strip():  # Datenvolumen-Zeile
            gb = _to_gb(_de_num(r[12]), r[13])  # _de_num wegen Tausenderpunkten
            d = data_by_ruf.setdefault(rufnummer, {
                "rufnummer": rufnummer, "kostenstelle": kostenstelle,
                "kostenstellennutzer": nutzer, "contracted": None, "used": None})
            if "Vertraglich vereinbartes Datenvolumen" in label:
                d["contracted"] = gb
            elif "Insgesamt verbrauchtes Datenvolumen" in label:
                d["used"] = gb

    # eine zusammengefasste Datenzeile je Rufnummer (mit Verbrauch verlinkt)
    for d in data_by_ruf.values():
        lines.append({
            "rufnummer": d["rufnummer"], "kostenstelle": d["kostenstelle"],
            "kostenstellennutzer": d["kostenstellennutzer"],
            "item_name": "Datenvolumen", "category": "info", "amount": 0.0,
            "quantity": None, "price": None, "period_start": period_start,
            "period_end": period_end, "data_contracted_gb": d["contracted"],
            "data_used_gb": d["used"], "vertragsbeginn": None, "mindestlaufzeit_ende": None,
        })

    net = round(sum(l["amount"] for l in lines), 2)
    tax = round(net * 0.19, 2)
    return InvoiceData(
        filename=path.name, invoice_number=invoice_number, kundenkonto=kundenkonto,
        issue_date=issue_date, due_date=due_date, period_start=period_start,
        period_end=period_end, total_net=net, total_tax=tax, total_gross=round(net + tax, 2),
        lines=lines,
    )
