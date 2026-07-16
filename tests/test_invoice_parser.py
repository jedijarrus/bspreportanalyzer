"""Tests für app.invoice_parser — XRechnung/UBL einlesen + normalisieren."""
import pytest

from app import invoice_parser


def test_rechnungsnummer_aus_kopf(make_invoice):
    inv = invoice_parser.parse_invoice(make_invoice(invoice_number="230000009999"))
    assert inv.invoice_number == "230000009999"


def test_ausstell_und_faelligkeitsdatum(make_invoice):
    inv = invoice_parser.parse_invoice(make_invoice())
    assert inv.issue_date == "2026-07-06"
    assert inv.due_date == "2026-07-20"


def test_summen_netto_ust_brutto(make_invoice):
    inv = invoice_parser.parse_invoice(make_invoice(n=3))
    assert inv.total_net > 0
    assert round(inv.total_net + inv.total_tax, 2) == inv.total_gross
    assert round(inv.total_net * 0.19, 2) == inv.total_tax


def test_alle_positionen_gelesen(make_invoice):
    inv = invoice_parser.parse_invoice(make_invoice(rufnummern=["0151A", "0151B"]))
    # je Rufnummer mind. 4 Positionen (Grund, Rabatt, Option, Daten-Info)
    assert len(inv.lines) >= 8


def test_rabatt_erbt_rufnummer_via_documentreference(make_invoice):
    # Rabatt trägt keine eigene Rufnummer, aber dieselbe DocumentReference wie
    # die Ladung des Blocks -> Zuordnung über docref-Gruppierung.
    inv = invoice_parser.parse_invoice(make_invoice(rufnummern=["0151XYZ"], n=1))
    rabatte = [l for l in inv.lines if l["category"] == "rabatt"]
    assert rabatte and all(l["rufnummer"] == "0151XYZ" for l in rabatte)


def test_kategorien_klassifiziert(make_invoice):
    inv = invoice_parser.parse_invoice(make_invoice(rufnummern=["0151A"], n=1))
    cats = {l["item_name"]: l["category"] for l in inv.lines}
    assert cats["Business Mobil L mit Top-Handy (3. Generation)"] == "grundpreis"
    assert cats["25% auf Grundpreis Business Mobil L"] == "rabatt"
    assert cats["DataPlus 12 GB"] == "option"
    assert cats["Wichtige Hinweise zu Ihrem Vertrag (Datenvolumen)"] == "info"


def test_verbrauch_kategorie(make_invoice):
    # i%3==0 -> erste Rufnummer bekommt eine Auslands-Verbrauchszeile
    inv = invoice_parser.parse_invoice(make_invoice(rufnummern=["0151A"], n=1))
    verbrauch = [l for l in inv.lines if l["category"] == "verbrauch"]
    assert verbrauch and "Verbindungen" in verbrauch[0]["item_name"]


def test_rabatt_betrag_negativ(make_invoice):
    inv = invoice_parser.parse_invoice(make_invoice(rufnummern=["0151A"], n=1))
    rabatt = [l for l in inv.lines if l["category"] == "rabatt"][0]
    assert rabatt["amount"] < 0


def test_datenvolumen_in_gb_normiert(make_invoice):
    inv = invoice_parser.parse_invoice(make_invoice(rufnummern=["0151A"], n=1))
    info = [l for l in inv.lines if l["category"] == "info" and l["data_contracted_gb"]][0]
    # 12582912 KB / 1024 / 1024 = 12.0 GB
    assert round(info["data_contracted_gb"], 1) == 12.0
    assert info["data_used_gb"] is not None


def test_kostenstelle_gelesen(make_invoice):
    inv = invoice_parser.parse_invoice(make_invoice(rufnummern=["0151A"], n=1))
    charge = [l for l in inv.lines if l["category"] == "grundpreis"][0]
    assert charge["kostenstelle"] is not None
