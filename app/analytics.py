"""Reine Auswertungsfunktionen über Contract-Dicts.

Kein DB-/IO-Zugriff — nimmt Listen von Contract-Dicts (wie
store.get_contracts liefert) und gibt Aggregate zurück. Damit gut testbar
und unabhängig von Persistenz/Web.

Datumsfelder kommen als ISO-Strings aus der DB; `_as_date` toleriert
zusätzlich datetime/date.
"""
from __future__ import annotations

import datetime as dt
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
    return [
        r for r in rows
        if (r.get("_report_date") or "", r.get("_report_id") or 0) == latest.get(r.get("rahmenvertrag"))
    ]


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
