"""GLPI-Abgleich: Vergleichslogik (analytics.glpi_abgleich), der GLPI-Client gegen
nachgestellte Antworten (httpx.MockTransport) und die Endpunkte /api/glpi*.

Rufnummern stehen im Format 0190 / 49190 — keine Mobilnummern, der Sanitizer bleibt still.
"""
import json
import re
import urllib.parse

import httpx
import pytest
from fastapi.testclient import TestClient

from app import analytics, config, glpi_client, store
from app.api import GLPI_SNAPSHOT_KEY, create_app, get_store

PW = "geheim-test-123"
GLPI_ENV = {"GLPI_URL": "https://glpi.example.com/api.php", "GLPI_CLIENT_ID": "cid-1",
            "GLPI_CLIENT_SECRET": "client-secret-xyz", "GLPI_USERNAME": "leser", "GLPI_PASSWORD": "pw-sehr-geheim"}
USERS = {"7": {"realname": "Muster", "firstname": "Max", "username": "mmuster"},
         "8": {"realname": "Andere", "firstname": "Anna", "username": "aandere"}}


def card(n: int) -> str:
    """Telekom-Kartennummer wie im Report: 20 Ziffern, Zusatz hinter dem Backslash."""
    return f"8-94902-00001-2345678{n}-0\\123"


def tail(n: int) -> str:
    """Dieselbe Karte, wie GLPI sie meist führt: die letzten 14 Ziffern."""
    return f"00001-2345678{n}-0"


def contract(nr, nutzer="Muster, Max", rid=2, date="2026-08-05", kst="1001", **extra):
    return {"rahmenvertrag": "RV1", "_report_id": rid, "_report_date": date, "rufnummer": nr,
            "kostenstellennutzer": nutzer, "kostenstelle": kst, "tarif": "Tarif A", **extra}


def line(id_, nr, user_id=None, deleted=False):
    return {"id": id_, "nr": nr, "user_id": user_id, "deleted": deleted}


def sim(id_, serial, line_id=None, user_id=None, deleted=False, model="Hauptkarte"):
    return {"id": id_, "serial": serial, "model": model, "line_id": line_id, "user_id": user_id,
            "itemtype": None, "items_id": None, "deleted": deleted}


def snap(lines=(), sims=(), users=None):
    return {"fetched_at": "2026-11-11T12:00:00", "lines": list(lines), "sims": list(sims), "users": users or USERS}


# ---- Vergleichslogik ------------------------------------------------------
def test_rufnummern_in_beiden_nur_telekom_nur_glpi():
    res = analytics.glpi_abgleich(
        [contract("4919011111111"), contract("4919022222222")],
        snap([line(1, "0190-11111111", 7), line(2, "0190-33333333", 8), line(3, "0190-22222222", 7, deleted=True)]))
    assert [x["rufnummer"] for x in res["nummer_nur_telekom"]] == ["4919022222222"]   # die GLPI-Leitung ist gelöscht
    assert res["nummer_nur_glpi"] == [{"rufnummer": "0190-33333333", "glpi_benutzer": "Andere, Anna", "line_id": 2}]
    assert (res["n_vertraege"], res["n_leitungen"], res["n_beide"]) == (2, 2, 1)


def test_es_zaehlt_die_aktuelle_flotte():
    """Eine Nummer, die nur im älteren Report des Rahmenvertrags steht, ist gekündigt."""
    alt = contract("4919044444444", rid=1, date="2026-07-01")
    res = analytics.glpi_abgleich([alt, contract("4919011111111")],
                                  snap([line(1, "0190-11111111", 7), line(4, "0190-44444444", 7)]))
    assert [x["rufnummer"] for x in res["nummer_nur_glpi"]] == ["0190-44444444"]
    assert res["n_vertraege"] == 1


