"""Azure/Entra-ID Device-Code-Flow (OAuth 2.0 Device Authorization Grant).

Kein Redirect-URI, kein HTTPS nötig — der Server spricht direkt mit
login.microsoftonline.com (TLS). Ablauf: device_start() liefert einen user_code
+ verification_uri; der Nutzer gibt den Code auf der Microsoft-Seite ein; der
Server pollt mit device_poll() das Token-Endpoint bis zur Anmeldung.

Braucht in der App-Registrierung: „Allow public client flows = Yes".
"""
from __future__ import annotations

import base64
import json

import httpx

_BASE = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0"
_SCOPE = "openid profile email"


def device_start(tenant: str, client_id: str) -> dict:
    """Startet den Flow. Rückgabe u.a.: device_code, user_code, verification_uri,
    interval, expires_in, message."""
    r = httpx.post(f"{_BASE.format(tenant=tenant)}/devicecode",
                   data={"client_id": client_id, "scope": _SCOPE}, timeout=15)
    r.raise_for_status()
    return r.json()


def device_poll(tenant: str, client_id: str, device_code: str) -> tuple[int, dict]:
    """Pollt einmal das Token-Endpoint. (status_code, body).
    200 -> Tokens (id_token/access_token); 400 -> {error: authorization_pending|slow_down|…}."""
    r = httpx.post(f"{_BASE.format(tenant=tenant)}/token",
                   data={"grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                         "client_id": client_id, "device_code": device_code}, timeout=15)
    try:
        body = r.json()
    except ValueError:
        body = {}
    return r.status_code, body


def id_token_claims(id_token: str) -> dict:
    """Claims aus dem id_token lesen (Payload-Segment). Das Token kommt direkt vom
    Microsoft-Token-Endpoint über TLS an den Server — daher reicht die Prüfung von
    aud/tid/exp durch den Aufrufer; keine JWKS-Signaturvalidierung nötig."""
    payload = id_token.split(".")[1]
    payload += "=" * (-len(payload) % 4)  # base64url-Padding
    return json.loads(base64.urlsafe_b64decode(payload))
