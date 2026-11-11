"""GLPI-Anbindung für den Abgleich Telekom ↔ GLPI (High-Level-API v3, ab GLPI 11).

Anmeldung per OAuth2 Password-Grant (Client unter Konfiguration → OAuth-Clients, Scope
`api`), danach nur lesende Abrufe: Leitungen, SIM-Karten und die Namen der Benutzer, an
denen sie hängen. Das Ergebnis ist ein schlanker Snapshot mit genau den Feldern, die der
Abgleich braucht; PIN/PUK der SIM-Karten werden nie übernommen.

Fehler kommen als GlpiError mit einem Text für die Oberfläche — ohne Zugangsdaten.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

import httpx

API_VERSION = "v3.0"
PAGE_SIZE = 200
MAX_PAGES = 100          # Notbremse: 100 × 200 Einträge je Liste
TIMEOUT_S = 30.0


class GlpiError(Exception):
    """Abruf aus GLPI fehlgeschlagen; der Text ist für die Oberfläche gedacht."""


def _token(client: httpx.Client, s: dict) -> str:
    try:
        r = client.post(s["url"] + "/token", data={
            "grant_type": "password", "client_id": s["client_id"], "client_secret": s["client_secret"],
            "username": s["username"], "password": s["password"], "scope": "api",
        })
    except httpx.HTTPError as e:
        raise GlpiError(f"GLPI nicht erreichbar ({type(e).__name__})") from None
    if r.status_code != 200:
        code = ""
        try:
            code = str(r.json().get("error") or "")
        except ValueError:
            pass
        raise GlpiError(f"Anmeldung bei GLPI fehlgeschlagen (HTTP {r.status_code}{', ' + code if code else ''})")
    try:
        return r.json()["access_token"]
    except (ValueError, KeyError):
        raise GlpiError("Anmeldung bei GLPI fehlgeschlagen (keine gültige Token-Antwort)") from None


def _all(client: httpx.Client, base: str, path: str, headers: dict) -> list[dict]:
    """Alle Einträge einer Liste, seitenweise über start/limit."""
    out: list[dict] = []
    for page in range(MAX_PAGES):
        try:
            r = client.get(f"{base}/{API_VERSION}{path}", headers=headers,
                           params={"start": page * PAGE_SIZE, "limit": PAGE_SIZE})
        except httpx.HTTPError as e:
            raise GlpiError(f"GLPI nicht erreichbar ({type(e).__name__})") from None
        if r.status_code not in (200, 206):
            raise GlpiError(f"GLPI-Abruf {path} fehlgeschlagen (HTTP {r.status_code})")
        try:
            body = r.json()
        except ValueError:
            raise GlpiError(f"GLPI-Abruf {path}: keine JSON-Antwort") from None
        if not isinstance(body, list):
            raise GlpiError(f"GLPI-Abruf {path}: unerwartete Antwort")
        out.extend(body)
        total = _total(r.headers.get("Content-Range"))
        if len(body) < PAGE_SIZE or (total is not None and len(out) >= total):
            break
    return out


def _total(content_range: str | None) -> int | None:
    """Gesamtzahl aus „Content-Range: 0-199/500"."""
    if not content_range or "/" not in content_range:
        return None
    tail = content_range.rsplit("/", 1)[1].strip()
    return int(tail) if tail.isdigit() else None


def _ref_id(v: Any) -> int | None:
    return v.get("id") if isinstance(v, dict) and v.get("id") else None


def _ref_name(v: Any) -> str | None:
    return (v.get("name") or v.get("designation")) if isinstance(v, dict) else None


def fetch_snapshot(settings: dict, transport: httpx.BaseTransport | None = None) -> dict:
    """Liest Leitungen, SIM-Karten und deren Benutzer aus GLPI.

    SIM-Karten kommen je Modell über /Components/SIMCard/{id}/Items; manche GLPI-Versionen liefern
    dort für jedes Modell alle Karten — darum nach id entdoppelt.
    """
    s = {k: (v or "") for k, v in settings.items()}
    if not all(s.get(k) for k in ("url", "client_id", "client_secret", "username", "password")):
        raise GlpiError("GLPI ist nicht vollständig eingerichtet")
    with httpx.Client(timeout=TIMEOUT_S, transport=transport) as client:
        h = {"Authorization": "Bearer " + _token(client, s), "Accept": "application/json"}
        raw_lines = _all(client, s["url"], "/Management/Line", h)
        raw_sims: dict[int, dict] = {}
        for model in _all(client, s["url"], "/Components/SIMCard", h):
            for it in _all(client, s["url"], f"/Components/SIMCard/{model['id']}/Items", h):
                raw_sims.setdefault(it["id"], it)
        raw_users = _all(client, s["url"], "/Administration/User", h)

    lines = [{
        "id": ln.get("id"), "nr": ln.get("caller_num") or ln.get("name") or "",
        "user_id": _ref_id(ln.get("user")), "deleted": bool(ln.get("is_deleted")),
    } for ln in raw_lines]
    sims = [{
        # bewusst ohne pin/pin2/puk/puk2
        "id": it.get("id"), "serial": it.get("serial") or "", "model": _ref_name(it.get("sim_card")),
        "line_id": _ref_id(it.get("line")), "user_id": _ref_id(it.get("user")),
        "itemtype": it.get("itemtype") or None, "items_id": it.get("items_id") or None,
        "deleted": bool(it.get("is_deleted")),
    } for it in raw_sims.values()]
    # Nur die Benutzer, an denen eine Leitung oder Karte hängt — keine Kopie der Belegschaft
    used = {x["user_id"] for x in lines + sims if x["user_id"]}
    users = {}
    for u in raw_users:
        if u.get("id") in used:
            users[str(u["id"])] = {"realname": u.get("realname") or "", "firstname": u.get("firstname") or "",
                                   "username": u.get("username") or ""}
    return {"fetched_at": dt.datetime.now().isoformat(timespec="seconds"),
            "lines": lines, "sims": sims, "users": users}