def test_anderer_benutzer_ohne_benutzer_und_pool():
    contracts = [contract("4919011111111"),                       # gleiche Person
                 contract("4919022222222"),                       # GLPI: andere Person
                 contract("4919033333333"),                       # GLPI: kein Benutzer
                 contract("4919055555555", kst="9000"),           # Pool-Kostenstelle
                 contract("4919066666666", nutzer="Pool"),        # Pool-Nutzer
                 contract("4919077777777", nutzer="")]            # kein Nutzer im Report
    lines = [line(1, "0190-11111111", 7), line(2, "0190-22222222", 8), line(3, "0190-33333333"),
             line(5, "0190-55555555", 8), line(6, "0190-66666666", 8), line(7, "0190-77777777", 8)]
    res = analytics.glpi_abgleich(contracts, snap(lines))
    assert res["benutzer_abweichend"] == [
        {"rufnummer": "4919022222222", "nutzer_telekom": "Muster, Max", "nutzer_glpi": "Andere, Anna", "art": "andere Person",
         "line_id": 2},
        {"rufnummer": "4919033333333", "nutzer_telekom": "Muster, Max", "nutzer_glpi": None, "art": "kein Benutzer", "line_id": 3}]


def test_schreibweise_steht_hinter_anderer_person():
    contracts = [contract("4919011111111", nutzer="Brandtner, Torben"), contract("4919022222222", nutzer="Oswald, Henrik")]
    users = {"1": {"realname": "Brandtner", "firstname": "Torbin"}, "2": {"realname": "Faber", "firstname": "Konstantin"}}
    res = analytics.glpi_abgleich(contracts, snap([line(1, "0190-11111111", 1), line(2, "0190-22222222", 2)], users=users))
    assert [(b["rufnummer"], b["art"]) for b in res["benutzer_abweichend"]] == [
        ("4919022222222", "andere Person"), ("4919011111111", "Schreibweise")]


@pytest.mark.parametrize("telekom, user, art", [
    ("Arnaud, Zoé", {"realname": "Arnaud", "firstname": "Zoe"}, None),
    ("Hagemeier, Lorik", {"realname": "Hakemeier", "firstname": "Lorik"}, "Schreibweise"),
    ("Hollerbach, Lia-Mae", {"realname": "Hollerbach", "firstname": "Lia-Mea Johanna"}, "Schreibweise"),
    ("Mueller, Hans", {"realname": "Meyer", "firstname": "Hans"}, "andere Person"),
    ("Becker, Jonas", {"realname": "Becker", "firstname": "Lena"}, "andere Person"),
    ("Becker, Jonas", None, "kein Benutzer"),
])
def test_name_mismatch(telekom, user, art):
    assert analytics.name_mismatch(telekom, user) == art


@pytest.mark.parametrize("telekom, user, same", [
    ("Müller, Jürgen", {"realname": "Mueller", "firstname": "Juergen"}, True),
    ("Müller, Andre", {"realname": "Müller", "firstname": "André"}, True),
    ("Mueller, Juergen", {"realname": "Müller", "firstname": "Jürgen"}, True),
    ("Krause-Wendt, Ute", {"realname": "Krause-Wendt", "firstname": "Ute"}, True),
    ("Schulz, Eva Maria", {"realname": "Schulz", "firstname": "Eva"}, True),
    ("Schulz, Eva", {"realname": "", "firstname": "", "username": "eva.schulz@example.com"}, True),
    ("Schulz, Eva", {"realname": "Schulz", "firstname": "Tom"}, False),
    ("Schulz, Eva", None, False),
    ("", {"realname": "Schulz", "firstname": "Eva"}, False),
])
def test_same_person(telekom, user, same):
    assert analytics.same_person(telekom, user) is same


