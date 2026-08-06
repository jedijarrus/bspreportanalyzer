"""Reine Auswertungsfunktionen über Contract-Dicts.

Kein DB-/IO-Zugriff — nimmt Listen von Contract-Dicts (wie
store.get_contracts liefert) und gibt Aggregate zurück. Damit gut testbar
und unabhängig von Persistenz/Web.

Datumsfelder kommen als ISO-Strings aus der DB; `_as_date` toleriert
zusätzlich datetime/date.
"""
from __future__ import annotations

import datetime as dt
import re
from collections import Counter
from typing import Any

# Felder, deren Änderung der Report-Vergleich meldet
DEFAULT_WATCH = (
    "tarif", "vertragsstatus", "sperren", "bindefristende", "kartentyp",
    "daten_optionen", "voice_optionen", "roaming_optionen", "vvl_berechtigung",
)


def _as_date(value: Any) -> dt.date | None:
    if value is None or value == "":
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


# ---- Aktuelle Flotte -----------------------------------------------------
def current_fleet(rows: list[dict]) -> list[dict]:
    """Aktueller Gesamtbestand über alle Rahmenverträge.

    Jeder Report ist ein Voll-Export *eines oder mehrerer* Rahmenverträge.
    Für jeden Rahmenvertrag zählt der **neueste** Report (größtes
    (_report_date, _report_id)); dessen Zeilen bilden den aktuellen Stand
    dieses RV. Vereinigung über alle RVs = aktuelle Flotte. Gekündigte
    Linien (im neueren Report fehlend) fallen damit korrekt weg.

    Erwartet je Zeile die Schlüssel `rahmenvertrag`, `_report_date`,
    `_report_id`.
    """
    # je Rahmenvertrag den neuesten (date, id) bestimmen
    latest: dict[str, tuple] = {}
    for r in rows:
        rv = r.get("rahmenvertrag")
        key = (r.get("_report_date") or "", r.get("_report_id") or 0)
        if rv not in latest or key > latest[rv]:
            latest[rv] = key
    union = [
        r for r in rows
        if (r.get("_report_date") or "", r.get("_report_id") or 0) == latest.get(r.get("rahmenvertrag"))
    ]
    # Dedup über die RV-Grenze: wechselt eine Nummer den Rahmenvertrag, steht sie im
    # letzten Report des ALTEN RV UND im neuen des neuen RV. Je normalisierter Rufnummer
    # den neuesten (_report_date, _report_id) behalten. Zeilen ohne Rufnummer bleiben alle.
    best: dict[str, tuple] = {}
    passthrough: list[dict] = []
    for r in union:
        nk = normalize_rufnummer(r.get("rufnummer"))
        if not nk:
            passthrough.append(r)
            continue
        key = (r.get("_report_date") or "", r.get("_report_id") or 0)
        if nk not in best or key > best[nk][0]:
            best[nk] = (key, r)
    return [r for _, r in best.values()] + passthrough


def fleet_freshness(fleet: list[dict], today: dt.date, max_age_days: int = 14) -> dict:
    """Frische der aktuellen Flotte je Rahmenvertrag bewerten.

    Ändert die Auswahl NICHT (das macht `current_fleet`), sondern berechnet
    nur, wie alt der zugrunde liegende Report-Stand je RV ist, und signalisiert
    „veraltet", wenn älter als `max_age_days`. So sieht der Nutzer immer die
    neuesten Daten, wird aber gewarnt, wenn nichts Frisches vorliegt.

    Rückgabe:
        {
          "max_age_tage": int,
          "stale": bool,                 # irgendein RV veraltet
          "stand_alter_tage": int|None,  # Alter des ÄLTESTEN RV-Stands (worst case)
          "rv": {rv: {"report_date": iso|None, "alter_tage": int|None, "stale": bool}},
        }

    Bezugsdatum ist `_report_date` (fachlicher Stand). Fehlt es, gilt der RV
    konservativ als veraltet. Zukunftsdatum (Alter < 0) gilt als frisch.
    """
    # neuestes Report-Datum je RV (Flotte enthält i.d.R. genau eines je RV)
    newest: dict[str, dt.date | None] = {}
    for c in fleet:
        rv = c.get("rahmenvertrag")
        if not rv:
            continue
        d = _as_date(c.get("_report_date"))
        if rv not in newest or (d is not None and (newest[rv] is None or d > newest[rv])):
            newest[rv] = d

    rv_map: dict[str, dict] = {}
    for rv, d in newest.items():
        if d is None:
            rv_map[rv] = {"report_date": None, "alter_tage": None, "stale": True}
        else:
            alter = (today - d).days
            rv_map[rv] = {"report_date": d.isoformat(), "alter_tage": alter,
                          "stale": alter > max_age_days}

    alter_werte = [v["alter_tage"] for v in rv_map.values() if v["alter_tage"] is not None]
    return {
        "max_age_tage": max_age_days,
        "stale": any(v["stale"] for v in rv_map.values()),
        "stand_alter_tage": max(alter_werte) if alter_werte else None,
        "rv": rv_map,
    }


