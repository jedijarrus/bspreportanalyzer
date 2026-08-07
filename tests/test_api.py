"""Tests für app.api — Auth, Upload-Sicherheit, Verwaltung, Auswertungen."""
import pytest
from fastapi.testclient import TestClient

from app import azure_verify, config, store
from app.api import create_app, get_store

PW = "geheim-test-123"


@pytest.fixture
def app_store(tmp_path, monkeypatch):
    # Uploads in tmp lenken (keine Test-Pollution in data/uploads)
    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path / "uploads")
    s = store.Store(tmp_path / "api.db")
    app = create_app(secret_key="test-secret")
    app.dependency_overrides[get_store] = lambda: s
    yield app, s
    s.close()


@pytest.fixture
def client(app_store, make_report, make_invoice_csv):
    """Authentifizierter Client (Passwort gesetzt + eingeloggt)."""
    app, s = app_store
    c = TestClient(app)
    c.post("/api/auth/setup", json={"password": PW})
    c._make_report = make_report
    c._make_invoice_csv = make_invoice_csv
    return c


@pytest.fixture
def azure_app(tmp_path, monkeypatch):
    """App mit konfiguriertem Azure-SSO (GRAPH_*-ENV gesetzt)."""
    monkeypatch.setenv("GRAPH_TENANT_ID", "tenant-x")
    monkeypatch.setenv("GRAPH_CLIENT_ID", "client-x")
    monkeypatch.setenv("GRAPH_CLIENT_SECRET", "secret-x")
    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path / "uploads")
    s = store.Store(tmp_path / "az.db")
    app = create_app(secret_key="test-secret")
    app.dependency_overrides[get_store] = lambda: s
    yield app, s
    s.close()


def test_status_sso_flag(azure_app):
    st = TestClient(azure_app[0]).get("/api/auth/status").json()
    assert st["sso"] is True and st["configured"] is True


def test_password_login_deaktiviert_bei_sso(azure_app):
    c = TestClient(azure_app[0])
    assert c.post("/api/auth/setup", json={"password": "geheim-123"}).status_code == 403
    assert c.post("/api/auth/login", json={"password": "geheim-123"}).status_code == 403


def test_azure_login_404_ohne_sso(app_store):
    assert TestClient(app_store[0]).get("/api/auth/azure/login").status_code == 404


def test_azure_verify_setzt_session(azure_app, monkeypatch):
    app = azure_app[0]
    monkeypatch.setattr(azure_verify, "validate_token", lambda tok, ten, cid: {"name": "Test", "tid": ten})
    c = TestClient(app)
    assert c.post("/api/auth/azure/verify", json={"token": "x"}).status_code == 200
    assert c.get("/api/reports").status_code == 200   # Session gesetzt


def test_azure_verify_ungueltiges_token_401(azure_app, monkeypatch):
    def boom(*a):
        raise ValueError("bad")
    monkeypatch.setattr(azure_verify, "validate_token", boom)
    assert TestClient(azure_app[0]).post("/api/auth/azure/verify", json={"token": "x"}).status_code == 401


def test_validate_token_roundtrip(monkeypatch):
    import time as _t
    from authlib.jose import JsonWebKey, jwt
    key = JsonWebKey.generate_key("RSA", 2048, options={"kid": "k1"}, is_private=True)
    keyset = JsonWebKey.import_key_set({"keys": [key.as_dict(is_private=False)]})
    monkeypatch.setattr(azure_verify, "_jwks", lambda tenant: keyset)
    tenant, cid = "tenant-x", "client-x"

    def mk(tid):
        return jwt.encode({"alg": "RS256", "kid": "k1"},
                          {"iss": f"https://login.microsoftonline.com/{tenant}/v2.0", "aud": cid,
                           "tid": tid, "exp": int(_t.time()) + 3600, "name": "Test"}, key).decode()

    assert azure_verify.validate_token(mk(tenant), tenant, cid)["name"] == "Test"
    with pytest.raises(Exception):                      # falscher Tenant -> abgelehnt
        azure_verify.validate_token(mk("anders"), tenant, cid)