def test_sim_karten_alle_faelle():
    c1 = contract("4919011111111", karten_profilnummer=card(1), multisim_karten_profilnummer_1=card(2))
    c2 = contract("4919022222222", karten_profilnummer=card(3))
    c3 = contract("4919033333333", karten_profilnummer=card(4), multisim_karten_profilnummer_2=card(5))
    lines = [line(1, "0190-11111111", 7), line(2, "0190-22222222", 7), line(3, "0190-33333333", 7)]
    sims = [
        sim(10, tail(1), line_id=1),                       # richtig
        sim(11, tail(2), user_id=7, model="MultiSIM 1"),   # bekannt, ohne Leitung
        sim(12, tail(3), line_id=1),                       # an der falschen Leitung
        sim(13, "8949020000123456784-0", line_id=3),       # ganze Nummer, richtig
        sim(14, "0001-23456785-0", line_id=3),             # eine Null weniger, richtig
        sim(18, "000001-23456784-0", line_id=3),           # eine Null mehr, richtig
        sim(15, "7", user_id=8),                           # unlesbar
        sim(16, "99999-99999999-9", line_id=2),            # keine Telekom-Karte
        sim(17, tail(1), line_id=2, deleted=True),         # gelöscht: zählt nicht
    ]
    res = analytics.glpi_abgleich([c1, c2, c3], snap(lines, sims))
    assert res["sim_fehlt_in_glpi"] == []
    assert [(s["sim_id"], s["telekom_rufnummer"], s["art"], s["glpi_benutzer"]) for s in res["sim_ohne_leitung"]] == [
        (11, "4919011111111", "MultiSIM 1", "Muster, Max")]
    assert [(s["sim_id"], s["telekom_rufnummer"], s["glpi_rufnummer"]) for s in res["sim_falsche_leitung"]] == [
        (12, "4919022222222", "0190-11111111")]
    assert [(s["sim_id"], s["unlesbar"]) for s in res["sim_nur_glpi"]] == [(16, False), (15, True)]
    assert (res["n_karten_telekom"], res["n_karten_glpi"], res["n_karten_beide"]) == (5, 8, 5)


def test_sim_fehlt_in_glpi_nennt_art_und_nummer():
    c = contract("4919011111111", karten_profilnummer=card(1), multisim_karten_profilnummer_3=card(6))
    res = analytics.glpi_abgleich([c], snap([line(1, "0190-11111111", 7)], [sim(10, tail(1), line_id=1)]))
    assert res["sim_fehlt_in_glpi"] == [{"karte": card(6), "art": "MultiSIM 3", "rufnummer": "4919011111111",
                                         "nutzer": "Muster, Max"}]


def test_card_digits_ohne_zusatz():
    assert analytics.card_digits(card(1)) == "89490200001234567810"
    assert analytics.card_digits(None) == ""


def test_leerer_snapshot():
    res = analytics.glpi_abgleich([contract("4919011111111")], {"fetched_at": "x"})
    assert len(res["nummer_nur_telekom"]) == 1 and res["n_leitungen"] == 0


# ---- GLPI-Client ------------------------------------------------------------
def settings():
    return {"url": "https://glpi.example.com/api.php", "client_id": "cid-1", "client_secret": "client-secret-xyz",
            "username": "leser", "password": "pw-sehr-geheim"}


RAW_LINES = [{"id": i, "caller_num": f"0190-1000000{i}", "name": f"0190-1000000{i}", "user": {"id": 7, "username": "mmuster"},
              "is_deleted": False} for i in range(1, 6)]
RAW_SIMS = [{"id": 20 + i, "serial": tail(i), "sim_card": {"id": 1, "designation": "Hauptkarte"}, "line": {"id": i, "name": "x"},
             "user": {"id": 7, "username": "mmuster"}, "itemtype": "Phone", "items_id": 3, "is_deleted": False,
             "pin": "1234", "pin2": "5678", "puk": "87654321", "puk2": "12345678"} for i in range(1, 4)]
RAW_USERS = [{"id": 7, "username": "mmuster", "realname": "Muster", "firstname": "Max", "mobile": "0190-5550001"},
             {"id": 9, "username": "nobody", "realname": "Niemand", "firstname": "Nina", "mobile": "0190-5550002"}]


