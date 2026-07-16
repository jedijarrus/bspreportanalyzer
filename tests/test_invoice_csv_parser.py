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
