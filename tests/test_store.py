"""Tests für app.store — SQLite-Persistenz der Reports + Contracts."""
import pytest

from app import parser, store


@pytest.fixture
def db(tmp_path):
    s = store.Store(tmp_path / "test.db")
    yield s
    s.close()


def test_leere_db_hat_keine_reports(db):
    assert db.list_reports() == []


def test_add_report_taucht_in_liste_auf(db, make_report):
    data = parser.parse_report(make_report(rows=5))
    db.add_report(data)
    reports = db.list_reports()
    assert len(reports) == 1
    assert reports[0]["row_count"] == 5
    assert reports[0]["filename"] == data.filename


def test_add_report_gibt_id_zurueck(db, make_report):
    data = parser.parse_report(make_report(rows=3))
    rid = db.add_report(data)
    assert isinstance(rid, int)


def test_report_date_wird_gespeichert(db, make_report):
    data = parser.parse_report(make_report(rows=3))
    rid = db.add_report(data)
    rep = db.list_reports()[0]
    assert rep["report_date"].startswith("2026-06-25")


def test_get_contracts_roundtrip(db, make_report):
    data = parser.parse_report(make_report(rows=4))
    rid = db.add_report(data)
    contracts = db.get_contracts(rid)
    assert len(contracts) == 4
    # Werte aus dem Parser müssen erhalten bleiben
    assert contracts[0]["rufnummer"] == data.rows[0]["rufnummer"]


def test_datetime_als_iso_gespeichert(db, make_report):
    data = parser.parse_report(make_report(rows=2))
    rid = db.add_report(data)
    c = db.get_contracts(rid)[0]
    # datetime wird als ISO-String persistiert
    assert isinstance(c["vertragsbeginn"], str)
    assert c["vertragsbeginn"].startswith(data.rows[0]["vertragsbeginn"].strftime("%Y-%m-%d"))


def test_zwei_reports_koexistieren(db, make_report):
    r1 = db.add_report(parser.parse_report(make_report(rows=3, seed=1)))
    r2 = db.add_report(parser.parse_report(make_report(rows=7, seed=2)))
    assert len(db.list_reports()) == 2
    assert len(db.get_contracts(r1)) == 3
    assert len(db.get_contracts(r2)) == 7


def test_delete_entfernt_report(db, make_report):
    rid = db.add_report(parser.parse_report(make_report(rows=3)))
    db.delete_report(rid)
    assert db.list_reports() == []


def test_delete_entfernt_contracts_cascade(db, make_report):
    rid = db.add_report(parser.parse_report(make_report(rows=3)))
    db.delete_report(rid)
    assert db.get_contracts(rid) == []


def test_all_contracts_mit_report_meta(db, make_report):
    rid = db.add_report(parser.parse_report(make_report(rows=4)))
    rows = db.all_contracts()
    assert len(rows) == 4
    assert all(r["_report_id"] == rid for r in rows)
    assert all(r["_report_date"].startswith("2026-06-25") for r in rows)
    assert "rufnummer" in rows[0]


def test_notes_leer(db):
    assert db.get_notes() == {}


def test_note_set_und_get(db):
    db.set_note("RV-A|0151", "VVL angefragt")
    assert db.get_notes()["RV-A|0151"] == "VVL angefragt"


def test_note_ueberschreiben(db):
    db.set_note("k", "a"); db.set_note("k", "b")
    assert db.get_notes()["k"] == "b"


def test_note_leer_loescht(db):
    db.set_note("k", "x"); db.set_note("k", "  ")
    assert "k" not in db.get_notes()


def test_setting_get_default_none(db):
    assert db.get_setting("password_hash") is None


def test_setting_set_und_get(db):
    db.set_setting("password_hash", "abc123")
    assert db.get_setting("password_hash") == "abc123"


def test_setting_ueberschreiben(db):
    db.set_setting("k", "v1")
    db.set_setting("k", "v2")
    assert db.get_setting("k") == "v2"


def test_persistenz_ueber_reconnect(tmp_path, make_report):
    path = tmp_path / "persist.db"
    s1 = store.Store(path)
    s1.add_report(parser.parse_report(make_report(rows=4)))
    s1.close()

    s2 = store.Store(path)
    assert len(s2.list_reports()) == 1
    s2.close()