def test_azure_callback_setzt_session(azure_app):
    app = azure_app[0]

    class _Azure:
        async def authorize_access_token(self, request):
            return {"userinfo": {"name": "Test Nutzer", "email": "t@firma.de"}}

    class _OAuth:
        azure = _Azure()

    app.state.oauth = _OAuth()   # echten OIDC-Client durch Mock ersetzen
    c = TestClient(app)
    r = c.get("/api/auth/azure/callback", follow_redirects=False)
    assert r.status_code == 303
    assert c.get("/api/reports").status_code == 200   # Session gesetzt -> Zugriff frei


def _upload_invoice(client, rufnummern=None, n=3, invoice_number="230000000001", period=None):
    kw = {"rufnummern": rufnummern, "n": n, "invoice_number": invoice_number}
    if period:
        kw["period"] = period
    path = client._make_invoice_csv(**kw)
    with open(path, "rb") as f:
        return client.post("/api/invoices",
                           files={"file": (path.name, f.read(), "text/csv")})


def _upload(client, rows=10, seed=0, name=None):
    path = client._make_report(rows=rows, seed=seed)  # immer sicherer Dateiname
    send_name = name or path.name  # bösartiger Name nur als Multipart-Filename
    with open(path, "rb") as f:
        return client.post(
            "/api/reports",
            files={"file": (send_name, f.read(),
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )


# ---- Auth ----------------------------------------------------------------
def test_version_endpoint(app_store):
    v = TestClient(app_store[0]).get("/api/version").json()
    assert "sha" in v and "built" in v   # ohne Docker-Build: Default "dev"


def test_status_initial_unkonfiguriert(app_store):
    app, _ = app_store
    c = TestClient(app)
    st = c.get("/api/auth/status").json()
    assert st["configured"] is False and st["authenticated"] is False
    assert st["user"] is None   # Name-Feld vorhanden, ohne Login leer


def test_setup_konfiguriert_und_loggt_ein(app_store):
    app, _ = app_store
    c = TestClient(app)
    assert c.post("/api/auth/setup", json={"password": PW}).status_code == 201
    st = c.get("/api/auth/status").json()
    assert st["configured"] and st["authenticated"]


def test_setup_zu_kurz_abgelehnt(app_store):
    app, _ = app_store
    c = TestClient(app)
    assert c.post("/api/auth/setup", json={"password": "kurz"}).status_code == 400


def test_setup_zweimal_konflikt(app_store):
    app, _ = app_store
    c = TestClient(app)
    c.post("/api/auth/setup", json={"password": PW})
    assert c.post("/api/auth/setup", json={"password": "anderes123"}).status_code == 409


def test_login_rate_limit(app_store):
    app, _ = app_store
    TestClient(app).post("/api/auth/setup", json={"password": PW})
    c = TestClient(app)  # frische Session
    for _ in range(5):
        assert c.post("/api/auth/login", json={"password": "falsch-123"}).status_code == 401
    assert c.post("/api/auth/login", json={"password": "falsch-123"}).status_code == 429  # gesperrt
    assert c.post("/api/auth/login", json={"password": PW}).status_code == 429             # auch korrekt gesperrt


def test_datenendpunkt_braucht_login(app_store):
    app, _ = app_store
    setup = TestClient(app)
    setup.post("/api/auth/setup", json={"password": PW})
    anon = TestClient(app)  # konfiguriert, aber frische Session
    assert anon.get("/api/reports").status_code == 401


def test_login_falsches_passwort(app_store):
    app, _ = app_store
    TestClient(app).post("/api/auth/setup", json={"password": PW})
    anon = TestClient(app)
    assert anon.post("/api/auth/login", json={"password": "falsch"}).status_code == 401


def test_login_korrekt_gibt_zugriff(app_store):
    app, _ = app_store
    TestClient(app).post("/api/auth/setup", json={"password": PW})
    anon = TestClient(app)
    assert anon.post("/api/auth/login", json={"password": PW}).status_code == 200
    assert anon.get("/api/reports").status_code == 200


def test_logout_entzieht_zugriff(client):
    assert client.get("/api/reports").status_code == 200
    client.post("/api/auth/logout")
    assert client.get("/api/reports").status_code == 401


# ---- Upload-Sicherheit ---------------------------------------------------
def test_upload_path_traversal_wird_entschaerft(client, tmp_path):
    r = _upload(client, rows=2, name="../../../evil.xlsx")
    assert r.status_code == 201
    # Datei nur als Basename im Upload-Ordner, nichts ausserhalb
    assert (tmp_path / "uploads" / "evil.xlsx").exists()
    assert not (tmp_path.parent / "evil.xlsx").exists()


def test_upload_zu_gross_abgelehnt(client, monkeypatch):
    monkeypatch.setattr(config, "MAX_UPLOAD_BYTES", 1000)  # 1 KB
    r = _upload(client, rows=50)  # generierte xlsx > 1 KB
    assert r.status_code == 413


def test_upload_nicht_xlsx_abgelehnt(client):
    r = client.post("/api/reports",
                    files={"file": ("x.txt", b"hallo", "text/plain")})
    assert r.status_code == 400


# ---- Report-Verwaltung + Auswertungen ------------------------------------
def test_dashboard_laedt(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_upload_legt_report_an(client):
    r = _upload(client, rows=8)
    assert r.status_code == 201
    assert r.json()["row_count"] == 8


def test_reports_liste(client):
    _upload(client, rows=5)
    r = client.get("/api/reports")
    assert len(r.json()) == 1
    assert r.json()[0]["row_count"] == 5


def test_report_loeschen(client):
    rid = _upload(client, rows=5).json()["report_id"]
    assert client.delete(f"/api/reports/{rid}").status_code == 204
    assert client.get("/api/reports").json() == []


def test_current_aktuelle_flotte(client):
    _upload(client, rows=5, seed=1)
    _upload(client, rows=7, seed=2)
    body = client.get("/api/current").json()
    assert "stand" in body and "rahmenvertraege" in body
    assert len(body["contracts"]) == 12  # synthetische RVs je Zeile unterschiedlich


def test_current_enthaelt_frische_felder(client):
    _upload(client, rows=5, seed=1)
    body = client.get("/api/current").json()
    assert body["max_age_tage"] == 14
    assert isinstance(body["stale"], bool)
    assert isinstance(body["frische"], dict) and body["frische"]  # je RV ein Eintrag
    any_rv = next(iter(body["frische"].values()))
    assert set(any_rv) == {"report_date", "alter_tage", "stale"}


def test_current_alter_report_wird_als_veraltet_markiert(client):
    # Report-Datum weit in der Vergangenheit (aus Dateiname) -> veraltet
    _upload(client, rows=5, seed=1, name="20200101-000000_RVKU-KI_000001_1.xlsx")
    body = client.get("/api/current").json()
    assert body["stale"] is True
    assert body["stand_alter_tage"] > 14


def test_report_upload_dedup(client):
    r1 = _upload(client, rows=4, seed=1, name="20260701-000000_RVKU-KI_dup.xlsx")
    assert r1.json()["duplicate"] is False
    r2 = _upload(client, rows=4, seed=1, name="20260701-000000_RVKU-KI_dup.xlsx")  # gleiche Datei
    assert r2.json()["duplicate"] is True
    assert len(client.get("/api/reports").json()) == 1  # nicht doppelt


def test_notes_setzen_und_lesen(client):
    assert client.post("/api/notes", json={"key": "RV-A|0151", "note": "VVL prüfen"}).status_code == 200
    assert client.get("/api/notes").json()["RV-A|0151"] == "VVL prüfen"


def test_notes_leer_loescht(client):
    client.post("/api/notes", json={"key": "k", "note": "x"})
    client.post("/api/notes", json={"key": "k", "note": ""})
    assert "k" not in client.get("/api/notes").json()


def test_notes_braucht_login(app_store):
    app, _ = app_store
    TestClient(app).post("/api/auth/setup", json={"password": PW})
    assert TestClient(app).get("/api/notes").status_code == 401


# ---- Rechnungen / Kosten -------------------------------------------------
def test_invoice_upload(client):
    r = _upload_invoice(client, rufnummern=["0151A", "0151B"])
    assert r.status_code == 201
    assert r.json()["line_count"] > 0


def test_invoice_upload_nur_csv(client):
    # weder .txt noch .xml werden akzeptiert - nur Telekom-CSV
    assert client.post("/api/invoices",
                       files={"file": ("x.txt", b"hallo", "text/plain")}).status_code == 400
    assert client.post("/api/invoices",
                       files={"file": ("x.xml", b"<Invoice/>", "application/xml")}).status_code == 400


def test_invoice_upload_dedup(client):
    r1 = _upload_invoice(client, rufnummern=["0151A"], invoice_number="777")
    assert r1.status_code == 201 and r1.json()["duplicate"] is False
    r2 = _upload_invoice(client, rufnummern=["0151A"], invoice_number="777")  # gleiche Rechnungsnr
    assert r2.status_code == 201 and r2.json()["duplicate"] is True
    assert len(client.get("/api/invoices").json()) == 1  # nicht doppelt gespeichert


def test_invoice_upload_defekt_abgelehnt(client):
    # CSV ohne Telekom-Kopfzeile -> 400, nicht als leere Rechnung importiert
    r = client.post("/api/invoices", files={"file": ("kaputt.csv", b"a;b;c\n1;2;3\n", "text/csv")})
    assert r.status_code == 400
    assert client.get("/api/invoices").json() == []


def test_invoices_liste(client):
    _upload_invoice(client, rufnummern=["0151A"])
    assert len(client.get("/api/invoices").json()) == 1


def test_invoice_loeschen(client):
    iid = _upload_invoice(client, rufnummern=["0151A"]).json()["invoice_id"]
    assert client.delete(f"/api/invoices/{iid}").status_code == 204
    assert client.get("/api/invoices").json() == []


def test_costs_kostenstellen(client):
    _upload_invoice(client, rufnummern=["0151A", "0151B", "0151C"])
    r = client.get("/api/costs/kostenstellen")
    assert r.status_code == 200 and len(r.json()) >= 1


def test_costs_trend(client):
    _upload_invoice(client, rufnummern=["0151A"], invoice_number="1")
    r = client.get("/api/costs/trend")
    assert r.status_code == 200 and len(r.json()) >= 1


def test_current_reichert_kosten_an(client):
    _upload(client, rows=3)
    ruf = client.get("/api/current").json()["contracts"][0]["rufnummer"]
    _upload_invoice(client, rufnummern=[ruf])
    body = client.get("/api/current").json()
    assert "netto_factor" in body
    c = [x for x in body["contracts"] if x["rufnummer"] == ruf][0]
    assert c["_kosten_netto"] is not None and c["_kosten_netto"] != 0


def test_invoice_detail(client):
    iid = _upload_invoice(client, rufnummern=["0151A", "0151B"], invoice_number="1").json()["invoice_id"]
    body = client.get(f"/api/invoices/{iid}").json()
    assert body["invoice"]["total_net"] > 0
    assert "kategorie" in body and "kostenstelle" in body
    assert "reconcile" in body and "datenauslastung" in body
    assert body["diff"] is None  # keine Vorrechnung
    # Positionen je Kategorie aufgeschlüsselt (Name + Anzahl + Summe)
    pos = body["positionen"]
    assert pos and all({"category", "summe", "anzahl", "positionen"} <= set(c) for c in pos)
    grund = [c for c in pos if c["category"] == "grundpreis"][0]
    assert grund["positionen"][0]["anzahl"] >= 1 and "name" in grund["positionen"][0]


def test_invoice_detail_diff_vs_vormonat(client):
    _upload_invoice(client, rufnummern=["0151A"], invoice_number="1", period=("2026-05-01", "2026-05-31"))
    iid2 = _upload_invoice(client, rufnummern=["0151A"], invoice_number="2", period=("2026-06-01", "2026-06-30")).json()["invoice_id"]
    body = client.get(f"/api/invoices/{iid2}").json()
    assert body["diff"] is not None
    assert "gesamt" in body["diff"]


def test_costs_kostenstellen_je_invoice(client):
    iid = _upload_invoice(client, rufnummern=["0151A", "0151B"], invoice_number="1").json()["invoice_id"]
    r = client.get(f"/api/costs/kostenstellen?invoice_id={iid}")
    assert r.status_code == 200 and len(r.json()) >= 1


def test_linie_monitoring_verlauf_und_stammdaten(client):
    _upload(client, rows=3)
    ruf = client.get("/api/current").json()["contracts"][0]["rufnummer"]
    _upload_invoice(client, rufnummern=[ruf], invoice_number="1", period=("2026-05-01", "2026-05-31"))
    _upload_invoice(client, rufnummern=[ruf], invoice_number="2", period=("2026-06-01", "2026-06-30"))
    body = client.get(f"/api/linie/{ruf}").json()
    assert len(body["verlauf"]) == 2                      # zwei Monate
    assert body["verlauf"][0]["period"] <= body["verlauf"][1]["period"]
    assert body["stammdaten"] is not None                 # Report-Stammdaten gejoint
    assert "auffaelligkeiten" in body


def test_linie_monitoring_unbekannt_404(client):
    assert client.get("/api/linie/0000000000").status_code == 404


def test_linie_braucht_login(app_store):
    app, _ = app_store
    TestClient(app).post("/api/auth/setup", json={"password": PW})
    assert TestClient(app).get("/api/linie/0151").status_code == 401


def test_csv_upload_und_auslastung_pro_vertrag(client):
    _upload(client, rows=3)
    ruf = client.get("/api/current").json()["contracts"][0]["rufnummer"]
    path = client._make_invoice_csv(rufnummern=[ruf])
    with open(path, "rb") as f:
        r = client.post("/api/invoices", files={"file": (path.name, f.read(), "text/csv")})
    assert r.status_code == 201
    c = [x for x in client.get("/api/current").json()["contracts"] if x["rufnummer"] == ruf][0]
    assert c["_auslastung_pct"] is not None       # <- CSV schaltet Auslastung pro Vertrag frei
    assert c["_data_contracted_gb"] and c["_data_used_gb"] is not None


def test_costs_braucht_login(app_store):
    app, _ = app_store
    TestClient(app).post("/api/auth/setup", json={"password": PW})
    assert TestClient(app).get("/api/costs/trend").status_code == 401


def test_current_braucht_login(app_store):
    app, _ = app_store
    TestClient(app).post("/api/auth/setup", json={"password": PW})
    anon = TestClient(app)
    assert anon.get("/api/current").status_code == 401


def test_vvl_auswertung(client):
    rid = _upload(client, rows=20).json()["report_id"]
    body = client.get(f"/api/reports/{rid}/vvl").json()
    assert "buckets" in body and "expiring" in body


def test_inventory_auswertung(client):
    rid = _upload(client, rows=15).json()["report_id"]
    assert client.get(f"/api/reports/{rid}/inventory").json()["total"] == 15


def test_tarife_auswertung(client):
    rid = _upload(client, rows=15).json()["report_id"]
    body = client.get(f"/api/reports/{rid}/tarife").json()
    assert "tarif" in body and "daten_optionen" in body


def test_diff_zwei_reports(client):
    r1 = _upload(client, rows=5, seed=1).json()["report_id"]
    r2 = _upload(client, rows=5, seed=2).json()["report_id"]
    body = client.get(f"/api/diff?old={r1}&new={r2}").json()
    assert "hinzugefuegt" in body and "entfernt" in body and "geaendert" in body


def test_trend_ueber_reports(client):
    _upload(client, rows=5, seed=1)
    _upload(client, rows=8, seed=2)
    assert len(client.get("/api/trend").json()) == 2
