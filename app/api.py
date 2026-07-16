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
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request

from app import analytics, auth, config, invoice_parser, parser
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
        https_only=False,  # lokales HTTP; hinter HTTPS-Proxy auf True setzen
    )
    templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))
    static_dir = WEB_DIR / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # ---- UI -------------------------------------------------------------
    @app.get("/", response_class=HTMLResponse)
    def dashboard(request: Request):
        return templates.TemplateResponse(request, "dashboard.html")

    # ---- Auth -----------------------------------------------------------
    @app.get("/api/auth/status")
    def auth_status(request: Request, db: Store = Depends(get_store)):
        return {
            "configured": db.get_setting(PW_HASH_KEY) is not None,
            "authenticated": bool(request.session.get("auth")),
        }

    @app.post("/api/auth/setup", status_code=201)
    def auth_setup(body: PasswordBody, request: Request, db: Store = Depends(get_store)):
        if db.get_setting(PW_HASH_KEY) is not None:
            raise HTTPException(409, "Passwort ist bereits gesetzt.")
        if len(body.password) < MIN_PASSWORD_LEN:
            raise HTTPException(400, f"Passwort muss mind. {MIN_PASSWORD_LEN} Zeichen haben.")
        db.set_setting(PW_HASH_KEY, auth.hash_password(body.password))
        request.session["auth"] = True
        return {"status": "ok"}

    @app.post("/api/auth/login")
    def auth_login(body: PasswordBody, request: Request, db: Store = Depends(get_store)):
        stored = db.get_setting(PW_HASH_KEY)
        if not stored or not auth.verify_password(body.password, stored):
            raise HTTPException(401, "Falsches Passwort.")
        request.session["auth"] = True
        return {"status": "ok"}

    @app.post("/api/auth/logout")
    def auth_logout(request: Request):
        request.session.clear()
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
        report_id = db.add_report(data)
        return {"report_id": report_id, "row_count": len(data.rows),
                "filename": data.filename}

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

        norm = analytics.normalize_rufnummer
        latest = _latest_invoice(db)
        kmap, brutto_factor, rechnung_stand = {}, 1.19, None
        if latest:
            lines = db.get_invoice_lines(latest["id"])
            # Kosten je Rufnummer, umgeschlüsselt auf normalisierte Rufnummer (Join)
            kmap = {norm(k): v for k, v in analytics.kosten_je_rufnummer(lines).items()}
            net, gross = latest.get("total_net") or 0, latest.get("total_gross") or 0
            if net:
                brutto_factor = round(gross / net, 4)
            rechnung_stand = latest.get("period_start")

        for c in fleet:
            k = kmap.get(norm(c.get("rufnummer")))
            c["_kosten_netto"] = round(k["netto"], 2) if k else None
            c["_rabatt"] = round(k["rabatt"], 2) if k else None
            c["_grundpreis"] = round(k["grundpreis"] + k["option"], 2) if k else None

        return {"stand": stand or None, "rahmenvertraege": rvs, "contracts": fleet,
                "netto_factor": 1.0, "brutto_factor": brutto_factor,
                "rechnung_stand": rechnung_stand}

    # ---- Rechnungen / Kosten -------------------------------------------
    @app.post("/api/invoices", status_code=201, dependencies=[Depends(require_auth)])
    async def upload_invoice(file: UploadFile, db: Store = Depends(get_store)):
        safe_name = Path(file.filename or "").name
        if not safe_name.lower().endswith(".xml"):
            raise HTTPException(400, "Nur .xml-Rechnungen (XRechnung/UBL) werden akzeptiert.")
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
            raise HTTPException(400, "Rechnung konnte nicht gelesen werden (ungültiges XML?).")
        invoice_id = db.add_invoice(data)
        return {"invoice_id": invoice_id, "line_count": len(data.lines),
                "filename": data.filename}

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
        top = sorted(analytics.kosten_je_rufnummer(lines).items(),
                     key=lambda kv: -kv[1]["netto"])[:10]
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
            "top_treiber": [{"rufnummer": r, **v} for r, v in top],
            "diff": diff,
            "prev_period": prev.get("period_start") if prev else None,
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