# ---- Bindefrist / VVL ----------------------------------------------------
def bindefrist_buckets(contracts: list[dict], today: dt.date) -> dict[str, int]:
    """Linien nach Restlaufzeit der Bindefrist gruppieren."""
    q = today + dt.timedelta(days=90)
    y = today + dt.timedelta(days=365)
    buckets = {"abgelaufen": 0, "0-3_monate": 0, "3-12_monate": 0,
               ">12_monate": 0, "ohne_datum": 0}
    for c in contracts:
        d = _as_date(c.get("bindefristende"))
        if d is None:
            buckets["ohne_datum"] += 1
        elif d < today:
            buckets["abgelaufen"] += 1
        elif d < q:
            buckets["0-3_monate"] += 1
        elif d < y:
            buckets["3-12_monate"] += 1
        else:
            buckets[">12_monate"] += 1
    return buckets


def expiring(contracts: list[dict], today: dt.date, within_days: int = 90) -> list[dict]:
    """Linien, deren Bindefrist bereits abgelaufen ist oder bald ausläuft.

    Aufsteigend nach Bindefristende sortiert (dringendste zuerst).
    """
    limit = today + dt.timedelta(days=within_days)
    result = []
    for c in contracts:
        d = _as_date(c.get("bindefristende"))
        if d is not None and d <= limit:
            result.append(c)
    result.sort(key=lambda c: _as_date(c.get("bindefristende")))
    return result


# ---- Verteilungen --------------------------------------------------------
def distribution(contracts: list[dict], field: str) -> list[tuple[str, int]]:
    """Häufigkeit der Werte eines Feldes, absteigend."""
    counter: Counter[str] = Counter(
        c[field] for c in contracts if c.get(field) not in (None, "")
    )
    return counter.most_common()


def split_distribution(contracts: list[dict], field: str) -> list[tuple[str, int]]:
    """Wie distribution, aber komma-separierte Mehrfachwerte werden zerlegt.

    Telekom legt mehrere Optionen in EIN Feld ('Opt A, Opt B') — hier
    werden Einzeloptionen gezählt, nicht Kombinationen.
    """
    counter: Counter[str] = Counter()
    for c in contracts:
        val = c.get(field)
        if val in (None, ""):
            continue
        for part in str(val).split(","):
            part = part.strip()
            if part:
                counter[part] += 1
    return counter.most_common()


# ---- Bestand / Status ----------------------------------------------------
def inventory(contracts: list[dict]) -> dict[str, Any]:
    return {
        "total": len(contracts),
        "gesperrt": sum(1 for c in contracts if c.get("sperren") not in (None, "")),
        "nach_kartentyp": distribution(contracts, "kartentyp"),
        "nach_status": distribution(contracts, "vertragsstatus"),
    }


