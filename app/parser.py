"""Liest Telekom-BSP-RVKU-KI-Reports (xlsx) in normalisierte Zeilen-Dicts.

Verantwortung: nur Einlesen + Normalisieren. Keine Persistenz, keine Analyse.
Erkenntnisse aus den Echtdaten, die hier umgesetzt sind:
- Datumsfelder kommen als datetime (openpyxl data_only) und bleiben datetime.
- '\' ist der Telekom-Leer-Platzhalter -> None.
- Leerstrings -> None.
- Report-Datum steckt im Dateinamen (YYYYMMDD-HHMMSS_...).
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import openpyxl

from app import schema

_DATE_RE = re.compile(r"^(\d{8})-(\d{6})")
_EMPTY_VALUES = {"", "\\"}


@dataclass
class ReportData:
    """Ergebnis des Parsens: Metadaten + normalisierte Zeilen."""
    filename: str
    report_date: dt.datetime | None
    rows: list[dict[str, Any]]


def report_date_from_name(name: str) -> dt.datetime | None:
    m = _DATE_RE.match(name)
    if not m:
        return None
    return dt.datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")


def _normalize(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        v = value.strip()
        return None if v in _EMPTY_VALUES else v
    return value


def parse_report(path: str | Path) -> ReportData:
    path = Path(path)
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active

    rows_iter = ws.iter_rows(values_only=True)
    header = next(rows_iter)
    # Spalten-Index -> Feldname (unbekannte Header werden ignoriert)
    known = set(schema.FIELDS)
    col_to_field: dict[int, str] = {}
    for i, h in enumerate(header):
        if h is None:
            continue
        field = schema.normalize_header(str(h))
        if field in known:
            col_to_field[i] = field

    rows: list[dict[str, Any]] = []
    for raw in rows_iter:
        record = {f: None for f in schema.FIELDS}
        for i, field in col_to_field.items():
            if i < len(raw):
                record[field] = _normalize(raw[i])
        if all(v is None for v in record.values()):
            continue  # komplett leere Zeile überspringen
        rows.append(record)

    wb.close()
    return ReportData(
        filename=path.name,
        report_date=report_date_from_name(path.name),
        rows=rows,
    )
