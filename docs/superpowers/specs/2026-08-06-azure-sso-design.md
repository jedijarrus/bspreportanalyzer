# Azure SSO (Entra ID / OIDC) — Design

## Ziel
Login über Microsoft Entra ID (Azure AD) als Alternative zum lokalen Passwort.
Zielnutzer: kleines Controlling-Team, self-hosted Docker-Container.

## Entscheidungen
- **Azure-only, wenn konfiguriert:** Sind die drei ENV-Variablen gesetzt, ist der
  Passwort-Login deaktiviert (setup/login → 403). Ohne die Variablen bleibt der
  bisherige Passwort-Flow unverändert. **Break-glass:** ENV-Vars entfernen →
  Rückfall auf Passwort (schützt vor Aussperrung bei Azure-Fehlkonfiguration).
- **Zugriffssteuerung durch Azure:** Enterprise-App „Assignment required = Yes" +
  Nutzer/Gruppen zuweisen. Die App führt **keine eigene Allowlist** — sie akzeptiert
  jeden gültigen Token **aus dem konfigurierten Tenant** (single-tenant), Azure gibt
  Tokens nur an zugewiesene Nutzer aus.

## Konfiguration (ENV)
Wiederverwendung der vorhandenen Graph-App-Registrierung:
- `GRAPH_TENANT_ID`, `GRAPH_CLIENT_ID`, `GRAPH_CLIENT_SECRET`
- optional `BSP_BASE_URL` — Basis-URL für die Redirect-URI hinter dem HTTPS-Proxy
  (sonst aus dem Request abgeleitet).
- `config.azure_configured()` = alle drei Graph-Variablen gesetzt.

## Bibliothek
Authlib (`authlib.integrations.starlette_client.OAuth`) — OIDC-Discovery
(`https://login.microsoftonline.com/{tenant}/v2.0/.well-known/openid-configuration`),
Authorization-Code-Flow, id_token-Validierung (Signatur/exp/aud/iss/nonce) und
state/nonce-Handling out of the box. Neue Prod-Deps: `authlib`, `httpx`.
Import erfolgt **lazy** (nur wenn Azure konfiguriert) — Passwort-only-Deployments
brauchen authlib nicht.

## Endpunkte
- `GET /api/auth/azure/login` → `authorize_redirect` zu Entra (state+nonce in Session).
  404, wenn nicht konfiguriert.
- `GET /api/auth/azure/callback` (name `azure_callback`) → `authorize_access_token`
  (Authlib validiert das id_token gegen die Tenant-Metadaten), Session setzen
  (`auth=True`, `user`=Name/UPN für Anzeige), Redirect auf `/`.
- `GET /api/auth/status` → zusätzliches Flag `sso: true/false`; `configured` ist bei
  Azure-Konfiguration immer true.
- `POST /api/auth/setup` + `POST /api/auth/login` → **403**, wenn Azure konfiguriert.
- `POST /api/auth/logout` → lokale Session löschen (kein Azure-Front-Channel-Logout).

## Redirect-URI
`{BSP_BASE_URL oder Request-Basis}/api/auth/azure/callback`. Muss in der
App-Registrierung als Web-Redirect eingetragen sein. Lokal `http://localhost:8080/...`
(von Azure für localhost erlaubt), Prod über HTTPS-Proxy.

## Sicherheit
- single-tenant (issuer-Pin über die Tenant-Discovery-URL), audience = client_id.
- nonce/state via Authlib (in der signierten Session).
- Session-Cookie httponly + samesite=lax, Secure via `BSP_HTTPS_ONLY`.
- Client-Secret nur aus ENV, nie geloggt/committet.

## Frontend
Auth-Modal: bei `sso:true` ein **„Login mit Microsoft"**-Button (Full-Page-Navigation
zu `/api/auth/azure/login`), Passwortfelder ausgeblendet. Sonst bisheriger Flow.

## Tests (TDD, ohne echtes Azure)
- `azure_configured()` true/false je ENV.
- `/api/auth/status`: `sso=true` wenn konfiguriert, sonst `false`.
- `/api/auth/setup` und `/api/auth/login`: 403 wenn Azure konfiguriert.
- `/api/auth/azure/login`: 404 wenn nicht konfiguriert.
- Callback mit **gemocktem** OAuth-Client (`app.state.oauth.azure.authorize_access_token`
  → fixes Token mit userinfo) → Session `auth=True` gesetzt, Redirect.
- Kein Netzwerk in Tests (Discovery/Token gemockt). Echter Browser-Redirect vom User
  mit realer App-Registrierung.

## Was der User in Azure macht
App-Registrierung (vorhandene Graph-App nutzbar) · Redirect-URI ergänzen · Client-Secret ·
Enterprise-App „Assignment required = Yes" + Nutzer zuweisen · ENV-Vars setzen.