# ---- Vergleich -----------------------------------------------------------
def diff(old: list[dict], new: list[dict], key: str = "rufnummer",
         watch_fields: tuple[str, ...] = DEFAULT_WATCH) -> dict[str, Any]:
    """Vergleicht zwei Report-Snapshots anhand eines Schlüssels (Default Rufnummer)."""
    old_by = {c[key]: c for c in old if c.get(key)}
    new_by = {c[key]: c for c in new if c.get(key)}

    hinzugefuegt = sorted(set(new_by) - set(old_by))
    entfernt = sorted(set(old_by) - set(new_by))

    geaendert = []
    for k in sorted(set(old_by) & set(new_by)):
        aenderungen = [
            (f, old_by[k].get(f), new_by[k].get(f))
            for f in watch_fields
            if old_by[k].get(f) != new_by[k].get(f)
        ]
        if aenderungen:
            geaendert.append({"rufnummer": k, "aenderungen": aenderungen})

    return {"hinzugefuegt": hinzugefuegt, "entfernt": entfernt, "geaendert": geaendert}


# ---- Rufnummer-Normalisierung --------------------------------------------
def normalize_rufnummer(r: Any) -> str | None:
    """Rufnummer auf einheitliche Form bringen (Join Report <-> Rechnung).

    Vereinheitlicht Trennzeichen und Länderpräfix: Report liefert z. B. das
    49er-Präfix ohne Plus, die Rechnung '+49-…' mit Trennstrichen. Ergebnis:
    nur Ziffern mit führender '0' statt '49'.
    """
    if r is None or r == "":
        return None
    d = re.sub(r"\D", "", str(r))
    if d.startswith("0049"):
        d = d[2:]
    if d.startswith("49"):
        d = "0" + d[2:]
    return d or None


# ---- Rechnungs-/Kostenauswertungen ---------------------------------------
def _amt(line: dict) -> float:
    v = line.get("amount")
    return float(v) if v is not None else 0.0


def kosten_je_rufnummer(lines: list[dict]) -> dict[str, dict[str, float]]:
    """Kosten je Rufnummer: netto + Aufschlüsselung nach Kategorie."""
    out: dict[str, dict[str, float]] = {}
    for l in lines:
        ruf = l.get("rufnummer")
        if not ruf:
            continue
        d = out.setdefault(ruf, {"netto": 0.0, "grundpreis": 0.0, "option": 0.0,
                                 "rabatt": 0.0, "verbrauch": 0.0})
        a = _amt(l)
        d["netto"] += a
        cat = l.get("category")
        if cat in d:
            d[cat] += a
    return out


def kosten_je_kostenstelle(lines: list[dict]) -> list[dict]:
    """Kosten je Kostenstelle (netto) + Anzahl unterschiedlicher Rufnummern."""
    agg: dict[str, dict] = {}
    for l in lines:
        kst = l.get("kostenstelle") or "(ohne)"
        d = agg.setdefault(kst, {"kostenstelle": kst, "netto": 0.0, "_rufs": set()})
        d["netto"] += _amt(l)
        if l.get("rufnummer"):
            d["_rufs"].add(l["rufnummer"])
    result = [{"kostenstelle": d["kostenstelle"], "netto": d["netto"],
               "anzahl_rufnummern": len(d["_rufs"])} for d in agg.values()]
    result.sort(key=lambda x: -x["netto"])
    return result


def kosten_je_kategorie(lines: list[dict]) -> list[tuple[str, float]]:
    agg: dict[str, float] = {}
    for l in lines:
        agg[l.get("category") or "?"] = agg.get(l.get("category") or "?", 0.0) + _amt(l)
    return sorted(agg.items(), key=lambda x: -abs(x[1]))


def _netto_map(lines: list[dict], key: str) -> dict[str, float]:
    m: dict[str, float] = {}
    for l in lines:
        k = l.get(key)
        if k is None:
            continue
        m[k] = m.get(k, 0.0) + _amt(l)
    return m


