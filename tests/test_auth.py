"""Tests für app.auth — Passwort-Hashing (stdlib pbkdf2)."""
from app import auth


def test_hash_enthaelt_nicht_das_passwort():
    h = auth.hash_password("geheim123")
    assert "geheim123" not in h


def test_verify_korrektes_passwort():
    h = auth.hash_password("geheim123")
    assert auth.verify_password("geheim123", h) is True


def test_verify_falsches_passwort():
    h = auth.hash_password("geheim123")
    assert auth.verify_password("falsch", h) is False


def test_zwei_hashes_unterscheiden_sich_durch_salt():
    assert auth.hash_password("x") != auth.hash_password("x")


def test_verify_toleriert_kaputten_hash():
    assert auth.verify_password("x", "muell") is False
    assert auth.verify_password("x", "") is False
