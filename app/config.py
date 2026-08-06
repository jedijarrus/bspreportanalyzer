"""Zentrale Pfad-/Konfigurationswerte. Über Umgebungsvariablen steuerbar
(im Docker-Container via Volume + ENV)."""
from __future__ import annotations

import os
from pathlib import Path

import secrets

DATA_DIR = Path(os.environ.get("BSP_DATA_DIR", "data"))
DB_PATH = Path(os.environ.get("BSP_DB_PATH", DATA_DIR / "app.db"))
UPLOAD_DIR = Path(os.environ.get("BSP_UPLOAD_DIR", DATA_DIR / "uploads"))
INVOICE_DIR = Path(os.environ.get("BSP_INVOICE_DIR", DATA_DIR / "rechnungen"))

# Maximale Upload-Größe (Schutz gegen OOM / Zip-Bomb). Default 25 MB.
MAX_UPLOAD_BYTES = int(os.environ.get("BSP_MAX_UPLOAD_MB", "25")) * 1024 * 1024

# Frische-Fenster: Report-Stände älter als so viele Tage gelten als „veraltet"
# (nur Warn-Signal, es wird nichts ausgeblendet). Default 14 Tage.
MAX_REPORT_AGE_DAYS = int(os.environ.get("BSP_MAX_REPORT_AGE_DAYS", "14"))

# Session-Cookie nur über HTTPS ausliefern (Secure-Flag). Hinter einem TLS-Proxy
# auf 1/true setzen; Default aus, da lokal via HTTP betrieben.
HTTPS_ONLY = os.environ.get("BSP_HTTPS_ONLY", "").strip().lower() in ("1", "true", "yes", "on")


def get_secret_key() -> str:
    """Secret für signierte Session-Cookies.

    Reihenfolge: ENV -> persistierte Datei in data/ -> neu generieren.
    Persistenz hält Sessions über Neustarts gültig (Einzelnutzer-Tool).
    """
    env = os.environ.get("BSP_SECRET_KEY")
    if env:
        return env
    key_file = DATA_DIR / "secret.key"
    if key_file.exists():
        _restrict(key_file)
        return key_file.read_text().strip()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    key = secrets.token_hex(32)
    key_file.write_text(key)
    _restrict(key_file)
    return key


def _restrict(path: Path) -> None:
    """Session-Signierschlüssel nur für den Owner lesbar (chmod 600, best effort).
    Wer die Datei liest, kann beliebige Session-Cookies signieren -> Auth-Umgehung."""
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