def invoice_diff(alt: list[dict], neu: list[dict]) -> dict:
    """Vergleich zweier Rechnungen: Δ netto gesamt, je Kostenstelle/Kategorie/
    Rufnummer (größte Änderungen zuerst) + neu/weggefallen."""
    def deltas(key):
        a, n = _netto_map(alt, key), _netto_map(neu, key)
        rows = [{key: k, "alt": round(a.get(k, 0.0), 2), "neu": round(n.get(k, 0.0), 2),
                 "delta": round(n.get(k, 0.0) - a.get(k, 0.0), 2)}
                for k in set(a) | set(n)]
        rows.sort(key=lambda r: -abs(r["delta"]))
        return rows

    a_ruf, n_ruf = _netto_map(alt, "rufnummer"), _netto_map(neu, "rufnummer")
    return {
        "gesamt": {"alt": round(sum(a_ruf.values()) + sum(_amt(l) for l in alt if not l.get("rufnummer")), 2),
                   "neu": round(sum(n_ruf.values()) + sum(_amt(l) for l in neu if not l.get("rufnummer")), 2),
                   "delta": round(sum(_amt(l) for l in neu) - sum(_amt(l) for l in alt), 2)},
        "je_kostenstelle": deltas("kostenstelle"),
        "je_kategorie": deltas("category"),
        "je_rufnummer": deltas("rufnummer"),
        "neu": sorted(set(n_ruf) - set(a_ruf)),
        "weggefallen": sorted(set(a_ruf) - set(n_ruf)),
    }


def reconcile(lines: list[dict], total_net: float) -> dict:
    """Abgleich: zugeordnete Kosten (mit Rufnummer) vs. nicht zugeordnet vs. Rechnungs-Netto."""
    zug = sum(_amt(l) for l in lines if l.get("rufnummer"))
    nicht = sum(_amt(l) for l in lines if not l.get("rufnummer"))
    rufs = {l["rufnummer"] for l in lines if l.get("rufnummer")}
    return {
        "zugeordnet": round(zug, 2), "nicht_zugeordnet": round(nicht, 2),
        "anzahl_rufnummern": len(rufs), "total_net": round(total_net, 2),
        "differenz": round(total_net - (zug + nicht), 2),
    }


def datenauslastung(lines: list[dict]) -> dict:
    """Aggregierte Datenauslastung: verbraucht vs. vereinbart."""
    rows = [(l["data_contracted_gb"], l.get("data_used_gb") or 0.0)
            for l in lines if l.get("data_contracted_gb")]
    n = len(rows)
    gebucht = sum(c for c, _ in rows)
    verbraucht = sum(u for _, u in rows)
    return {
        "anzahl": n,
        "gebucht_gb": round(gebucht, 1),
        "verbraucht_gb": round(verbraucht, 1),
        "auslastung_pct": round(verbraucht / gebucht * 100, 1) if gebucht else 0.0,
        "ueber_100": sum(1 for c, u in rows if u > c),
        "unter_25": sum(1 for c, u in rows if c and u < 0.25 * c),
        "unter_10": sum(1 for c, u in rows if c and u < 0.10 * c),
    }


def datenauslastung_liste(lines: list[dict]) -> list[dict]:
    """Je Datenzeile: gebucht/verbraucht/Auslastung%, aufsteigend (schlechteste zuerst).
    Anonym — die Zeilen tragen keine Rufnummer."""
    rows = []
    for l in lines:
        c = l.get("data_contracted_gb")
        if not c:
            continue
        u = l.get("data_used_gb") or 0.0
        rows.append({"gebucht_gb": round(c, 1), "verbraucht_gb": round(u, 2),
                     "pct": round(u / c * 100, 1) if c else 0.0})
    rows.sort(key=lambda r: r["pct"])
    return rows


def kosten_trend(lines: list[dict]) -> list[dict]:
    """Netto-Kosten je Rechnungsperiode (aus _period_start), chronologisch."""
    agg: dict[str, float] = {}
    for l in lines:
        p = l.get("_period_start") or l.get("period_start") or ""
        agg[p] = agg.get(p, 0.0) + _amt(l)
    return [{"period": p, "netto": v} for p, v in sorted(agg.items())]


def fleet_gb_trend(lines: list[dict]) -> list[dict]:
    """Verbrauchte GB der ganzen Flotte je Rechnungsperiode (absolute Menge).

    Sinnvoll bei Unlimited-Tarifen, wo die Auslastung % (verbraucht/gebucht)
    keinen Nenner mehr hat.
    """
    agg: dict[str, float] = {}
    for l in lines:
        u = l.get("data_used_gb")
        if u is None:
            continue
        p = l.get("_period_start") or l.get("period_start") or ""
        agg[p] = agg.get(p, 0.0) + u
    return [{"period": p, "gb": round(v, 1)} for p, v in sorted(agg.items())]


