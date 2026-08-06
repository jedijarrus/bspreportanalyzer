"""FastAPI-Anwendung: Auth, Upload, Report-Verwaltung, Auswertungs-Endpunkte.

Sicherheit:
- Passwortschutz per signiertem Session-Cookie (kein Basic-Auth). Beim ersten
  Start wird das Passwort im Dashboard gesetzt; der Hash liegt in der DB (data/).
- Alle Daten-Endpunkte erfordern eine gültige Session (serverseitig erzwungen).
- Upload: Dateiname wird auf den Basenamen reduziert (kein Path-Traversal),
  Größe begrenzt (OOM-/Zip-Bomb-Schutz).
Alle Daten bleiben lokal; nichts verlässt den Container.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request

from app import analytics, auth, azure_verify, config, invoice_parser, parser, version
from app.store import Store

WEB_DIR = Path(__file__).resolve().parents[1] / "web"
PW_HASH_KEY = "password_hash"
MIN_PASSWORD_LEN = 8

VVL_VIEW_FIELDS = (
    "rufnummer", "kostenstellennutzer", "kostenstelle", "tarif",
    "vertragsbeginn", "bindefristende", "vvl_berechtigung", "kartentyp", "sperren",
)


class PasswordBody(BaseModel):
    password: str


class TokenBody(BaseModel):
    token: str


def _azure_redirect_uri(request: Request) -> str:
    """Redirect-URI für den OIDC-Callback. Hinter dem HTTPS-Proxy über BSP_BASE_URL,
    sonst aus dem Request abgeleitet."""
    base = config.azure_settings().get("base_url")
    if base:
        return base.rstrip("/") + "/api/auth/azure/callback"
    return str(request.url_for("azure_callback"))


class NoteBody(BaseModel):
    key: str
    note: str = ""


def get_store():
    s = Store(config.DB_PATH)
    try:
        yield s
    finally:
        s.close()


def require_auth(request: Request):
    """Session-Wächter für alle Daten-Endpunkte."""
    if not request.session.get("auth"):
        raise HTTPException(401, "Nicht angemeldet")


def _today() -> dt.date:
    return dt.date.today()


def _latest_invoice(db: Store):
    """Neueste Rechnung (nach Periode, dann id) oder None."""
    invs = db.list_invoices()
    if not invs:
        return None
    return sorted(invs, key=lambda i: (i.get("period_start") or "", i["id"]))[-1]


def create_app(secret_key: str | None = None) -> FastAPI:
    app = FastAPI(title="Telekom BSP Report Analyzer")
    app.add_middleware(
        SessionMiddleware,
        secret_key=secret_key or config.get_secret_key(),
        same_site="lax",
        https_only=config.HTTPS_ONLY,  # via BSP_HTTPS_ONLY setzen, wenn hinter TLS-Proxy
    )
    app.state.login_fails = {"count": 0, "until": 0.0}  # simple Brute-Force-Bremse

    # Azure/Entra-ID SSO nur registrieren, wenn konfiguriert (Import lazy -> Passwort-
    # only-Deployments brauchen authlib nicht).
    app.state.oauth = None
    if config.azure_configured():
        from authlib.integrations.starlette_client import OAuth
        s = config.azure_settings()
        oauth = OAuth()
        oauth.register(
            name="azure",
            client_id=s["client_id"],
            client_secret=s["client_secret"],
            server_metadata_url=f"https://login.microsoftonline.com/{s['tenant']}/v2.0/.well-known/openid-configuration",
            client_kwargs={"scope": "openid profile email"},
        )
        app.state.oauth = oauth

    _bi = version.build_info()
    print(f"[BSP] Version {_bi['sha']} · gebaut {_bi['built']} · "
          f"SSO={'an' if config.azure_configured() else 'aus'}", flush=True)

    templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))
    static_dir = WEB_DIR / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # ---- UI -------------------------------------------------------------
    @app.get("/", response_class=HTMLResponse)
    def dashboard(request: Request):
        return templates.TemplateResponse(request, "dashboard.html")

    @app.get("/api/version")
    def app_version():
        return version.build_info()   # Build-Marker: sha + Bauzeit (erkennt altes Image)

    # ---- Auth -----------------------------------------------------------
    @app.get("/api/auth/status")
    def auth_status(request: Request, db: Store = Depends(get_store)):
        sso = config.azure_configured()
        s = config.azure_settings() if sso else {}
        return {
            "configured": sso or db.get_setting(PW_HASH_KEY) is not None,
            "authenticated": bool(request.session.get("auth")),
            "user": request.session.get("user"),   # angezeigter Name (nur bei SSO gesetzt)
            "sso": sso,
            # client_id/tenant sind öffentliche IDs (keine Secrets) -> fürs MSAL-Setup im Frontend
            "azure": {"client_id": s.get("client_id"), "tenant": s.get("tenant")} if sso else None,
        }

    @app.post("/api/auth/setup", status_code=201)
    def auth_setup(body: PasswordBody, request: Request, db: Store = Depends(get_store)):
        if config.azure_configured():
            raise HTTPException(403, "SSO aktiv – Passwort-Login ist deaktiviert.")
        if db.get_setting(PW_HASH_KEY) is not None:
            raise HTTPException(409, "Passwort ist bereits gesetzt.")
        if len(body.password) < MIN_PASSWORD_LEN:
            raise HTTPException(400, f"Passwort muss mind. {MIN_PASSWORD_LEN} Zeichen haben.")
        db.set_setting(PW_HASH_KEY, auth.hash_password(body.password))
        request.session["auth"] = True
        return {"status": "ok"}

    @app.post("/api/auth/login")
    def auth_login(body: PasswordBody, request: Request, db: Store = Depends(get_store)):
        if config.azure_configured():
            raise HTTPException(403, "SSO aktiv – Passwort-Login ist deaktiviert.")
        st = request.app.state.login_fails
        now = dt.datetime.now().timestamp()
        if st["until"] > now:
            raise HTTPException(429, "Zu viele Fehlversuche. Bitte kurz warten.")
        stored = db.get_setting(PW_HASH_KEY)
        if not stored or not auth.verify_password(body.password, stored):
            st["count"] += 1
            if st["count"] >= 5:                 # nach 5 Fehlversuchen 30 s sperren
                st["until"], st["count"] = now + 30.0, 0
            raise HTTPException(401, "Falsches Passwort.")
        st["count"] = 0
        request.session["auth"] = True
        return {"status": "ok"}

    @app.post("/api/auth/logout")
    def auth_logout(request: Request):
        request.session.clear()
        return {"status": "ok"}

    # ---- Azure / Entra ID SSO (nur wenn konfiguriert) ------------------
    @app.get("/api/auth/azure/login")
    async def azure_login(request: Request):
        if request.app.state.oauth is None:
            raise HTTPException(404, "SSO nicht konfiguriert.")
        return await request.app.state.oauth.azure.authorize_redirect(request, _azure_redirect_uri(request))

    @app.get("/api/auth/azure/callback", name="azure_callback")
    async def azure_callback(request: Request):
        if request.app.state.oauth is None:
            raise HTTPException(404, "SSO nicht konfiguriert.")
        try:
            # authlib validiert das id_token (Signatur/exp/aud/iss/nonce) gegen die Tenant-Metadaten
            token = await request.app.state.oauth.azure.authorize_access_token(request)
        except Exception:
            raise HTTPException(401, "SSO-Anmeldung fehlgeschlagen.")
        claims = token.get("userinfo") or {}
        request.session["auth"] = True
        request.session["user"] = claims.get("name") or claims.get("preferred_username") or claims.get("email")
        return RedirectResponse("/", status_code=303)

    # ---- MSAL-Login: Frontend holt Token (Popup/Redirect), Server validiert ---
    @app.post("/api/auth/azure/verify")
    def azure_verify_ep(body: TokenBody, request: Request):
        if not config.azure_configured():
            raise HTTPException(404, "SSO nicht konfiguriert.")
        s = config.azure_settings()
        try:
            claims = azure_verify.validate_token(body.token, s["tenant"], s["client_id"])
        except Exception:
            raise HTTPException(401, "Token ungültig.")
        request.session["auth"] = True
        request.session["user"] = claims.get("name") or claims.get("preferred_username") or claims.get("upn")
        return {"status": "ok"}

    # ---- Report-Verwaltung ---------------------------------------------
    @app.post("/api/reports", status_code=201, dependencies=[Depends(require_auth)])
    async def upload_report(file: UploadFile, db: Store = Depends(get_store)):
        # Path-Traversal verhindern: nur Basename verwenden
        safe_name = Path(file.filename or "").name
        if not safe_name.lower().endswith(".xlsx"):
            raise HTTPException(400, "Nur .xlsx-Reports werden akzeptiert.")
        # Größenlimit: höchstens MAX+1 Bytes lesen (begrenzt RAM)
        content = await file.read(config.MAX_UPLOAD_BYTES + 1)
        if len(content) > config.MAX_UPLOAD_BYTES:
            raise HTTPException(413, "Datei zu groß.")

        config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        dest = config.UPLOAD_DIR / safe_name
        dest.write_bytes(content)
        try:
            data = parser.parse_report(dest)
        except Exception:
            dest.unlink(missing_ok=True)
            raise HTTPException(400, "Report konnte nicht gelesen werden (ungültiges xlsx?).")
        rd = data.report_date.isoformat() if data.report_date else None
        existing = db.find_report(data.filename, rd, len(data.rows))
        if existing:  # Dedup: identische Report-Datei schon importiert
            return {"report_id": existing["id"], "duplicate": True,
                    "row_count": 0, "filename": data.filename}
        report_id = db.add_report(data)
        return {"report_id": report_id, "duplicate": False,
                "row_count": len(data.rows), "filename": data.filename}

    @app.get("/api/reports", dependencies=[Depends(require_auth)])
    def list_reports(db: Store = Depends(get_store)):
        return db.list_reports()

    @app.get("/api/notes", dependencies=[Depends(require_auth)])
    def get_notes(db: Store = Depends(get_store)):
        return db.get_notes()

    @app.post("/api/notes", dependencies=[Depends(require_auth)])
    def set_note(body: NoteBody, db: Store = Depends(get_store)):
        db.set_note(body.key, body.note)
        return {"status": "ok"}

    @app.get("/api/fields", dependencies=[Depends(require_auth)])
    def fields():
        """Feld (snake) -> Original-Header, für UI-Beschriftung."""
        from app import schema
        return schema.HEADER_BY_FIELD

    @app.get("/api/current", dependencies=[Depends(require_auth)])
    def current(db: Store = Depends(get_store)):
        """Aktueller Gesamtbestand über alle Rahmenverträge (neuester Report je RV),
        angereichert mit Kosten aus der neuesten Rechnung (Join über Rufnummer)."""
        fleet = analytics.current_fleet(db.all_contracts())
        stand = max((c.get("_report_date") or "" for c in fleet), default=None)
        rvs = sorted({c.get("rahmenvertrag") for c in fleet if c.get("rahmenvertrag")})
        frische = analytics.fleet_freshness(fleet, _today(), config.MAX_REPORT_AGE_DAYS)

        norm = analytics.normalize_rufnummer
        latest = _latest_invoice(db)
        kmap, brutto_factor, rechnung_stand, auslastung, util_map = {}, 1.19, None, None, {}
        if latest:
            lines = db.get_invoice_lines(latest["id"])
            # Kosten je Rufnummer, umgeschlüsselt auf normalisierte Rufnummer (Join)
            kmap = {}
            for k, v in analytics.kosten_je_rufnummer(lines).items():
                nk = norm(k)
                if nk in kmap:  # zwei Schreibweisen derselben Nummer -> Kosten addieren, nicht ueberschreiben
                    for f, val in v.items():
                        kmap[nk][f] = kmap[nk].get(f, 0.0) + val
                else:
                    kmap[nk] = dict(v)
            auslastung = analytics.datenauslastung(lines)
            # Per-Vertrag-Datenauslastung (nur mit CSV-Rechnung: Datenzeilen tragen Rufnummer)
            util_map = {norm(l["rufnummer"]): l for l in lines
                        if l.get("data_contracted_gb") and l.get("rufnummer")}
            net, gross = latest.get("total_net") or 0, latest.get("total_gross") or 0
            if net:
                brutto_factor = round(gross / net, 4)
            rechnung_stand = latest.get("period_start")

        for c in fleet:
            k = kmap.get(norm(c.get("rufnummer")))
            c["_kosten_netto"] = round(k["netto"], 2) if k else None
            c["_rabatt"] = round(k["rabatt"], 2) if k else None
            c["_grundpreis"] = round(k["grundpreis"] + k["option"], 2) if k else None
            um = util_map.get(norm(c.get("rufnummer")))
            if um:
                cg, ug = um["data_contracted_gb"], um.get("data_used_gb") or 0.0
                c["_data_contracted_gb"] = round(cg, 1)
                c["_data_used_gb"] = round(ug, 2)
                c["_auslastung_pct"] = round(ug / cg * 100, 1) if cg else None
            else:
                c["_data_contracted_gb"] = c["_data_used_gb"] = c["_auslastung_pct"] = None

        return {"stand": stand or None, "rahmenvertraege": rvs, "contracts": fleet,
                "netto_factor": 1.0, "brutto_factor": brutto_factor,
                "rechnung_stand": rechnung_stand, "datenauslastung": auslastung,
                "stale": frische["stale"], "stand_alter_tage": frische["stand_alter_tage"],
                "max_age_tage": frische["max_age_tage"], "frische": frische["rv"]}

    # ---- Rechnungen / Kosten -------------------------------------------
    @app.post("/api/invoices", status_code=201, dependencies=[Depends(require_auth)])
    async def upload_invoice(file: UploadFile, db: Store = Depends(get_store)):
        safe_name = Path(file.filename or "").name
        if not safe_name.lower().endswith(".csv"):
            raise HTTPException(400, "Nur Rechnungen als Telekom-CSV (.csv) werden akzeptiert.")
        content = await file.read(config.MAX_UPLOAD_BYTES + 1)
        if len(content) > config.MAX_UPLOAD_BYTES:
            raise HTTPException(413, "Datei zu groß.")
        config.INVOICE_DIR.mkdir(parents=True, exist_ok=True)
        dest = config.INVOICE_DIR / safe_name
        dest.write_bytes(content)
        try:
            data = invoice_parser.parse_invoice(dest)
        except Exception:
            dest.unlink(missing_ok=True)
            raise HTTPException(400, "Rechnung konnte nicht gelesen werden (ungültige CSV?).")
        existing = db.find_invoice(data.invoice_number)
        if existing:  # Dedup: gleiche Rechnungsnummer schon importiert -> nicht doppelt speichern
            return {"invoice_id": existing["id"], "duplicate": True,
                    "line_count": 0, "filename": data.filename}
        invoice_id = db.add_invoice(data)
        return {"invoice_id": invoice_id, "duplicate": False,
                "line_count": len(data.lines), "filename": data.filename}

    @app.get("/api/invoices", dependencies=[Depends(require_auth)])
    def list_invoices(db: Store = Depends(get_store)):
        return db.list_invoices()

    @app.delete("/api/invoices/{invoice_id}", status_code=204,
                dependencies=[Depends(require_auth)])
    def delete_invoice(invoice_id: int, db: Store = Depends(get_store)):
        db.delete_invoice(invoice_id)
        return Response(status_code=204)

    @app.get("/api/invoices/{invoice_id}", dependencies=[Depends(require_auth)])
    def invoice_detail(invoice_id: int, db: Store = Depends(get_store)):
        invs = {i["id"]: i for i in db.list_invoices()}
        inv = invs.get(invoice_id)
        if not inv:
            raise HTTPException(404, "Rechnung nicht gefunden.")
        lines = db.get_invoice_lines(invoice_id)
        # Join mit aktueller Flotte (Rufnummer) für Nutzer/Rahmenvertrag
        norm = analytics.normalize_rufnummer
        cmap = {norm(c.get("rufnummer")): c for c in analytics.current_fleet(db.all_contracts())}
        kmap = analytics.kosten_je_rufnummer(lines)
        rv_agg: dict = {}
        for ruf, v in kmap.items():
            c = cmap.get(norm(ruf))
            key = (c.get("rahmenvertrag") if c else None) or "(ohne Vertrag)"
            d = rv_agg.setdefault(key, {"rahmenvertrag": key, "netto": 0.0, "anzahl": 0})
            d["netto"] = round(d["netto"] + v["netto"], 2)
            d["anzahl"] += 1
        top = sorted(kmap.items(), key=lambda kv: -kv[1]["netto"])[:12]
        # Vorrechnung (nach Periode) für Δ
        ordered = sorted(invs.values(), key=lambda i: (i.get("period_start") or "", i["id"]))
        pos = [i["id"] for i in ordered].index(invoice_id)
        prev = ordered[pos - 1] if pos > 0 else None
        diff = analytics.invoice_diff(db.get_invoice_lines(prev["id"]), lines) if prev else None
        return {
            "invoice": inv,
            "kategorie": analytics.kosten_je_kategorie(lines),
            "kostenstelle": analytics.kosten_je_kostenstelle(lines),
            "reconcile": analytics.reconcile(lines, inv.get("total_net") or 0.0),
            "datenauslastung": analytics.datenauslastung(lines),
            "auslastung_liste": analytics.datenauslastung_liste(lines),
            "je_rahmenvertrag": sorted(rv_agg.values(), key=lambda x: -x["netto"]),
            "top_treiber": [{"rufnummer": r, "netto": round(v["netto"], 2), "rabatt": round(v["rabatt"], 2),
                             "nutzer": (cmap.get(norm(r)) or {}).get("kostenstellennutzer")}
                            for r, v in top],
            "diff": diff,
            "prev_period": prev.get("period_start") if prev else None,
            "gb_trend": analytics.fleet_gb_trend(db.all_invoice_lines()),
            "zuordnungsluecken": analytics.zuordnungsluecken(lines, list(cmap.values())),
            "top_gesamt": analytics.top_rufnummer_gesamt(
                db.all_invoice_lines(),
                {k: (c.get("kostenstellennutzer")) for k, c in cmap.items()}),
        }

    @app.get("/api/costs/kostenstellen", dependencies=[Depends(require_auth)])
    def costs_kostenstellen(invoice_id: int | None = None, db: Store = Depends(get_store)):
        inv = {i["id"]: i for i in db.list_invoices()}.get(invoice_id) if invoice_id else _latest_invoice(db)
        lines = db.get_invoice_lines(inv["id"]) if inv else []
        return analytics.kosten_je_kostenstelle(lines)

    @app.get("/api/costs/trend", dependencies=[Depends(require_auth)])
    def costs_trend(db: Store = Depends(get_store)):
        return analytics.kosten_trend(db.all_invoice_lines())

    @app.get("/api/costs/lines/{rufnummer}", dependencies=[Depends(require_auth)])
    def costs_lines(rufnummer: str, db: Store = Depends(get_store)):
        latest = _latest_invoice(db)
        if not latest:
            return []
        target = analytics.normalize_rufnummer(rufnummer)
        return [l for l in db.get_invoice_lines(latest["id"])
                if analytics.normalize_rufnummer(l.get("rufnummer")) == target]

    @app.get("/api/linie/{rufnummer}", dependencies=[Depends(require_auth)])
    def linie(rufnummer: str, db: Store = Depends(get_store)):
        """Monitoring EINER Rufnummer: Kosten-/Verbrauchs-Verlauf über alle
        Rechnungsmonate, Auffälligkeiten (Monat-zu-Monat) und Report-Stammdaten."""
        norm = analytics.normalize_rufnummer
        target = norm(rufnummer)
        verlauf = analytics.linie_verlauf(db.all_invoice_lines(), rufnummer)
        auff = analytics.linie_auffaelligkeiten(verlauf)
        contract = next((c for c in analytics.current_fleet(db.all_contracts())
                         if norm(c.get("rufnummer")) == target), None)
        if contract is None and not verlauf:
            raise HTTPException(404, "Rufnummer nicht gefunden.")
        return {"rufnummer": rufnummer, "stammdaten": contract,
                "verlauf": verlauf, "auffaelligkeiten": auff}

    @app.delete("/api/reports/{report_id}", status_code=204,
                dependencies=[Depends(require_auth)])
    def delete_report(report_id: int, db: Store = Depends(get_store)):
        db.delete_report(report_id)
        return Response(status_code=204)

    # ---- Auswertungen ---------------------------------------------------
    @app.get("/api/reports/{report_id}/vvl", dependencies=[Depends(require_auth)])
    def vvl(report_id: int, within_days: int = 90, db: Store = Depends(get_store)):
        contracts = db.get_contracts(report_id)
        today = _today()
        expiring = [
            {k: c.get(k) for k in VVL_VIEW_FIELDS}
            for c in analytics.expiring(contracts, today, within_days)
        ]
        return {"buckets": analytics.bindefrist_buckets(contracts, today),
                "expiring": expiring}

    @app.get("/api/reports/{report_id}/inventory", dependencies=[Depends(require_auth)])
    def inventory(report_id: int, db: Store = Depends(get_store)):
        return analytics.inventory(db.get_contracts(report_id))

    @app.get("/api/reports/{report_id}/tarife", dependencies=[Depends(require_auth)])
    def tarife(report_id: int, db: Store = Depends(get_store)):
        contracts = db.get_contracts(report_id)
        return {
            "tarif": analytics.distribution(contracts, "tarif"),
            "daten_optionen": analytics.split_distribution(contracts, "daten_optionen"),
            "voice_optionen": analytics.split_distribution(contracts, "voice_optionen"),
            "roaming_optionen": analytics.split_distribution(contracts, "roaming_optionen"),
            "nach_kostenstelle": analytics.distribution(contracts, "kostenstelle"),
        }

    @app.get("/api/diff", dependencies=[Depends(require_auth)])
    def diff(old: int, new: int, db: Store = Depends(get_store)):
        return analytics.diff(db.get_contracts(old), db.get_contracts(new))

    @app.get("/api/trend", dependencies=[Depends(require_auth)])
    def trend(db: Store = Depends(get_store)):
        snapshots = [
            {"report_date": r["report_date"], "contracts": db.get_contracts(r["id"])}
            for r in db.list_reports()
        ]
        return analytics.trend(snapshots, _today())

    return app


app = create_app()
