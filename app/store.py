"""SQLite-Persistenz für Reports und ihre Contract-Zeilen.

Ein Report = ein Upload-Snapshot. Löschen eines Reports entfernt per
CASCADE alle zugehörigen Contracts. Datumswerte werden als ISO-Strings
gespeichert (SQLite kennt keinen nativen datetime-Typ).
"""
from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path
from typing import Any

from app import schema
from app.parser import ReportData

# Spaltendefinition der contracts-Tabelle aus dem kanonischen Schema
_CONTRACT_COLS = ", ".join(f'"{f}" TEXT' for f in schema.FIELDS)
_CONTRACT_FIELDS = list(schema.FIELDS)

# Spalten einer Rechnungsposition (Reihenfolge = Werte-Reihenfolge beim Insert)
_INVOICE_LINE_COLS = [
    "rufnummer", "kostenstelle", "kostenstellennutzer", "item_name", "category",
    "amount", "quantity", "price", "period_start", "period_end",
    "data_contracted_gb", "data_used_gb", "vertragsbeginn", "mindestlaufzeit_ende",
]
_INVOICE_LINE_NUM = {"amount", "quantity", "price", "data_contracted_gb", "data_used_gb"}


class Store:
    def __init__(self, db_path: str | Path):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: FastAPI bedient sync-Routen aus einem
        # Threadpool; bei genau einem Nutzer ist das unkritisch.
        self.con = sqlite3.connect(str(self.path), check_same_thread=False)
        self.con.row_factory = sqlite3.Row
        self.con.execute("PRAGMA foreign_keys = ON")
        self._create_schema()

    def _create_schema(self) -> None:
        self.con.execute(
            """
            CREATE TABLE IF NOT EXISTS reports (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                filename    TEXT NOT NULL,
                report_date TEXT,
                row_count   INTEGER NOT NULL,
                imported_at TEXT NOT NULL
            )
            """
        )
        self.con.execute(
            f"""
            CREATE TABLE IF NOT EXISTS contracts (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                report_id INTEGER NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
                {_CONTRACT_COLS}
            )
            """
        )
        self.con.execute(
            "CREATE INDEX IF NOT EXISTS idx_contracts_report ON contracts(report_id)"
        )
        self.con.execute(
            "CREATE INDEX IF NOT EXISTS idx_contracts_rufnummer ON contracts(rufnummer)"
        )
        self.con.execute(
            "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)"
        )
        # Notizen je Vertrag (Schlüssel = rahmenvertrag|rufnummer, report-übergreifend)
        self.con.execute(
            "CREATE TABLE IF NOT EXISTS notes (key TEXT PRIMARY KEY, note TEXT NOT NULL)"
        )
        # Rechnungen (Telekom-CSV) + Positionen
        self.con.execute(
            """
            CREATE TABLE IF NOT EXISTS invoices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                invoice_number TEXT,
                kundenkonto TEXT,
                issue_date TEXT,
                due_date TEXT,
                period_start TEXT,
                period_end TEXT,
                total_net REAL,
                total_tax REAL,
                total_gross REAL,
                line_count INTEGER NOT NULL,
                imported_at TEXT NOT NULL
            )
            """
        )
        self.con.execute(
            f"""
            CREATE TABLE IF NOT EXISTS invoice_lines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                invoice_id INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
                {", ".join(f'"{c}" {"REAL" if c in _INVOICE_LINE_NUM else "TEXT"}' for c in _INVOICE_LINE_COLS)}
            )
            """
        )
        self.con.execute("CREATE INDEX IF NOT EXISTS idx_il_invoice ON invoice_lines(invoice_id)")
        self.con.execute("CREATE INDEX IF NOT EXISTS idx_il_rufnummer ON invoice_lines(rufnummer)")
        self.con.execute("CREATE INDEX IF NOT EXISTS idx_il_kostenstelle ON invoice_lines(kostenstelle)")
        self.con.commit()

    # ---- Notizen --------------------------------------------------------
    def get_notes(self) -> dict[str, str]:
        return {r["key"]: r["note"] for r in self.con.execute("SELECT key, note FROM notes")}

    def set_note(self, key: str, note: str) -> None:
        if note and note.strip():
            self.con.execute(
                "INSERT INTO notes (key, note) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET note = excluded.note",
                (key, note.strip()),
            )
        else:
            self.con.execute("DELETE FROM notes WHERE key = ?", (key,))
        self.con.commit()

    # ---- Schlüssel/Wert-Einstellungen (z.B. Passwort-Hash) --------------
    def get_setting(self, key: str) -> str | None:
        row = self.con.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None

    def set_setting(self, key: str, value: str) -> None:
        self.con.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        self.con.commit()

    @staticmethod
    def _ser(value: Any) -> Any:
        if isinstance(value, dt.datetime):
            return value.isoformat()
        if isinstance(value, dt.date):
            return value.isoformat()
        return value

    def add_report(self, data: ReportData) -> int:
        cur = self.con.execute(
            "INSERT INTO reports (filename, report_date, row_count, imported_at) "
            "VALUES (?, ?, ?, ?)",
            (
                data.filename,
                data.report_date.isoformat() if data.report_date else None,
                len(data.rows),
                dt.datetime.now().isoformat(timespec="seconds"),
            ),
        )
        report_id = cur.lastrowid
        cols = ", ".join(f'"{f}"' for f in _CONTRACT_FIELDS)
        placeholders = ", ".join("?" * (len(_CONTRACT_FIELDS) + 1))
        self.con.executemany(
            f'INSERT INTO contracts (report_id, {cols}) VALUES ({placeholders})',
            [
                (report_id, *[self._ser(row.get(f)) for f in _CONTRACT_FIELDS])
                for row in data.rows
            ],
        )
        self.con.commit()
        return report_id

    def list_reports(self) -> list[dict[str, Any]]:
        rows = self.con.execute(
            "SELECT id, filename, report_date, row_count, imported_at "
            "FROM reports ORDER BY report_date, id"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_contracts(self, report_id: int) -> list[dict[str, Any]]:
        rows = self.con.execute(
            "SELECT * FROM contracts WHERE report_id = ? ORDER BY id", (report_id,)
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d.pop("id", None)
            d.pop("report_id", None)
            result.append(d)
        return result

    def all_contracts(self) -> list[dict[str, Any]]:
        """Alle Verträge über alle Reports, je Zeile mit Report-Metadaten
        (`_report_id`, `_report_date`) angereichert."""
        rows = self.con.execute(
            "SELECT c.*, r.report_date AS _rdate FROM contracts c "
            "JOIN reports r ON r.id = c.report_id"
        ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["_report_id"] = d.pop("report_id")
            d["_report_date"] = d.pop("_rdate")
            d.pop("id", None)
            result.append(d)
        return result

    # ---- Rechnungen -----------------------------------------------------
    def add_invoice(self, data) -> int:
        cur = self.con.execute(
            "INSERT INTO invoices (filename, invoice_number, kundenkonto, issue_date, "
            "due_date, period_start, period_end, total_net, total_tax, total_gross, "
            "line_count, imported_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (data.filename, data.invoice_number, data.kundenkonto, data.issue_date,
             data.due_date, data.period_start, data.period_end, data.total_net,
             data.total_tax, data.total_gross, len(data.lines),
             dt.datetime.now().isoformat(timespec="seconds")),
        )
        invoice_id = cur.lastrowid
        cols = ", ".join(f'"{c}"' for c in _INVOICE_LINE_COLS)
        ph = ", ".join("?" * (len(_INVOICE_LINE_COLS) + 1))
        self.con.executemany(
            f"INSERT INTO invoice_lines (invoice_id, {cols}) VALUES ({ph})",
            [(invoice_id, *[line.get(c) for c in _INVOICE_LINE_COLS]) for line in data.lines],
        )
        self.con.commit()
        return invoice_id

    def list_invoices(self) -> list[dict[str, Any]]:
        rows = self.con.execute(
            "SELECT id, filename, invoice_number, issue_date, period_start, period_end, "
            "total_net, total_tax, total_gross, line_count, imported_at "
            "FROM invoices ORDER BY period_start, id"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_invoice_lines(self, invoice_id: int) -> list[dict[str, Any]]:
        rows = self.con.execute(
            "SELECT * FROM invoice_lines WHERE invoice_id = ? ORDER BY id", (invoice_id,)
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d.pop("id", None)
            d.pop("invoice_id", None)
            out.append(d)
        return out

    def all_invoice_lines(self) -> list[dict[str, Any]]:
        """Alle Positionen über alle Rechnungen, angereichert mit Rechnungs-Meta."""
        rows = self.con.execute(
            "SELECT il.*, i.period_start AS _period_start, i.period_end AS _period_end, "
            "i.issue_date AS _issue_date FROM invoice_lines il JOIN invoices i ON i.id = il.invoice_id"
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["_invoice_id"] = d.pop("invoice_id")
            d.pop("id", None)
            out.append(d)
        return out

    def delete_invoice(self, invoice_id: int) -> None:
        self.con.execute("DELETE FROM invoices WHERE id = ?", (invoice_id,))
        self.con.commit()

    def delete_report(self, report_id: int) -> None:
        self.con.execute("DELETE FROM reports WHERE id = ?", (report_id,))
        self.con.commit()

    def close(self) -> None:
        self.con.close()