def zuordnungsluecken(lines: list[dict], fleet: list[dict]) -> dict:
    """Lücken zwischen Rechnung und Flotte (Prüfung):
    - `geister`: Rufnummer auf der Rechnung, aber kein aktiver Vertrag (Geister-SIM)
    - `ohne_rechnung`: aktiver Vertrag ohne jede Rechnungsposition
    Rückgabe in Original-Schreibweise (nicht normalisiert).
    """
    inv: dict[str, str] = {}
    for l in lines:
        r = l.get("rufnummer")
        nk = normalize_rufnummer(r) if r else None
        if nk:
            inv.setdefault(nk, r)
    flt: dict[str, str] = {}
    for c in fleet:
        r = c.get("rufnummer")
        nk = normalize_rufnummer(r) if r else None
        if nk:
            flt.setdefault(nk, r)
    return {
        "geister": sorted(inv[k] for k in set(inv) - set(flt)),
        "ohne_rechnung": sorted(flt[k] for k in set(flt) - set(inv)),
    }


def top_rufnummer_gesamt(lines: list[dict], nutzer_map: dict, n: int = 12) -> list[dict]:
    """Top-Kostentreiber über ALLE Rechnungen — **je Rufnummer** (unique).

    Netto je Rufnummer über alle Rechnungen summiert, absteigend. Der Nutzer wird
    nur angezeigt (aus `nutzer_map`: normalisierte Rufnummer → Nutzer, aus dem
    Report). Bewusst NICHT nach Nutzer gruppiert — Pools haben mehrere Rufnummern
    unter gleichem/leerem Nutzer, die sonst falsch zusammengefasst würden.
    """
    rows = [{"rufnummer": ruf, "netto": round(v["netto"], 2),
             "nutzer": nutzer_map.get(normalize_rufnummer(ruf))}
            for ruf, v in kosten_je_rufnummer(lines).items()]
    rows.sort(key=lambda r: -r["netto"])
    return rows[:n]


# ---- Rufnummer-Monitoring (Verlauf über Monate) --------------------------
def linie_verlauf(all_lines: list[dict], rufnummer: str) -> list[dict]:
    """Monatsreihe EINER Rufnummer über alle Rechnungen.

    `all_lines` = Zeilen aller Rechnungen (mit `_period_start`), wie
    store.all_invoice_lines liefert. Ergebnis je Periode chronologisch:
    netto / grundpreis / optionen / rabatt / verbrauch, Datenvolumen
    gebucht+verbraucht + auslastung_pct, sowie die Options-Namen.
    """
    target = normalize_rufnummer(rufnummer)
    by_period: dict[str, dict] = {}
    opt_by_period: dict[str, dict[str, float]] = {}
    rab_by_period: dict[str, dict[str, float]] = {}
    verb_by_period: dict[str, dict[str, float]] = {}
    for l in all_lines:
        if normalize_rufnummer(l.get("rufnummer")) != target:
            continue
        p = l.get("_period_start") or l.get("period_start") or ""
        m = by_period.setdefault(p, {
            "period": p, "netto": 0.0, "grundpreis": 0.0, "optionen": 0.0,
            "rabatt": 0.0, "verbrauch": 0.0, "data_contracted_gb": None,
            "data_used_gb": None, "optionen_namen": [], "optionen_posten": []})
        amt = l.get("amount") or 0.0
        m["netto"] += amt
        cat = l.get("category")
        if cat == "grundpreis":
            m["grundpreis"] += amt
        elif cat == "option":
            m["optionen"] += amt
            name = (l.get("item_name") or "").strip()
            if name and name not in m["optionen_namen"]:
                m["optionen_namen"].append(name)
            posten = opt_by_period.setdefault(p, {})
            posten[name] = posten.get(name, 0.0) + amt
        elif cat == "rabatt":
            m["rabatt"] += amt
            rname = (l.get("item_name") or "Rabatt").strip() or "Rabatt"
            rp = rab_by_period.setdefault(p, {})
            rp[rname] = rp.get(rname, 0.0) + amt
        elif cat == "verbrauch":
            m["verbrauch"] += amt
            vname = (l.get("item_name") or "Verbrauch").strip() or "Verbrauch"
            vp = verb_by_period.setdefault(p, {})
            vp[vname] = vp.get(vname, 0.0) + amt
        cg, ug = l.get("data_contracted_gb"), l.get("data_used_gb")
        if cg is not None:
            m["data_contracted_gb"] = cg
        if ug is not None:
            m["data_used_gb"] = ug

    out = []
    for m in by_period.values():
        for k in ("netto", "grundpreis", "optionen", "rabatt", "verbrauch"):
            m[k] = round(m[k], 2)
        cg, ug = m["data_contracted_gb"], m["data_used_gb"] or 0.0
        m["auslastung_pct"] = round(ug / cg * 100, 1) if cg else None
        m["optionen_posten"] = [{"name": n, "amount": round(a, 2)}
                                for n, a in opt_by_period.get(m["period"], {}).items()]
        m["rabatte_posten"] = [{"name": n, "amount": round(a, 2)}
                               for n, a in rab_by_period.get(m["period"], {}).items()]
        m["verbrauch_posten"] = [{"name": n, "amount": round(a, 2)}
                                 for n, a in verb_by_period.get(m["period"], {}).items()]
        out.append(m)
    out.sort(key=lambda x: x["period"])
    return out