def glpi_mock(calls, token_status=200, token_body=None, lists=None):
    data = {"/api.php/v3.0/Management/Line": RAW_LINES,
            "/api.php/v3.0/Components/SIMCard": [{"id": 1, "designation": "Hauptkarte"}, {"id": 2, "designation": "MultiSIM 1"}],
            "/api.php/v3.0/Components/SIMCard/1/Items": RAW_SIMS,
            "/api.php/v3.0/Components/SIMCard/2/Items": RAW_SIMS,    # manche GLPI-Versionen: jedes Modell liefert alle Karten
            "/api.php/v3.0/Administration/User": RAW_USERS, **(lists or {})}

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        if req.url.path == "/api.php/token":
            form = dict(urllib.parse.parse_qsl(req.content.decode()))
            assert form == {"grant_type": "password", "client_id": "cid-1", "client_secret": "client-secret-xyz",
                            "username": "leser", "password": "pw-sehr-geheim", "scope": "api"}
            return httpx.Response(token_status, json=token_body if token_body is not None else {"access_token": "tok-1"})
        assert req.headers["Authorization"] == "Bearer tok-1"
        rows = data[req.url.path]
        if not isinstance(rows, list):
            return rows
        start, limit = int(req.url.params["start"]), int(req.url.params["limit"])
        page = rows[start:start + limit]
        return httpx.Response(200, json=page, headers={"Content-Range": f"{start}-{start + len(page) - 1}/{len(rows)}"})
    return httpx.MockTransport(handler)


def test_snapshot_mit_paginierung_entdoppelt_und_ohne_pin_puk(monkeypatch):
    monkeypatch.setattr(glpi_client, "PAGE_SIZE", 2)
    calls = []
    s = glpi_client.fetch_snapshot(settings(), transport=glpi_mock(calls))
    assert [ln["id"] for ln in s["lines"]] == [1, 2, 3, 4, 5]
    assert len([c for c in calls if c.url.path.endswith("/Management/Line")]) == 3          # 2 + 2 + 1
    assert sorted(x["id"] for x in s["sims"]) == [21, 22, 23]                               # nach id entdoppelt
    assert s["sims"][0] == {"id": 21, "serial": tail(1), "model": "Hauptkarte", "line_id": 1, "user_id": 7,
                            "itemtype": "Phone", "items_id": 3, "deleted": False}
    dumped = json.dumps(s)
    assert "87654321" not in dumped and "pin" not in dumped and "puk" not in dumped
    assert s["users"] == {"7": {"realname": "Muster", "firstname": "Max", "username": "mmuster"}}   # nur zugeordnete
    assert "0190-5550001" not in dumped


@pytest.mark.parametrize("status, body, want", [
    (401, {"error": "invalid_client"}, "Anmeldung bei GLPI fehlgeschlagen (HTTP 401, invalid_client)"),
    (400, {"error": "invalid_grant", "error_description": "pw-sehr-geheim"}, "Anmeldung bei GLPI fehlgeschlagen (HTTP 400, invalid_grant)"),
    (200, {"token_type": "Bearer"}, "Anmeldung bei GLPI fehlgeschlagen (keine gültige Token-Antwort)"),
])
def test_anmeldung_fehlgeschlagen_ohne_geheimnisse(status, body, want):
    with pytest.raises(glpi_client.GlpiError) as e:
        glpi_client.fetch_snapshot(settings(), transport=glpi_mock([], token_status=status, token_body=body))
    assert str(e.value) == want
    assert "client-secret-xyz" not in str(e.value) and "pw-sehr-geheim" not in str(e.value)


def test_glpi_nicht_erreichbar():
    def boom(req):
        raise httpx.ConnectError("refused", request=req)
    with pytest.raises(glpi_client.GlpiError, match="GLPI nicht erreichbar"):
        glpi_client.fetch_snapshot(settings(), transport=httpx.MockTransport(boom))


@pytest.mark.parametrize("answer, want", [
    (httpx.Response(403, json={"title": "Zugriff verweigert"}), "fehlgeschlagen (HTTP 403)"),
    (httpx.Response(200, json={"rows": []}), "unerwartete Antwort"),
    (httpx.Response(200, text="<html>"), "keine JSON-Antwort"),
])
def test_abruf_fehler(answer, want):
    with pytest.raises(glpi_client.GlpiError, match=re.escape(want)):
        glpi_client.fetch_snapshot(settings(), transport=glpi_mock([], lists={"/api.php/v3.0/Management/Line": answer}))


