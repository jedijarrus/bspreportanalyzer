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


# ---- Frische / Veraltet-Guardrail ---------------------------------------
FRESH_TODAY = dt.date(2026, 8, 4)


def test_fleet_freshness_alles_frisch_nicht_stale():
    fleet = [
        _r("RV-A", "A1", "2026-08-01", 3),    # 3 Tage
        _r("RV-B", "B1", "2026-07-25", 4),    # 10 Tage
    ]
    f = analytics.fleet_freshness(fleet, FRESH_TODAY, max_age_days=14)
    assert f["stale"] is False
    assert f["rv"]["RV-A"]["alter_tage"] == 3
    assert f["rv"]["RV-B"]["alter_tage"] == 10
    assert f["stand_alter_tage"] == 10  # worst case = ältester Stand
    assert f["max_age_tage"] == 14


def test_fleet_freshness_ein_rv_veraltet_anderer_frisch():
    fleet = [
        _r("RV-A", "A1", "2026-06-25", 1),    # 40 Tage -> veraltet
        _r("RV-B", "B1", "2026-08-01", 2),    # 3 Tage
    ]
    f = analytics.fleet_freshness(fleet, FRESH_TODAY, max_age_days=14)
    assert f["rv"]["RV-A"]["stale"] is True
    assert f["rv"]["RV-B"]["stale"] is False
    assert f["stale"] is True
    assert f["stand_alter_tage"] == 40  # ältester Stand
    assert f["rv"]["RV-A"]["report_date"] == "2026-06-25"


def test_fleet_freshness_grenze_14_frisch_15_stale():
    f14 = analytics.fleet_freshness([_r("RV", "A", "2026-07-21", 1)], FRESH_TODAY, 14)
    assert f14["rv"]["RV"]["alter_tage"] == 14 and f14["stale"] is False
    f15 = analytics.fleet_freshness([_r("RV", "A", "2026-07-20", 1)], FRESH_TODAY, 14)
    assert f15["rv"]["RV"]["alter_tage"] == 15 and f15["stale"] is True


def test_fleet_freshness_leere_flotte():
    f = analytics.fleet_freshness([], FRESH_TODAY, 14)
    assert f["rv"] == {}
    assert f["stale"] is False
    assert f["stand_alter_tage"] is None


def test_fleet_freshness_ohne_report_date_konservativ_stale():
    f = analytics.fleet_freshness([_r("RV", "A", None, 1)], FRESH_TODAY, 14)
    assert f["rv"]["RV"]["alter_tage"] is None
    assert f["rv"]["RV"]["stale"] is True
    assert f["stale"] is True


def test_fleet_freshness_zukunftsdatum_ist_frisch():
    # Tippfehler im Dateinamen -> Datum in der Zukunft: nicht crashen, als frisch werten
    f = analytics.fleet_freshness([_r("RV", "A", "2026-09-01", 1)], FRESH_TODAY, 14)
    assert f["rv"]["RV"]["stale"] is False


def test_fleet_freshness_env_fenster_wird_respektiert():
    fleet = [_r("RV", "A", "2026-07-28", 1)]  # 7 Tage
    assert analytics.fleet_freshness(fleet, FRESH_TODAY, max_age_days=14)["stale"] is False
    assert analytics.fleet_freshness(fleet, FRESH_TODAY, max_age_days=5)["stale"] is True


# ---- Rufnummer-Monitoring (Verlauf über Monate) -------------------------
def _iline(period, ruf, cat, amount, item="", cg=None, ug=None):
    """Rechnungszeile mit Perioden-Meta (wie store.all_invoice_lines liefert)."""
    return {"_period_start": period, "rufnummer": ruf, "category": cat,
            "item_name": item, "amount": amount,
            "data_contracted_gb": cg, "data_used_gb": ug}


