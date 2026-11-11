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


# ---- Azure / Entra ID SSO (optional) ------------------------------------
# Entra-ID-App-Registrierung über die GRAPH_*-Variablen. Sind alle drei
# gesetzt, gilt SSO als konfiguriert -> Passwort-Login wird deaktiviert.
def azure_settings() -> dict[str, str | None]:
    return {
        "tenant": os.environ.get("GRAPH_TENANT_ID") or None,
        "client_id": os.environ.get("GRAPH_CLIENT_ID") or None,
        "client_secret": os.environ.get("GRAPH_CLIENT_SECRET") or None,
        "base_url": os.environ.get("BSP_BASE_URL") or None,
        # optional: nur Nutzer mit dieser App-Rolle (roles-Claim) dürfen rein
        "required_role": os.environ.get("GRAPH_REQUIRED_ROLE") or None,
    }


def azure_configured() -> bool:
    s = azure_settings()
    return bool(s["tenant"] and s["client_id"] and s["client_secret"])


# ---- GLPI-Abgleich (optional) -------------------------------------------
# High-Level-API von GLPI (ab 11), Anmeldung per OAuth2 Password-Grant. GLPI_URL ist
# die API-Basis, also https://<glpi>/api.php. Sind alle fünf gesetzt, gibt es den
# Reiter „GLPI" mit Daten; sonst zeigt er nur, was fehlt.
GLPI_KEYS = ("GLPI_URL", "GLPI_CLIENT_ID", "GLPI_CLIENT_SECRET", "GLPI_USERNAME", "GLPI_PASSWORD")


def glpi_settings() -> dict[str, str | None]:
    url = (os.environ.get("GLPI_URL") or "").strip().rstrip("/")
    # tolerant: eine mitkopierte Versionsangabe (…/api.php/v3.0) abschneiden
    url = url.removesuffix("/v3.0").removesuffix("/v3").rstrip("/")
    return {
        "url": url or None,
        "client_id": os.environ.get("GLPI_CLIENT_ID") or None,
        "client_secret": os.environ.get("GLPI_CLIENT_SECRET") or None,
        "username": os.environ.get("GLPI_USERNAME") or None,
        "password": os.environ.get("GLPI_PASSWORD") or None,
    }


def glpi_missing() -> list[str]:
    """Die Namen der GLPI-Variablen, die nicht gesetzt sind (leer = eingerichtet)."""
    return [k for k in GLPI_KEYS if not (os.environ.get(k) or "").strip()]


def glpi_web_base() -> str | None:
    """Basis der GLPI-Oberfläche für Links auf Einträge (API-Basis ohne /api.php)."""
    url = glpi_settings()["url"]
    return url.removesuffix("/api.php") if url else None


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