def test_unvollstaendig_eingerichtet():
    with pytest.raises(glpi_client.GlpiError, match="nicht vollständig"):
        glpi_client.fetch_snapshot({**settings(), "password": None})


# ---- Konfiguration -----------------------------------------------------------
def test_glpi_settings_und_fehlende_variablen(monkeypatch):
    assert config.glpi_missing() == list(config.GLPI_KEYS)
    for k, v in GLPI_ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("GLPI_URL", "https://glpi.example.com/api.php/v3.0/")
    assert config.glpi_missing() == []
    assert config.glpi_settings()["url"] == "https://glpi.example.com/api.php"
    assert config.glpi_web_base() == "https://glpi.example.com"


# ---- Endpunkte ----------------------------------------------------------------
@pytest.fixture
def app_store(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path / "uploads")
    s = store.Store(tmp_path / "api.db")
    app = create_app(secret_key="test-secret")
    app.dependency_overrides[get_store] = lambda: s
    yield app, s
    s.close()


@pytest.fixture
def client(app_store):
    app, _ = app_store
    c = TestClient(app)
    c.post("/api/auth/setup", json={"password": PW})
    return c


@pytest.fixture
def glpi_env(monkeypatch):
    for k, v in GLPI_ENV.items():
        monkeypatch.setenv(k, v)


def test_endpunkte_brauchen_anmeldung(app_store, glpi_env):
    c = TestClient(app_store[0])
    assert c.get("/api/glpi").status_code == 401
    assert c.post("/api/glpi/refresh").status_code == 401


def test_nicht_eingerichtet(client, monkeypatch):
    monkeypatch.setattr(glpi_client, "fetch_snapshot", lambda *a, **k: pytest.fail("darf GLPI nicht fragen"))
    assert client.get("/api/glpi").json() == {"configured": False, "missing": list(config.GLPI_KEYS)}
    r = client.post("/api/glpi/refresh")
    assert (r.status_code, r.json()["detail"]) == (400, "GLPI ist nicht eingerichtet.")


def test_eingerichtet_ohne_stand(client, glpi_env):
    assert client.get("/api/glpi").json() == {"configured": True, "glpi_web": "https://glpi.example.com",
                                              "report_stand": None, "stand": None}


def test_neu_laden_speichert_den_stand(client, app_store, glpi_env, monkeypatch):
    seen = {}

    def fake(settings_):
        seen.update(settings_)
        return snap([line(1, "0190-11111111", 7)], [sim(10, tail(1), line_id=1)])
    monkeypatch.setattr(glpi_client, "fetch_snapshot", fake)
    r = client.post("/api/glpi/refresh")
    assert r.status_code == 200 and r.json() == {"stand": "2026-11-11T12:00:00", "leitungen": 1, "sim_karten": 1}
    assert seen["url"] == "https://glpi.example.com/api.php" and seen["password"] == "pw-sehr-geheim"
    assert json.loads(app_store[1].get_setting(GLPI_SNAPSHOT_KEY))["lines"][0]["nr"] == "0190-11111111"
    d = client.get("/api/glpi").json()
    assert d["stand"] == "2026-11-11T12:00:00" and d["nummer_nur_glpi"][0]["rufnummer"] == "0190-11111111"
    assert d["sim_nur_glpi"][0]["sim_id"] == 10 and d["n_vertraege"] == 0


def test_neu_laden_fehler_kommt_als_502(client, glpi_env, monkeypatch):
    def fail(_):
        raise glpi_client.GlpiError("Anmeldung bei GLPI fehlgeschlagen (HTTP 401, invalid_client)")
    monkeypatch.setattr(glpi_client, "fetch_snapshot", fail)
    r = client.post("/api/glpi/refresh")
    assert (r.status_code, r.json()["detail"]) == (502, "Anmeldung bei GLPI fehlgeschlagen (HTTP 401, invalid_client)")
