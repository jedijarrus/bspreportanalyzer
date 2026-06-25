"""Tests für app.api — Auth, Upload-Sicherheit, Verwaltung, Auswertungen."""
import pytest
from fastapi.testclient import TestClient

from app import config, store
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
def client(app_store, make_report):
    """Authentifizierter Client (Passwort gesetzt + eingeloggt)."""
    app, s = app_store
    c = TestClient(app)
    c.post("/api/auth/setup", json={"password": PW})
    c._make_report = make_report
    return c


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
def test_status_initial_unkonfiguriert(app_store):
    app, _ = app_store
    c = TestClient(app)
    st = c.get("/api/auth/status").json()
    assert st["configured"] is False and st["authenticated"] is False


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
