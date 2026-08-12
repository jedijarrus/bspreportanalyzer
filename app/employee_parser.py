"""Liest die Mitarbeiterliste (xlsx) für den Abgleich gegen den Report.

Erwartet eine Kopfzeile mit **PersNr, Nachname, Vorname**. Der Abgleich läuft über
die Kostenstelle im BSP-Report, die dafür die PersNr tragen muss.
Nur Einlesen/Normalisieren, keine Persistenz.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import openpyxl

_REQUIRED = {"persnr", "nachname", "vorname"}
# akzeptierte Schreibweisen je Zielspalte (Header normalisiert: lower, ohne . - Leer)
_ALIASES = {
    "persnr": {"persnr", "personalnummer", "personalnr", "pnr"},
    "nachname": {"nachname"},
    "vorname": {"vorname"},
}


def _norm_header(h: Any) -> str:
    return str(h).strip().lower().replace(".", "").replace("-", "").replace(" ", "")


def _header_map(header) -> dict[int, str]:
    """Spaltenindex -> Zielspalte (persnr/nachname/vorname), unbekannte ignoriert."""
    out: dict[int, str] = {}
    for i, h in enumerate(header):
        if h is None:
            continue
        key = _norm_header(h)
        for ziel, namen in _ALIASES.items():
            if key in namen:
                out[i] = ziel
                break
    return out


def _read_header(path: str | Path):
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        return next(wb.active.iter_rows(values_only=True), ())
    finally:
        wb.close()


def is_employee_workbook(path: str | Path) -> bool:
    """True, wenn die Kopfzeile PersNr + Nachname + Vorname enthält."""
    try:
        header = _read_header(path)
    except Exception:
        return False
    return _REQUIRED <= set(_header_map(header).values())


def _persnr(v: Any) -> str | None:
    if v in (None, ""):
        return None
    s = str(v).strip()
    if s.endswith(".0"):   # Excel liefert Zahlen oft als float
        s = s[:-2]
    return s or None


def parse_employees(path: str | Path) -> list[dict[str, Any]]:
    """Mitarbeiterliste -> [{persnr, nachname, vorname}]. Leere Zeilen fallen raus."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        it = wb.active.iter_rows(values_only=True)
        hmap = _header_map(next(it, ()))
        out: list[dict[str, Any]] = []
        for raw in it:
            rec: dict[str, Any] = {"persnr": None, "nachname": None, "vorname": None}
            for i, ziel in hmap.items():
                if i < len(raw):
                    val = raw[i]
                    if ziel == "persnr":
                        rec["persnr"] = _persnr(val)
                    else:
                        rec[ziel] = str(val).strip() if val not in (None, "") else None
            if rec["persnr"] is None and rec["nachname"] is None and rec["vorname"] is None:
                continue
            out.append(rec)
        return out
    finally:
        wb.close()
