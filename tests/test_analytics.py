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