def test_linie_verlauf_gruppiert_je_monat_und_filtert_rufnummer():
    lines = [
        # Mai — Ziel-Rufnummer (verschiedene Schreibweisen matchen via normalize)
        _iline("2026-05-01", "+49-151-1", "grundpreis", 69.71, "Business Mobil L"),
        _iline("2026-05-01", "+49-151-1", "rabatt", -17.43, "25% auf Grundpreis"),
        _iline("2026-05-01", "+49-151-1", "option", 16.76, "DataPlus 12 GB"),
        _iline("2026-05-01", "+49-151-1", "info", 0.0, "Datenvolumen", cg=80.0, ug=8.0),
        # Juni — gleiche Linie, andere Schreibweise
        _iline("2026-06-01", "0151 1", "grundpreis", 69.71, "Business Mobil L"),
        _iline("2026-06-01", "0151 1", "info", 0.0, "Datenvolumen", cg=80.0, ug=40.0),
        # Fremde Linie (muss rausgefiltert werden)
        _iline("2026-06-01", "0170 999", "grundpreis", 50.0, "Flat S"),
    ]
    v = analytics.linie_verlauf(lines, "0151-1")
    assert [m["period"] for m in v] == ["2026-05-01", "2026-06-01"]  # chronologisch
    m0 = v[0]
    assert m0["netto"] == round(69.71 - 17.43 + 16.76, 2)
    assert m0["grundpreis"] == 69.71 and m0["optionen"] == 16.76 and m0["rabatt"] == -17.43
    assert m0["data_contracted_gb"] == 80.0 and m0["data_used_gb"] == 8.0
    assert m0["auslastung_pct"] == 10.0
    assert "DataPlus 12 GB" in m0["optionen_namen"]
    assert v[1]["auslastung_pct"] == 50.0


def test_linie_verlauf_leer_wenn_rufnummer_fehlt():
    lines = [_iline("2026-06-01", "0170 999", "grundpreis", 50.0, "Flat S")]
    assert analytics.linie_verlauf(lines, "0151-1") == []


def _m(period, netto, rabatt=0.0, pct=None, opt=None):
    return {"period": period, "netto": netto, "grundpreis": netto, "optionen": 0.0,
            "rabatt": rabatt, "auslastung_pct": pct, "optionen_namen": opt or []}


def test_auffaelligkeiten_kostensprung():
    verlauf = [_m("2026-05-01", 68.0), _m("2026-06-01", 95.0)]  # +27 = 40%
    a = analytics.linie_auffaelligkeiten(verlauf)
    ks = [x for x in a if x["typ"] == "kostensprung"]
    assert len(ks) == 1 and ks[0]["period"] == "2026-06-01" and ks[0]["delta_eur"] == 27.0


def test_auffaelligkeiten_kleiner_sprung_ignoriert():
    verlauf = [_m("2026-05-01", 68.0), _m("2026-06-01", 74.0)]  # +6 < 10 EUR
    assert [x for x in analytics.linie_auffaelligkeiten(verlauf) if x["typ"] == "kostensprung"] == []


def test_auffaelligkeiten_rabatt_verloren():
    verlauf = [_m("2026-05-01", 68.0, rabatt=-17.0), _m("2026-06-01", 85.0, rabatt=0.0)]
    typen = {x["typ"] for x in analytics.linie_auffaelligkeiten(verlauf)}
    assert "rabatt_weg" in typen


def test_auffaelligkeiten_overage_je_monat():
    verlauf = [_m("2026-05-01", 68.0, pct=120.0)]
    ov = [x for x in analytics.linie_auffaelligkeiten(verlauf) if x["typ"] == "overage"]
    assert len(ov) == 1 and ov[0]["period"] == "2026-05-01"


def test_auffaelligkeiten_option_hinzu_und_weg():
    verlauf = [_m("2026-05-01", 68.0, opt=["DataPlus 12 GB"]),
               _m("2026-06-01", 90.0, opt=["Travel Mobil"])]
    typen = {(x["typ"], x.get("text")) for x in analytics.linie_auffaelligkeiten(verlauf)}
    assert any(t == "option_neu" and "Travel Mobil" in (txt or "") for t, txt in typen)
    assert any(t == "option_weg" and "DataPlus 12 GB" in (txt or "") for t, txt in typen)


def test_auffaelligkeiten_leer_bei_einem_ruhigen_monat():
    assert analytics.linie_auffaelligkeiten([_m("2026-06-01", 69.0, rabatt=-17.0, pct=40.0)]) == []
