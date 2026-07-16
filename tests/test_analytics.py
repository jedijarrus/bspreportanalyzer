"""Tests für app.analytics — reine Auswertungsfunktionen.

Arbeiten auf Contract-Dicts wie store.get_contracts sie liefert
(Datumsfelder als ISO-Strings).
"""
import datetime as dt

from app import analytics

TODAY = dt.date(2026, 6, 25)


def _c(**kw):
    """Minimaler Contract-Dict-Builder."""
    base = {"rufnummer": "0151000", "tarif": "Tarif A", "kartentyp": "eSIM",
            "vertragsstatus": "A", "sperren": None, "bindefristende": None,
            "daten_optionen": None}
    base.update(kw)
    return base


def _r(rv, ruf, date, rid, **kw):
    """Contract mit Report-Metadaten (für current_fleet)."""
    c = _c(rahmenvertrag=rv, rufnummer=ruf, **kw)
    c["_report_date"] = date
    c["_report_id"] = rid
    return c


# ---- Aktuelle Flotte (Vereinigung neuester Report je Rahmenvertrag) ------
def test_current_fleet_vereint_verschiedene_rahmenvertraege():
    rows = [
        _r("RV-A", "A1", "2026-06-01", 1),
        _r("RV-B", "B1", "2026-06-02", 2),
        _r("RV-B", "B2", "2026-06-02", 2),
    ]
    fleet = analytics.current_fleet(rows)
    assert len(fleet) == 3
    assert {c["rahmenvertrag"] for c in fleet} == {"RV-A", "RV-B"}


def test_current_fleet_neuester_report_ersetzt_alten_je_rv():
    rows = [
        _r("RV-A", "A1", "2026-05-01", 1, tarif="Alt"),
        _r("RV-A", "A1", "2026-06-01", 2, tarif="Neu"),  # neuer
    ]
    fleet = analytics.current_fleet(rows)
    assert len(fleet) == 1
    assert fleet[0]["tarif"] == "Neu"


def test_current_fleet_gekuendigte_linie_verschwindet():
    # RV-A: alter Report hatte A1+A2, neuer nur noch A1 -> A2 weg
    rows = [
        _r("RV-A", "A1", "2026-05-01", 1),
        _r("RV-A", "A2", "2026-05-01", 1),
        _r("RV-A", "A1", "2026-06-01", 2),
    ]
    fleet = analytics.current_fleet(rows)
    assert {c["rufnummer"] for c in fleet} == {"A1"}


def test_current_fleet_leer():
    assert analytics.current_fleet([]) == []


# ---- Bindefrist / VVL ----------------------------------------------------
def test_bindefrist_buckets_zaehlt_korrekt():
    contracts = [
        _c(bindefristende="2026-01-01T00:00:00"),  # abgelaufen
        _c(bindefristende="2026-07-10T00:00:00"),  # 0-3 Monate
        _c(bindefristende="2027-01-01T00:00:00"),  # 3-12 Monate
        _c(bindefristende="2029-01-01T00:00:00"),  # >12 Monate
    ]
    b = analytics.bindefrist_buckets(contracts, TODAY)
    assert b["abgelaufen"] == 1
    assert b["0-3_monate"] == 1
    assert b["3-12_monate"] == 1
    assert b[">12_monate"] == 1


def test_bindefrist_buckets_none_als_ohne_datum():
    b = analytics.bindefrist_buckets([_c(bindefristende=None)], TODAY)
    assert b["ohne_datum"] == 1


def test_expiring_inkl_abgelaufen_sortiert():
    contracts = [
        _c(rufnummer="C", bindefristende="2026-08-01T00:00:00"),
        _c(rufnummer="A", bindefristende="2026-01-01T00:00:00"),
        _c(rufnummer="X", bindefristende="2030-01-01T00:00:00"),  # nicht bald
    ]
    res = analytics.expiring(contracts, TODAY, within_days=90)
    rufs = [r["rufnummer"] for r in res]
    assert rufs == ["A", "C"]  # aufsteigend nach Datum, X ausserhalb Fenster


# ---- Verteilungen --------------------------------------------------------
def test_distribution_sortiert_absteigend():
    contracts = [_c(tarif="A"), _c(tarif="A"), _c(tarif="B")]
    d = analytics.distribution(contracts, "tarif")
    assert d == [("A", 2), ("B", 1)]