def linie_auffaelligkeiten(verlauf: list[dict], sprung_eur: float = 10.0,
                           sprung_pct: float = 30.0, rabatt_eur: float = 1.0) -> list[dict]:
    """Monat-zu-Monat-Auffälligkeiten EINER Linie (nur Fakten, kein Sparen).

    Erkennt: Overage (>100% je Monat), Kostensprung (|Δ|≥sprung_eur UND
    ≥sprung_pct des Vormonats), Rabatt weg/gesunken (≥rabatt_eur), Option
    hinzu/entfallen. `verlauf` = Ausgabe von linie_verlauf.
    """
    out: list[dict] = []
    for i, m in enumerate(verlauf):
        pct = m.get("auslastung_pct")
        if pct is not None and pct > 100:
            out.append({"period": m["period"], "typ": "overage",
                        "text": f"Datenvolumen {pct:.0f}% ausgelastet", "delta_eur": None})
        if i == 0:
            continue
        prev = verlauf[i - 1]
        d = round(m["netto"] - prev["netto"], 2)
        base = prev["netto"]
        if abs(d) >= sprung_eur and (base == 0 or abs(d) / abs(base) * 100 >= sprung_pct):
            out.append({"period": m["period"], "typ": "kostensprung",
                        "text": f"Netto {'+' if d >= 0 else ''}{d:.2f} € ggü. Vormonat",
                        "delta_eur": d})
        drab = round(abs(prev.get("rabatt") or 0) - abs(m.get("rabatt") or 0), 2)
        if drab >= rabatt_eur:
            out.append({"period": m["period"], "typ": "rabatt_weg",
                        "text": f"Rabatt {drab:.2f} € geringer als Vormonat", "delta_eur": drab})
        prev_opt = set(prev.get("optionen_namen") or [])
        cur_opt = set(m.get("optionen_namen") or [])
        for name in sorted(cur_opt - prev_opt):
            out.append({"period": m["period"], "typ": "option_neu",
                        "text": f"Option neu: {name}", "delta_eur": None})
        for name in sorted(prev_opt - cur_opt):
            out.append({"period": m["period"], "typ": "option_weg",
                        "text": f"Option entfallen: {name}", "delta_eur": None})
    return out


# ---- Trend ---------------------------------------------------------------
def trend(snapshots: list[dict], today: dt.date) -> list[dict[str, Any]]:
    """Zeitreihe von Kennzahlen über mehrere Report-Snapshots.

    snapshots: [{'report_date': iso, 'contracts': [...]}].
    """
    out = []
    for snap in snapshots:
        contracts = snap["contracts"]
        buckets = bindefrist_buckets(contracts, today)
        out.append({
            "report_date": snap["report_date"],
            "total": len(contracts),
            "gesperrt": sum(1 for c in contracts if c.get("sperren") not in (None, "")),
            "ablaufend_90": buckets["abgelaufen"] + buckets["0-3_monate"],
        })
    out.sort(key=lambda s: s["report_date"] or "")
    return out
