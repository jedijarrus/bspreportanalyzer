"""Tests für den CSV-Rechnungs-Parser (Telekom-Format).

Der große Unterschied zur XML: Datenverbrauchs-Zeilen tragen die Rufnummer,
daher ist Auslastung PRO Vertrag möglich.
"""
from app import invoice_parser


def test_csv_wird_erkannt_und_geparst(make_invoice_csv):
    inv = invoice_parser.parse_invoice(make_invoice_csv(invoice_number="230000009999"))
    assert inv.invoice_number == "230000009999"
    assert len(inv.lines) > 0


def test_csv_zeitraum_iso(make_invoice_csv):
    inv = invoice_parser.parse_invoice(make_invoice_csv())
    assert inv.period_start == "2026-06-01"
    assert inv.period_end == "2026-06-30"


def test_csv_datenzeile_traegt_rufnummer(make_invoice_csv):
    inv = invoice_parser.parse_invoice(make_invoice_csv(rufnummern=["0151ABC"], n=1))
    data = [l for l in inv.lines if l["data_contracted_gb"]]
    assert data, "keine Datenzeile"
    assert data[0]["rufnummer"] == "0151ABC"           # <- der springende Punkt
    assert round(data[0]["data_contracted_gb"]) == 80   # 83886080 KB
    assert data[0]["data_used_gb"] is not None


def test_csv_kosten_kategorien(make_invoice_csv):
    inv = invoice_parser.parse_invoice(make_invoice_csv(rufnummern=["0151A"], n=1))
    cats = {l["item_name"]: l["category"] for l in inv.lines}
    assert cats["Business Mobil L mit Top-Handy (3. Generation)"] == "grundpreis"
    assert cats["25% auf Grundpreis Business Mobil L"] == "rabatt"
    assert cats["DataPlus 12 GB"] == "option"


def test_csv_summen(make_invoice_csv):
    inv = invoice_parser.parse_invoice(make_invoice_csv(n=3))
    assert inv.total_net > 0
    assert round(inv.total_net * 0.19, 2) == inv.total_tax


def test_csv_kosten_je_rufnummer_stimmt(make_invoice_csv):
    from app import analytics
    inv = invoice_parser.parse_invoice(make_invoice_csv(rufnummern=["0151A"], n=1))
    k = analytics.kosten_je_rufnummer(inv.lines)
    assert "0151A" in k and k["0151A"]["netto"] > 0


def test_csv_kopfzeile_nicht_als_datenzeile(tmp_path):
    """Die 34-spaltige Kopfzeile darf nicht als Detailzeile geparst werden
    (sonst Phantom-Rufnummer = Kundenkonto, wie in echten Telekom-CSV)."""
    import csv
    head = [""] * 34
    head[0], head[5], head[12] = "230000000001", "0099999999", "Telekom Deutschland GmbH"
    head[6], head[7] = "01.06.2026", "30.06.2026"
    head[17] = "DE93ZZZ00000000000"  # Gläubiger-ID, keine Zahl
    row = [""] * 22
    row[5], row[8], row[10], row[16], row[17] = "0151 1", "Grundpreise", "Business Mobil L", "19", "69,71"
    p = tmp_path / "Rechnung_kopf.csv"
    with open(p, "w", encoding="cp1252", newline="") as f:
        csv.writer(f, delimiter=";").writerows([head, row])
    inv = invoice_parser.parse_invoice(p)
    rufs = {l["rufnummer"] for l in inv.lines if l.get("rufnummer")}
    assert "0099999999" not in rufs   # Kundenkonto NICHT als Rufnummer
    assert "0151 1" in rufs           # echte Detailzeile bleibt erhalten


def test_csv_ohne_kopfzeile_wird_abgelehnt(tmp_path):
    """Defektes/fremdes CSV (keine 34-spaltige Kopfzeile) -> ValueError statt leerer Rechnung."""
    import csv
    import pytest
    p = tmp_path / "kaputt.csv"
    with open(p, "w", encoding="cp1252", newline="") as f:
        csv.writer(f, delimiter=";").writerows([["a", "b", "c"], ["1", "2", "3"]])
    with pytest.raises(ValueError):
        invoice_parser.parse_invoice(p)