def test_split_distribution_trennt_kommas():
    contracts = [
        _c(daten_optionen="Data 80 GB 5G, DataPlus 12 GB"),
        _c(daten_optionen="Data 80 GB 5G"),
    ]
    d = dict(analytics.split_distribution(contracts, "daten_optionen"))
    assert d["Data 80 GB 5G"] == 2
    assert d["DataPlus 12 GB"] == 1


def test_split_distribution_ignoriert_none():
    contracts = [_c(daten_optionen=None), _c(daten_optionen="X")]
    d = dict(analytics.split_distribution(contracts, "daten_optionen"))
    assert d == {"X": 1}


# ---- Bestand / Status ----------------------------------------------------
def test_inventory_grundzahlen():
    contracts = [
        _c(kartentyp="eSIM", sperren=None),
        _c(kartentyp="eSIM", sperren="Dienste3"),
        _c(kartentyp="TRIPLE-SIM", sperren=None),
    ]
    inv = analytics.inventory(contracts)
    assert inv["total"] == 3
    assert inv["gesperrt"] == 1
    assert dict(inv["nach_kartentyp"])["eSIM"] == 2


# ---- Vergleich -----------------------------------------------------------
def test_diff_added_removed():
    old = [_c(rufnummer="A"), _c(rufnummer="B")]
    new = [_c(rufnummer="B"), _c(rufnummer="C")]
    d = analytics.diff(old, new)
    assert d["hinzugefuegt"] == ["C"]
    assert d["entfernt"] == ["A"]


def test_diff_changed_feld():
    old = [_c(rufnummer="A", tarif="Alt")]
    new = [_c(rufnummer="A", tarif="Neu")]
    d = analytics.diff(old, new)
    changed = d["geaendert"]
    assert len(changed) == 1
    assert changed[0]["rufnummer"] == "A"
    assert ("tarif", "Alt", "Neu") in changed[0]["aenderungen"]


def test_diff_keine_aenderung():
    old = [_c(rufnummer="A", tarif="X")]
    new = [_c(rufnummer="A", tarif="X")]
    d = analytics.diff(old, new)
    assert d["geaendert"] == []


# ---- Trend ---------------------------------------------------------------
# ---- Rufnummer-Normalisierung (Join Report <-> Rechnung) -----------------
def test_normalize_rufnummer_vereinheitlicht_formate():
    a = analytics.normalize_rufnummer("+49-151-2345678")
    b = analytics.normalize_rufnummer("491512345678")
    c = analytics.normalize_rufnummer("0049 151 2345678")
    assert a == b == c
    assert a.startswith("0")


def test_normalize_rufnummer_leer():
    assert analytics.normalize_rufnummer(None) is None
    assert analytics.normalize_rufnummer("") is None


# ---- Rechnungs-/Kostenauswertungen ---------------------------------------
def _il(**kw):
    base = {"rufnummer": "A", "kostenstelle": "K1", "item_name": "x",
            "category": "grundpreis", "amount": 10.0}
    base.update(kw)
    return base


def test_kosten_je_rufnummer_summiert_und_trennt_rabatt():
    lines = [
        _il(rufnummer="A", category="grundpreis", amount=60),
        _il(rufnummer="A", category="rabatt", amount=-15),
        _il(rufnummer="B", category="grundpreis", amount=40),
    ]
    r = analytics.kosten_je_rufnummer(lines)
    assert round(r["A"]["netto"], 2) == 45
    assert round(r["A"]["rabatt"], 2) == -15
    assert round(r["B"]["netto"], 2) == 40


def test_kosten_je_kostenstelle():
    lines = [
        _il(rufnummer="A", kostenstelle="K1", amount=45),
        _il(rufnummer="B", kostenstelle="K1", amount=40),
        _il(rufnummer="C", kostenstelle="K2", amount=30),
    ]
    k = {x["kostenstelle"]: x for x in analytics.kosten_je_kostenstelle(lines)}
    assert round(k["K1"]["netto"]) == 85
    assert k["K1"]["anzahl_rufnummern"] == 2


