"""Entra-ID id_token serverseitig validieren (wie die Portal-API).

Der Login passiert im Browser via MSAL.js; das Frontend schickt das id_token an
den Server, der es hier prüft: Signatur gegen die Tenant-JWKS (RS256), Aussteller
(iss), Zielgruppe (aud = client_id), Mandant (tid) und Ablauf (exp). Danach wird
die Session gesetzt. JWKS werden 1 h gecacht.
"""
from __future__ import annotations

import time

import httpx
from authlib.jose import JsonWebKey, jwt

_JWKS_TTL = 3600
_cache: dict = {"tenant": None, "keys": None, "ts": 0.0}


def _jwks(tenant: str):
    now = time.time()
    if _cache["keys"] is not None and _cache["tenant"] == tenant and now - _cache["ts"] < _JWKS_TTL:
        return _cache["keys"]
    r = httpx.get(f"https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys", timeout=15)
    r.raise_for_status()
    keys = JsonWebKey.import_key_set(r.json())
    _cache.update(tenant=tenant, keys=keys, ts=now)
    return keys


def validate_token(token: str, tenant: str, client_id: str) -> dict:
    """Validiertes id_token -> Claims. Wirft bei ungültigem/abgelaufenem/fremdem Token."""
    claims = jwt.decode(token, _jwks(tenant), claims_options={
        "iss": {"essential": True, "values": [
            f"https://login.microsoftonline.com/{tenant}/v2.0",
            f"https://sts.windows.net/{tenant}/",
        ]},
        "aud": {"essential": True, "value": client_id},
    })
    claims.validate()  # exp/iss/aud gemäß Optionen
    if claims.get("tid") != tenant:
        raise ValueError("tenant mismatch")
    return dict(claims)
