"""Erzeugt synthetische XRechnung/UBL-Rechnungen (XML) — nur Fantasiewerte.

Bildet die reale Struktur ab (siehe Spec): Positionen in Bloecken je Rufnummer,
wobei Ladungen (+) die Props Rufnummer/Kostenstelle tragen, Rabatte (-) und
Info-Zeilen (0) NICHT — damit der Carry-Forward im Parser testbar ist.

CLI:
    python fixtures/fake_invoice_generator.py out.xml --lines 5 --seed 1
"""
from __future__ import annotations

import argparse
import xml.etree.ElementTree as ET
from pathlib import Path

from faker import Faker

NS = {
    "ubl": "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
}
for _p, _u in NS.items():
    ET.register_namespace(_p, _u)


def _q(prefix: str, tag: str) -> str:
    return f"{{{NS[prefix]}}}{tag}"


def _sub(parent, prefix, tag, text=None, **attrs):
    e = ET.SubElement(parent, _q(prefix, tag), {k: str(v) for k, v in attrs.items()})
    if text is not None:
        e.text = str(text)
    return e


def _line(root, idx, item_name, amount, props, period, docref=None):
    L = ET.SubElement(root, _q("cac", "InvoiceLine"))
    _sub(L, "cbc", "ID", idx)
    _sub(L, "cbc", "InvoicedQuantity", "1")
    _sub(L, "cbc", "LineExtensionAmount", f"{amount:.2f}", currencyID="EUR")
    ip = ET.SubElement(L, _q("cac", "InvoicePeriod"))
    _sub(ip, "cbc", "StartDate", period[0])
    _sub(ip, "cbc", "EndDate", period[1])
    # DocumentReference gruppiert einen Block (gleiche Karten-/Profilnummer)
    if docref:
        dr = ET.SubElement(L, _q("cac", "DocumentReference"))
        _sub(dr, "cbc", "ID", docref)
        _sub(dr, "cbc", "DocumentTypeCode", "130")
    it = ET.SubElement(L, _q("cac", "Item"))
    _sub(it, "cbc", "Name", item_name)
    for nm, val in props.items():
        aip = ET.SubElement(it, _q("cac", "AdditionalItemProperty"))
        _sub(aip, "cbc", "Name", nm)
        _sub(aip, "cbc", "Value", val)
    pr = ET.SubElement(L, _q("cac", "Price"))
    _sub(pr, "cbc", "PriceAmount", f"{abs(amount):.2f}", currencyID="EUR")


def generate_invoice(
    path, rufnummern=None, n=5, seed=0,
    period=("2026-06-01", "2026-06-30"), issue_date="2026-07-06",
    due_date="2026-07-20", invoice_number="230000000001", kundenkonto="0099999999",
) -> Path:
    fake = Faker("de_DE")
    Faker.seed(seed)
    if rufnummern is None:
        rufnummern = ["0151" + fake.numerify("########") for _ in range(n)]
    kostenstellen = [f"KST-{fake.random_int(1000, 9999)}" for _ in range(max(1, len(rufnummern) // 3))]

    root = ET.Element(_q("ubl", "Invoice"))
    _sub(root, "cbc", "CustomizationID", "urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_3.0")
    _sub(root, "cbc", "ID", invoice_number)
    _sub(root, "cbc", "IssueDate", issue_date)
    _sub(root, "cbc", "DueDate", due_date)
    _sub(root, "cbc", "InvoiceTypeCode", "380")

    total = 0.0
    idx = 0
    for i, ruf in enumerate(rufnummern):
        kst = kostenstellen[i % len(kostenstellen)]
        nutzer = fake.name()
        card = "8965" + fake.numerify("#########")  # DocumentReference/Karten-Nr je Block
        charge_props = {
            "Rufnummer": ruf, "Kostenstelle": kst, "Kostenstellennutzer": nutzer,
            "Vertragsbeginn": "2022-05-01", "Kündigungsfrist": "3 Monate",
        }
        grund = round(59.95 + (i % 5) * 5, 2)
        # Rabatt zuerst (OHNE Rufnummer, aber gleiche docref -> Gruppierungs-Test)
        rab = -round(grund * 0.25, 2)
        idx += 1; _line(root, idx, "25% auf Grundpreis Business Mobil L", rab, {}, period, docref=card); total += rab
        # Grundpreis (Ladung, mit Props)
        idx += 1; _line(root, idx, "Business Mobil L mit Top-Handy (3. Generation)", grund, charge_props, period, docref=card); total += grund
        # Option (Ladung, mit Props)
        opt = 16.76
        idx += 1; _line(root, idx, "DataPlus 12 GB", opt, charge_props, period, docref=card); total += opt
        # bei jedem 3. ein Auslandsverbrauch (Ladung)
        if i % 3 == 0:
            ausland = round(2.5 + i * 0.1, 2)
            idx += 1; _line(root, idx, "Abgehende Verbindungen Ländergruppe 3", ausland, charge_props, period, docref=card); total += ausland

    # Daten-Info-Zeilen: separater Block am Ende, EIGENE docref, KEINE Rufnummer
    # (spiegelt die reale Rechnung — daher nicht per Rufnummer zuordenbar).
    for i in range(len(rufnummern)):
        data_props = {
            "Vertraglich vereinbartes Datenvolumen": "12582912",  # 12 GB in KB (2P)
            "Vertraglich vereinbartes Dateneinheit": "2P",
            "Verbrauchtes Datenvolumen": str(1258291 + i * 100000),
            "Verbrauchtes Dateneinheit": "2P",
        }
        idx += 1
        _line(root, idx, "Wichtige Hinweise zu Ihrem Vertrag (Datenvolumen)", 0.0,
              data_props, period, docref="DATA" + str(i))

    net = round(total, 2)
    tax = round(net * 0.19, 2)
    gross = round(net + tax, 2)
    tt = ET.SubElement(root, _q("cac", "TaxTotal"))
    _sub(tt, "cbc", "TaxAmount", f"{tax:.2f}", currencyID="EUR")
    lmt = ET.SubElement(root, _q("cac", "LegalMonetaryTotal"))
    _sub(lmt, "cbc", "LineExtensionAmount", f"{net:.2f}", currencyID="EUR")
    _sub(lmt, "cbc", "TaxExclusiveAmount", f"{net:.2f}", currencyID="EUR")
    _sub(lmt, "cbc", "TaxInclusiveAmount", f"{gross:.2f}", currencyID="EUR")
    _sub(lmt, "cbc", "PayableAmount", f"{gross:.2f}", currencyID="EUR")

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(path, encoding="UTF-8", xml_declaration=True)
    return path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("out")
    ap.add_argument("--lines", type=int, default=5)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    p = generate_invoice(args.out, n=args.lines, seed=args.seed)
    print(f"geschrieben: {p} (synthetisch, {args.lines} Rufnummern)")


if __name__ == "__main__":
    main()