def test_kosten_je_kategorie():
    lines = [_il(category="grundpreis", amount=60), _il(category="rabatt", amount=-15),
             _il(category="option", amount=17)]
    d = dict(analytics.kosten_je_kategorie(lines))
    assert round(d["grundpreis"]) == 60 and round(d["rabatt"]) == -15


def test_invoice_diff_delta_je_kostenstelle_und_rufnummer():
    alt = [_il(rufnummer="A", kostenstelle="K1", category="grundpreis", amount=60)]
    neu = [_il(rufnummer="A", kostenstelle="K1", category="grundpreis", amount=70),
           _il(rufnummer="B", kostenstelle="K2", category="grundpreis", amount=30)]
    d = analytics.invoice_diff(alt, neu)
    assert round(d["gesamt"]["delta"]) == 40  # (70+30) - 60
    assert d["neu"] == ["B"]
    assert d["weggefallen"] == []
    ruf_a = [x for x in d["je_rufnummer"] if x["rufnummer"] == "A"][0]
    assert round(ruf_a["delta"]) == 10


def test_invoice_diff_weggefallen():
    alt = [_il(rufnummer="A", amount=50)]
    neu = [_il(rufnummer="B", amount=50)]
    d = analytics.invoice_diff(alt, neu)
    assert d["weggefallen"] == ["A"] and d["neu"] == ["B"]


def test_reconcile_zugeordnet_und_rest():
    lines = [_il(rufnummer="A", amount=45), _il(rufnummer="B", amount=40),
             _il(rufnummer=None, amount=-5)]
    r = analytics.reconcile(lines, total_net=80.0)
    assert round(r["zugeordnet"]) == 85
    assert round(r["nicht_zugeordnet"]) == -5
    assert r["anzahl_rufnummern"] == 2


def test_datenauslastung_buckets():
    lines = [
        _il(category="info", amount=0, data_contracted_gb=80, data_used_gb=9),   # 11%
        _il(category="info", amount=0, data_contracted_gb=80, data_used_gb=90),  # >100
        _il(category="info", amount=0, data_contracted_gb=80, data_used_gb=4),   # 5%
    ]
    a = analytics.datenauslastung(lines)
    assert a["anzahl"] == 3
    assert a["ueber_100"] == 1
    assert a["unter_25"] == 2
    assert a["unter_10"] == 1
    # GB-Summen + Gesamtauslastung
    assert round(a["gebucht_gb"]) == 240        # 80*3
    assert round(a["verbraucht_gb"]) == 103      # 9+90+4
    assert round(a["auslastung_pct"]) == 43      # 103/240


def test_datenauslastung_liste_sortiert():
    lines = [
        _il(data_contracted_gb=80, data_used_gb=40),  # 50%
        _il(data_contracted_gb=80, data_used_gb=4),    # 5%
        _il(data_contracted_gb=80, data_used_gb=90),   # 112%
        _il(data_contracted_gb=None),                  # ignoriert
    ]
    liste = analytics.datenauslastung_liste(lines)
    assert len(liste) == 3
    assert [round(r["pct"]) for r in liste] == [5, 50, 112]  # aufsteigend
    assert liste[0]["gebucht_gb"] == 80 and liste[0]["verbraucht_gb"] == 4


def test_kosten_trend_je_periode():
    lines = [
        {"_period_start": "2026-05-01", "amount": 100, "rufnummer": "A"},
        {"_period_start": "2026-06-01", "amount": 120, "rufnummer": "A"},
        {"_period_start": "2026-06-01", "amount": 30, "rufnummer": "B"},
    ]
    t = analytics.kosten_trend(lines)
    assert len(t) == 2
    p6 = [x for x in t if x["period"] == "2026-06-01"][0]
    assert round(p6["netto"]) == 150


def test_trend_zeitreihe():
    snapshots = [
        {"report_date": "2026-05-01T00:00:00",
         "contracts": [_c(sperren=None), _c(sperren="x")]},
        {"report_date": "2026-06-01T00:00:00",
         "contracts": [_c(), _c(), _c()]},
    ]
    t = analytics.trend(snapshots, TODAY)
    assert len(t) == 2
    assert t[0]["total"] == 2
    assert t[0]["gesperrt"] == 1
    assert t[1]["total"] == 3
    # chronologisch sortiert
    assert t[0]["report_date"] <= t[1]["report_date"]
